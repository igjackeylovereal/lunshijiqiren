#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function
import argparse
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
import wave
from access_gate import AccessGate
from map_tools import pixel_goal, map_catalog
try:
    from Cookie import SimpleCookie
except ImportError:
    from http.cookies import SimpleCookie
from collections import deque
try:
    from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
    from SocketServer import ThreadingMixIn
except ImportError:
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from socketserver import ThreadingMixIn
from core import Controller, SimNavigation, as_text
from face_recognition import FaceDetector, IdentityWindow, face_sample

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def save_json(path, value):
    temporary = path + '.tmp'
    with io.open(temporary, 'w', encoding='utf-8') as stream:
        stream.write(as_text(json.dumps(value, ensure_ascii=False, indent=2)))
    os.rename(temporary, path)


def parse_ros_response(output):
    import yaml
    class ResponseLoader(yaml.SafeLoader):
        pass
    # ROS Kinetic 的 rosservice 会把中文字符串输出为 !!python/str。
    # 只允许这个标量标签，不能改用可执行任意 Python 标签的 yaml.load 默认加载器。
    ResponseLoader.add_constructor('tag:yaml.org,2002:python/str',
                                   lambda loader, node: loader.construct_scalar(node))
    result = yaml.load(output, Loader=ResponseLoader)
    if not isinstance(result, dict):
        raise ValueError('服务返回格式无效')
    return result


class Application(object):
    def __init__(self, args):
        import cv2
        self.cv2, self.args = cv2, args
        with io.open(args.config, encoding='utf-8') as stream:
            self.config = json.load(stream)
        self.data = os.path.abspath(os.path.expanduser(args.data))
        for directory in (self.data, self.data + '/faces', self.data + '/audio'):
            if not os.path.isdir(directory):
                os.makedirs(directory, 0o700)
        self.lock = threading.RLock()
        self.model_lock = threading.RLock()
        self.logs = []
        self.voice = {'busy': False, 'last_text': '', 'error': '', 'tts': '尚未测试', 'asr': '尚未测试',
                      'audio_sequence': 0, 'output': self.config.get('audio_output', 'pc')}
        self.runtime, self.ros_error = None, ''
        if args.ros:
            try:
                from ros_adapter import RosRuntime
                self.runtime = RosRuntime(self.config)
            except Exception as exc:
                self.ros_error = as_text(exc)
        if args.allow_motion:
            if self.runtime is None:
                raise ValueError('没有 ROS 连接，不启用实际运动')
            from ros_adapter import LiveNavigation
            navigation = LiveNavigation(self.config, self.runtime, True)
        else:
            navigation = SimNavigation()
        self.controller = Controller(self.config, navigation, self.log)
        self.access = AccessGate(self.config["people"],
                                cache_path=os.path.join(self.data, "sessions.json"))
        self.selected_map = None
        self.mapping = None
        if args.mapping_teleop:
            if self.runtime is None or args.allow_motion:
                raise ValueError('人工建图需要 ROS，且不能同时启用服务导航')
            from mapping_control import MappingControl
            self.mapping = MappingControl(self.runtime, args.mapping_test_speed, args.mapping_keyboard)
            self.controller.reply = '人工遥控建图已就绪，请在电脑页面进行微动测试。'
        self.camera = {'ready': False, 'frames': 0, 'face_count': 0, 'last_identity': None, 'paused_for_session': False,
                       'error': '', 'enrollment': None, 'samples': {}}
        self.frame_jpeg = None
        self.model = None
        self.id_labels = {}
        self.enrollment = None
        self.identity_window = IdentityWindow(self.config.get('recognition_vote_required', 4),
                                               self.config.get('recognition_vote_window', 6))
        self.last_face_seen = 0
        self.recognition_history = deque(maxlen=600)
        self.enrollment_last_crop = None
        self.detector = FaceDetector(cv2, os.path.join(ROOT, 'assets'), config_path=args.config, data_path=self.data)
        self.camera.update(detector=self.detector.name, detector_error=self.detector.error,
                           quality=None, guidance='请露出完整正脸，面向光源', threshold=self.config['recognition_threshold'],
                           embedding_threshold=self.config.get('embedding_similarity_threshold', .82))
        self.retrain()
        self.stopping = threading.Event()
        self.last_session_activity = 0.0
        self.voice_flow = {'awake': False, 'mode': 'chat', 'choosing': False, 'last': 0}
        self.voice_cmd_pub = None
        if self.runtime:
            try:
                from geometry_msgs.msg import Twist
                self.voice_cmd_pub = self.runtime.rospy.Publisher('/cmd_vel', Twist, queue_size=1)
            except Exception:
                self.voice_cmd_pub = None
        self.session_idle_seconds = 120
        self.start_thread(self.camera_loop)
        self.start_thread(self.control_loop)

    def session_active(self):
        """配置页仍在使用（最近有接口请求）时，认为会话活跃。"""
        return (time.time() - self.last_session_activity) < self.session_idle_seconds

    def ensure_session_person(self, person):
        """把浏览器会话里已认证的人员直接写进交互状态机。"""
        current = self.controller.snapshot()['person']
        if current and current['id'] == person['id']:
            self.controller.touch()
            return
        try:
            self.controller.authorize(person['id'])
        except Exception as exc:
            self.log(dict(kind='session_authorize_failed', reason=as_text(exc), time=time.time()))

    def start_thread(self, function):
        thread = threading.Thread(target=function)
        thread.daemon = True
        thread.start()
        return thread

    def log(self, event):
        with self.lock:
            self.logs.append(event)
            self.logs = self.logs[-100:]
            with io.open(self.data + '/events.jsonl', 'a', encoding='utf-8') as stream:
                stream.write(as_text(json.dumps(event, ensure_ascii=False)) + '\n')

    def retrain(self):
        import numpy as np
        images, labels, id_labels, counts = [], [], {}, {}
        for label, person in enumerate(self.config['people']):
            directory = self.data + '/faces/' + person['id']
            samples = []
            if os.path.isdir(directory):
                for filename in sorted(os.listdir(directory)):
                    if filename.endswith('.png'):
                        image = self.cv2.imread(directory + '/' + filename, 0)
                        if image is not None and image.shape == (128, 128):
                            samples.append(image)
            counts[person['id']] = len(samples)
            if len(samples) >= 20 and person.get('authorized'):
                images.extend(samples)
                labels.extend([label] * len(samples))
                id_labels[label] = person['id']
        model = None
        if images:
            model = self.cv2.face.LBPHFaceRecognizer_create(radius=1, neighbors=8, grid_x=8, grid_y=8)
            model.train(images, np.asarray(labels, dtype=np.int32))
            model.write(self.data + '/model.yml')
        with self.model_lock:
            self.model, self.id_labels = model, id_labels
            self.camera['samples'] = counts
        if hasattr(self, 'stopping'):
            self.detector.reload_gallery()

    def enroll(self, person_id):
        if person_id not in [p['id'] for p in self.config['people']]:
            raise ValueError('未知人员编号')
        if not self.camera['ready']:
            raise ValueError('彩色相机尚未就绪')
        if self.enrollment:
            raise ValueError('已有录入任务，请等待完成或超时')
        self.controller.invalidate_identity('正在补录样本，暂停身份交互')
        self.identity_window.clear()
        self.enrollment_last_crop = None
        self.enrollment = dict(person_id=person_id, count=0, target=self.config['enrollment_samples'],
                               last=0, deadline=time.time() + 120)
        self.log(dict(kind='enrollment_started', person_id=person_id, time=time.time()))

    def open_camera(self):
        device = self.config['camera_device']
        if not isinstance(device, int):
            target = os.path.realpath(device)
            if not os.path.exists(target) or not target.startswith('/dev/video'):
                return self.cv2.VideoCapture()
            device = int(target[len('/dev/video'):])
        controls = self.config.get('camera_controls', {})
        supported = {'brightness': (-64, 64), 'gamma': (100, 300), 'backlight_compensation': (0, 3)}
        settings = []
        for key, value in controls.items():
            if key not in supported or isinstance(value, bool) or not isinstance(value, int):
                continue
            if supported[key][0] <= value <= supported[key][1]:
                settings.append('%s=%d' % (key, value))
        if settings:
            try:
                with open(os.devnull, 'w') as null:
                    subprocess.check_call(['timeout', '3', 'v4l2-ctl', '-d', '/dev/video%d' % device,
                                           '--set-ctrl=' + ','.join(settings)], stdout=null, stderr=null)
                self.camera['control_error'] = ''
            except Exception:
                self.camera['control_error'] = '无法应用相机亮度配置，请检查 v4l2-ctl'
        return self.cv2.VideoCapture(device)

    def camera_loop(self):
        cap = self.open_camera()
        cap.set(3, 640)
        cap.set(4, 480)
        while not self.stopping.is_set():
            try:
                ok, frame = cap.read()
                if not ok:
                    self.camera.update(ready=False, error='无法读取彩色相机')
                    self.frame_jpeg = None
                    cap.release()
                    time.sleep(2)
                    cap = self.open_camera()
                    cap.set(3, 640)
                    cap.set(4, 480)
                    continue
                self.camera.update(ready=True, error='')
                self.camera['frames'] += 1
                if self.session_active() and not self.enrollment:
                    # 已刷脸登录：暂停人脸检测，只保留画面预览
                    self.camera.update(paused_for_session=True, face_count=0, last_identity=None,
                                       guidance='已通过身份验证，人脸检测已暂停；退出配置或 120 秒无操作后恢复')
                    self.last_face_seen = time.time()
                    success, jpeg = self.cv2.imencode('.jpg', frame, [int(self.cv2.IMWRITE_JPEG_QUALITY), 75])
                    if success:
                        self.frame_jpeg = jpeg.tostring()
                    if self.runtime:
                        try:
                            self.runtime.publish_frame(frame)
                        except Exception:
                            pass
                    time.sleep(0.2)
                    continue
                self.camera['paused_for_session'] = False
                started = time.time()
                gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
                faces = self.detector.detect(frame)
                self.camera.update(detector=self.detector.name, detector_error=self.detector.error)
                self.camera.update(recognizer='OpenFace-128' if self.detector.embedding_ready else 'LBPH (fallback)',
                                   embedding_error=self.detector.embedding_error)
                self.camera['face_count'] = len(faces)
                self.camera['face_boxes'] = [dict(x=b[0], y=b[1], width=b[2], height=b[3]) for b in faces]
                if len(faces) > 1:
                    for index, (bx, by, bw, bh) in enumerate(faces):
                        self.cv2.rectangle(frame, (bx, by), (bx+bw, by+bh), (40, 40, 240), 2)
                        self.cv2.putText(frame, '#%d %dx%d' % (index+1, bw, bh),
                                         (bx, max(16, by-5)), self.cv2.FONT_HERSHEY_SIMPLEX, .5, (40, 40, 240), 1)
                person_id, distance = None, None
                self.camera.update(quality=None, guidance='未检测到人脸，请正对相机，露出完整正脸')
                if len(faces) == 1:
                    x, y, width, height = faces[0]
                    crop, quality, reason = face_sample(self.cv2, gray, faces[0])
                    self.camera.update(quality=quality, guidance=reason or '正脸清晰，正在匹配身份')
                    self.last_face_seen = time.time()
                    if self.enrollment:
                        en = self.enrollment
                        phase = en['count'] * 3 // en['target']
                        hints = ['正对相机，稍微改变距离', '缓慢向左、右小幅转头（保持双眼可见）', '回到正脸，稍抬头或低头，面向光源']
                        if not reason:
                            self.camera['guidance'] = hints[min(phase, 2)]
                        different = (self.enrollment_last_crop is None or
                                     self.cv2.absdiff(crop, self.enrollment_last_crop).mean() >= 3)
                        if time.time() - en['last'] >= 0.8 and not reason and different:
                            directory = self.data + '/faces/' + en['person_id']
                            if not os.path.isdir(directory):
                                os.makedirs(directory, 0o700)
                            path = directory + '/%d.png' % int(time.time() * 1000)
                            if not self.cv2.imwrite(path, crop):
                                raise IOError('无法保存录入样本')
                            en['count'] += 1
                            en['last'] = time.time()
                            self.enrollment_last_crop = crop.copy()
                            if en['count'] >= en['target']:
                                self.enrollment = None
                                self.retrain()
                                self.log(dict(kind='enrollment_completed', person_id=en['person_id'], count=en['count'], time=time.time()))
                    elif not reason:
                        with self.model_lock:
                            if self.model is not None:
                                label, distance = self.model.predict(crop)
                                if distance <= self.config['recognition_threshold']:
                                    person_id = self.id_labels.get(label)
                        if self.detector.embedding_ready:
                            match = self.detector.identity_match or {}
                            person_id = match.get('person_id')
                            if person_id not in self.id_labels.values():
                                person_id = None
                    color = (40, 200, 80) if person_id else (0, 180, 255)
                    self.cv2.rectangle(frame, (x, y), (x+width, y+height), color, 2)
                    if distance is not None:
                        match = self.detector.identity_match
                        if self.detector.embedding_ready and match and match.get('similarity') is not None:
                            label_text = '%s cos=%.3f / %.2f' % (person_id or 'unknown', match['similarity'], match['threshold'])
                        else:
                            label_text = '%s d=%.1f / %.0f' % (person_id or 'unknown', distance, self.config['recognition_threshold'])
                        self.cv2.putText(frame, label_text, (x, max(20, y-8)), self.cv2.FONT_HERSHEY_SIMPLEX, .55, color, 1)
                else:
                    # 多人时不选择“最大的一张脸”进行授权，避免指令主体混淆。
                    self.identity_window.clear()
                    if len(faces) > 1:
                        self.camera['guidance'] = '出现多人，请仅保留当前交互人员在画面内'
                        self.controller.invalidate_identity('画面中出现多人')
                if time.time() - self.last_face_seen > 1.5:
                    self.controller.invalidate_identity('当前人员已离开相机画面')
                if self.enrollment and time.time() >= self.enrollment['deadline']:
                    en = self.enrollment
                    self.enrollment = None
                    self.retrain()
                    self.log(dict(kind='enrollment_timeout', person_id=en['person_id'], count=en['count'], time=time.time()))
                if not self.enrollment and len(faces) == 1 and self.model is not None and distance is not None:
                    stable_key = person_id or 'unknown'
                    confirmed, votes = self.identity_window.update(stable_key, time.time())
                    self.camera['last_identity'] = dict(person_id=person_id, distance=float(distance),
                                                        stable_frames=votes, vote_required=self.identity_window.required,
                                                        vote_window=self.identity_window.size, confirmed=confirmed is not None)
                    if self.detector.embedding_ready:
                        self.camera['last_identity'].update(self.detector.identity_match or {})
                    active = self.controller.snapshot()['person']
                    if active and person_id and person_id != active['id']:
                        self.controller.invalidate_identity('交互人员发生变化')
                    if self.access.observe(person_id, True, confirmed is not None):
                        self.log(dict(kind='access_denied', reason='不是授权人员', time=time.time()))
                        if self.mapping:
                            self.speak_async('不是授权人员')
                    if confirmed is not None and self.mapping is None:
                        # The controller applies its own cooldown. Repeated calls allow recovery
                        # after an interaction timeout while the same person remains in view.
                        self.controller.identify(person_id)
                    if not person_id:
                        self.camera['guidance'] = '已检测到人脸，但未匹配；请保持正脸，必要时补录当前光照和距离的样本'
                else:
                    self.access.observe(None, False, False)
                    self.identity_window.clear()
                    self.camera['last_identity'] = None
                    if len(faces) == 1 and not self.enrollment:
                        self.controller.invalidate_identity('人脸画面质量不足，需要重新确认')
                self.camera['enrollment'] = dict(self.enrollment) if self.enrollment else None
                self.camera['processing_ms'] = round((time.time() - started) * 1000, 1)
                self.recognition_history.append(dict(time=time.time(), faces=len(faces), person_id=person_id,
                                                     distance=float(distance) if distance is not None else None,
                                                     match=self.detector.identity_match,
                                                     quality=self.camera['quality'], enrolling=bool(self.enrollment)))
                success, jpeg = self.cv2.imencode('.jpg', frame, [int(self.cv2.IMWRITE_JPEG_QUALITY), 75])
                if success:
                    self.frame_jpeg = jpeg.tostring()
                if self.runtime:
                    try:
                        self.runtime.publish_frame(frame)
                    except Exception as exc:
                        self.ros_error = as_text(exc)
            except Exception as exc:
                self.camera['error'] = as_text(exc)
            time.sleep(0.15)
        cap.release()

    def control_loop(self):
        previous = None
        while not self.stopping.is_set():
            try:
                self.controller.tick()
                reply = self.controller.snapshot()['reply']
                if reply != previous:
                    previous = reply
                    if self.args.auto_speech:
                        self.speak_async(reply)
            except Exception as exc:
                self.log(dict(kind='control_error', reason=as_text(exc), time=time.time()))
            time.sleep(0.1)

    def status(self):
        with self.lock:
            logs, voice = list(self.logs[-20:]), dict(self.voice)
        # controller.event() 会持控制器锁再写日志；这里不能反向嵌套这两把锁。
        return dict(controller=self.controller.snapshot(), camera=dict(self.camera),
                    voice=voice, people=self.config['people'], places=self.config['places'],
                    health=self.runtime.health() if self.runtime else {'ros_error': self.ros_error},
                    camera_topic=self.config['camera_topic'], logs=logs,
                    model_ready=self.model is not None, measurements={'face_accuracy': None, 'obstacle_accuracy': None},
                    pending=self.config['requirements_pending'],
                    mapping=self.mapping.snapshot() if self.mapping else None, offline_preview=False)

    def map_metadata(self):
        if not self.runtime or self.runtime.map_message is None:
            return dict(ready=False)
        import math
        msg = self.runtime.map_message
        q = msg.info.origin.orientation
        angle = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
        return dict(ready=True, map_id=self.runtime.map_id,
                    width=msg.info.width, height=msg.info.height, resolution=msg.info.resolution,
                    origin=[msg.info.origin.position.x, msg.info.origin.position.y, angle])

    def maps(self):
        return dict(items=map_catalog(os.path.join(os.path.dirname(self.data), 'maps')),
                    selected=self.selected_map, active=self.map_metadata())

    def selected_goal(self, data):
        meta = self.map_metadata()
        if not meta['ready'] or data.get('map_id') != meta['map_id']:
            raise ValueError('地图已变化或尚未加载，请重新选点')
        if self.mapping:
            raise ValueError('建图期间不能发送导航目标')
        pose = pixel_goal(meta, data.get('u'), data.get('v'), data.get('yaw'))
        msg = self.runtime.map_message
        row, col = meta['height']-1-int(data['v']), int(data['u'])
        if msg.data[row*meta['width']+col] != 0:
            raise ValueError('请选择已观测的白色空地')
        return dict(id='clicked_goal', name='地图选点', pose=pose, map_id=meta['map_id'])

    def mapping_image(self):
        import numpy as np
        if not self.runtime or self.runtime.map_message is None:
            return None
        msg = self.runtime.map_message
        cells = np.asarray(msg.data, dtype=np.int16).reshape(msg.info.height, msg.info.width)
        gray = np.full(cells.shape, 205, dtype=np.uint8)
        gray[cells == 0], gray[cells > 0] = 255, 0
        canvas = self.cv2.cvtColor(np.flipud(gray).copy(), self.cv2.COLOR_GRAY2BGR)
        pose = self.runtime.position()
        if pose:
            import math
            import tf
            origin = msg.info.origin
            q = origin.orientation
            angle = tf.transformations.euler_from_quaternion((q.x, q.y, q.z, q.w))[2]
            dx, dy = pose[0]-origin.position.x, pose[1]-origin.position.y
            px = int((dx*math.cos(angle)+dy*math.sin(angle))/msg.info.resolution)
            py = msg.info.height-1-int((-dx*math.sin(angle)+dy*math.cos(angle))/msg.info.resolution)
            self.cv2.circle(canvas, (px, py), 4, (40, 100, 230), -1)
            end = (int(px+12*math.cos(pose[2]-angle)), int(py-12*math.sin(pose[2]-angle)))
            self.cv2.line(canvas, (px, py), end, (40, 100, 230), 2)
        ok, data = self.cv2.imencode('.png', canvas)
        return data.tostring() if ok else None

    def save_mapping_progress(self):
        if not self.mapping or not self.runtime.map_message:
            raise ValueError('实际建图尚未就绪')
        with self.mapping.lock:
            self.mapping.policy.stop(halt=True)
            self.mapping.publisher.publish(self.mapping.Twist())
        directory = os.path.expanduser('~/bobac_practicum_run/maps')
        if not os.path.isdir(directory):
            os.makedirs(directory, 0o700)
        prefix = directory + '/classroom_draft_' + time.strftime('%Y%m%d_%H%M%S')
        process = subprocess.Popen(['timeout', '8', 'rosrun', 'map_server', 'map_saver', '-f', prefix, 'map:=/map'],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = process.communicate()[0]
        if process.returncode:
            raise ValueError('地图保存失败，请检查实际建图节点')
        self.log(dict(kind='mapping_progress_saved', prefix=prefix, complete=False, time=time.time()))
        return dict(saved=prefix, complete=False)

    def face_diagnostics(self):
        # Numeric diagnostics only; no extra face images are retained by this endpoint.
        rows = list(self.recognition_history)
        return dict(detector=self.detector.name, threshold=self.config['recognition_threshold'],
                    samples=dict(self.camera['samples']), observations=rows,
                    note='连续帧仅用于排查检测与匹配问题，不能作为独立准确率验收样本')

    def service(self, name, request):
        if self.runtime is None:
            raise ValueError('ROS 服务连接尚未就绪')
        args = ['timeout', '15', 'rosservice', 'call', name, json.dumps(request, ensure_ascii=False)]
        args = [a.encode('utf-8') if isinstance(a, type(u'')) else a for a in args]
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, error = process.communicate()
        if process.returncode:
            raise ValueError('服务调用失败或超时：' + name)
        return parse_ros_response(out.decode('utf-8'))

    def speak(self, text):
        result = self.service('/tts', {'text': text})
        returned = result.get('voice_file', '')
        path = os.path.realpath(returned if os.path.isabs(returned) else os.path.expanduser('~/.ros/') + returned)
        if not path.startswith(os.path.expanduser('~') + '/') or not os.path.isfile(path):
            raise ValueError('语音合成没有返回可读取的本机音频')
        wav = wave.open(path, 'rb')
        try:
            if wav.getnframes() == 0:
                raise ValueError('语音合成音频为空')
        finally:
            wav.close()
        latest = self.data + '/audio/reply.wav'
        shutil.copyfile(path, latest + '.tmp')
        os.rename(latest + '.tmp', latest)
        with self.lock:
            self.voice['audio_sequence'] += 1
        if self.config.get('audio_output', 'pc') == 'pc':
            self.voice['tts'] = '已生成语音，等待电脑播放器播放'
            return
        code = subprocess.call(['timeout', '20', 'aplay', '-D', 'plughw:CARD=PCH,DEV=0', path],
                               stdout=open(os.devnull, 'w'), stderr=subprocess.STDOUT)
        if code:
            raise ValueError('音频播放失败')
        self.voice['tts'] = '合成与播放调用成功，实际听感待确认'

    def speak_async(self, text):
        def work():
            with self.lock:
                if self.voice['busy']:
                    return
                self.voice['busy'] = True
            try:
                self.speak(text)
                self.voice['error'] = ''
            except Exception as exc:
                self.voice.update(error=as_text(exc), tts='未通过')
            finally:
                self.voice['busy'] = False
        self.start_thread(work)

    def _voice_move(self, linear, angular, seconds):
        """语音控制模式的一次短动作；导航进行中拒绝直接发速度。"""
        if self.voice_cmd_pub is None:
            return '底盘尚未就绪，无法执行动作。'
        if self.controller.snapshot()['state'] == 'NAVIGATING':
            return '正在导航，请先取消导航再手动控制。'
        try:
            from geometry_msgs.msg import Twist
        except Exception:
            return '缺少 geometry_msgs，无法执行动作。'

        def run():
            rate = self.runtime.rospy.Rate(10)
            end = time.time() + max(0.1, seconds)
            msg = Twist()
            msg.linear.x = linear
            msg.angular.z = angular
            while time.time() < end and not self.stopping.is_set():
                self.voice_cmd_pub.publish(msg)
                rate.sleep()
            self.voice_cmd_pub.publish(Twist())

        self.start_thread(run)
        return ''

    def voice_handle(self, text):
        """文档 5.1：先唤醒，再按模式处理（闲聊/控制/导航）。"""
        text = as_text(text).strip()
        flow = self.voice_flow
        now = time.time()
        if now - flow.get('last', 0) > 120:
            flow['awake'] = False
        flow['last'] = now

        if not flow['awake']:
            if u'元宝' in text:
                flow['awake'] = True
                return u'我在，请说指令。'
            return u'请先呼唤“元宝元宝”唤醒我。'

        if flow.get('choosing'):
            flow['choosing'] = False
            for key, name in ((u'闲聊', u'闲聊'), (u'控制', u'控制'), (u'导航', u'导航')):
                if key in text:
                    flow['mode'] = {'闲聊': 'chat', '控制': 'control', '导航': 'nav'}[name]
                    return u'已切换到%s模式。' % name
            return u'没有听清模式，请说闲聊模式、控制模式或导航模式。'

        if u'切换模式' in text or u'模式切换' in text:
            flow['choosing'] = True
            return u'请选择想要切换的模式：闲聊、控制或导航。'

        mode = flow.get('mode', 'chat')
        if mode == 'control':
            if any(w in text for w in [u'停止', u'停下', u'停']):
                err = self._voice_move(0, 0, 0.1)
                return err or u'已停车。'
            table = ((u'前进', 0.12, 0.0, 1.5), (u'后退', -0.10, 0.0, 1.5),
                     (u'左转', 0.0, 0.5, 1.2), (u'右转', 0.0, -0.5, 1.2))
            for word, linear, angular, seconds in table:
                if word in text:
                    err = self._voice_move(linear, angular, seconds)
                    return err or (u'执行%s。' % word)
            return u'控制模式请说前进、后退、左转、右转或停止。'

        if mode == 'nav':
            if any(w in text for w in [u'取消', u'停止']):
                self.controller.dispatch(u'停止')
                return u'已取消导航。'
            name = text
            for prefix in (u'我要去', u'我想去', u'带我去', u'去', u'到'):
                if prefix in name:
                    name = name.split(prefix, 1)[1]
                    break
            name = name.strip(u'，。, .！!')
            return self.controller.dispatch(name)

        return self.controller.dispatch(text)

    def listen(self):
        with self.lock:
            if self.voice['busy']:
                raise ValueError('语音正在处理，请稍候')
            self.voice['busy'] = True
        def work():
            try:
                path = self.data + '/audio/input_%d.wav' % int(time.time() * 1000)
                code = subprocess.call(['timeout', '8', 'arecord', '-D', 'plughw:CARD=Pro,DEV=0',
                                        '-d', '5', '-f', 'S16_LE', '-r', '16000', '-c', '1', path],
                                       stdout=open(os.devnull, 'w'), stderr=subprocess.STDOUT)
                if code:
                    raise ValueError('麦克风录音失败')
                result = self.service('/aiui', {'audio_file': path})
                text = as_text(result.get('iat_str', '')).strip()
                if not text:
                    raise ValueError('语音识别没有返回文字，请检查服务配置和网络')
                self.voice.update(last_text=text, asr='识别调用成功，准确率待独立测试', error='')
                reply = self.voice_handle(text)
                self.speak(reply)
            except Exception as exc:
                self.voice['error'] = as_text(exc)
                self.log(dict(kind='voice_failed', reason=as_text(exc), time=time.time()))
            finally:
                self.voice['busy'] = False
        self.start_thread(work)


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def respond(self, code, body, content_type='application/json; charset=utf-8'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        elif isinstance(body, type(u'')):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        if getattr(self, 'new_cookie', None):
            self.send_header('Set-Cookie', 'bobac_session='+self.new_cookie+'; HttpOnly; SameSite=Strict; Path=/')
            self.new_cookie = None
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        host = self.headers.get('Host', '')
        port = self.server.server_port
        return host in ('127.0.0.1:%d' % port, 'localhost:%d' % port)

    def token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            return cookie['bobac_session'].value if 'bobac_session' in cookie else ''
        except Exception:
            return ''

    def do_GET(self):
        app = self.server.app
        if not self.valid_host():
            return self.respond(403, {'error': '仅允许本机或 SSH 隧道访问'})
        path = self.path.split('?')[0]
        if path == '/api/access':
            return self.respond(200, dict(app.access.status(self.token()),
                people=app.config['people'], bootstrap=not any(app.camera['samples'].values()),
                camera_ready=app.camera['ready'], offline_preview=getattr(app.args, 'offline_preview', False)))
        if path.startswith('/api/') and path not in ('/api/access',):
            if not app.access.status(self.token())['authenticated']:
                return self.respond(401, dict(error='请先完成人脸身份验证'))
        if path == '/api/maps':
            return self.respond(200, app.maps())
        if path == '/api/map-metadata':
            return self.respond(200, app.map_metadata())
        if path == '/api/status':
            app.last_session_activity = time.time()
            app.ensure_session_person(app.access.require(self.token()))
            return self.respond(200, app.status())
        if path == '/api/face-diagnostics':
            return self.respond(200, app.face_diagnostics())
        if path == '/api/mapping/status':
            return self.respond(200, app.mapping.snapshot() if app.mapping else dict(enabled=False))
        if path == '/mapping-map.png':
            data = app.mapping_image()
            return self.respond(200, data, 'image/png') if data else self.respond(503, dict(error='等待实际地图'))
        if path == '/camera.jpg':
            return self.respond(200, app.frame_jpeg, 'image/jpeg') if app.frame_jpeg else self.respond(503, {'error': '相机未就绪'})
        if path == '/reply.wav':
            audio = app.data + '/audio/reply.wav'
            if not os.path.isfile(audio):
                return self.respond(404, {'error': '尚未生成回复音频'})
            with open(audio, 'rb') as stream:
                return self.respond(200, stream.read(), 'audio/wav')
        files = {'/': ('login.html', 'text/html; charset=utf-8'),
                 '/console': ('index.html', 'text/html; charset=utf-8'),
                 '/login.js': ('login.js', 'application/javascript; charset=utf-8'),
                 '/modules.js': ('modules.js', 'application/javascript; charset=utf-8'),
                 '/app.js': ('app.js', 'application/javascript; charset=utf-8'),
                 '/style.css': ('style.css', 'text/css; charset=utf-8'),
                 '/mapping': ('mapping.html', 'text/html; charset=utf-8'),
                 '/mapping.js': ('mapping.js', 'application/javascript; charset=utf-8')}
        if path == '/console' or path == '/mapping':
            # 刷脸一次后，本次会话内可自由进出配置/建图页
            if not app.access.status(self.token())['authenticated']:
                self.send_response(302)
                self.send_header('Location', '/?next=' + path)
                self.end_headers()
                return
        if path in files:
            filename, kind = files[path]
            with open(os.path.join(ROOT, 'web', filename), 'rb') as stream:
                return self.respond(200, stream.read(), kind)
        self.respond(404, {'error': '未找到'})

    def do_POST(self):
        app = self.server.app
        try:
            if not self.valid_host() or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.respond(403, {'error': '请求来源或格式不允许'})
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + self.headers.get('Host'):
                return self.respond(403, {'error': '请求来源不允许'})
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > 8192:
                raise ValueError('请求长度无效')
            data = json.loads(self.rfile.read(length).decode('utf-8'))
            if not isinstance(data, dict):
                raise ValueError('请求必须是对象')
            if self.path == '/api/access/begin':
                app.last_session_activity = 0  # 开始验证时恢复人脸检测
                self.new_cookie = app.access.begin()
                return self.respond(200, dict(ok=True))
            if self.path == '/api/access/logout':
                app.access.logout(self.token())
                app.last_session_activity = 0  # 退出后恢复人脸检测
                return self.respond(200, dict(ok=True))
            if self.path == '/api/access/preview' and getattr(app.args, 'offline_preview', False):
                app.preview_identity(data.get('person_id'), self.token())
                return self.respond(200, dict(ok=True, simulated=True))
            if self.path == '/api/access/bootstrap':
                if any(app.camera['samples'].values()) or app.enrollment:
                    raise ValueError('初始化仅在没有任何人脸样本时可用')
                if app.access.status(self.token())['expired'] or data.get('consent') is not True:
                    raise ValueError('请先开始验证并确认本人同意')
                app.enroll(data.get('person_id'))
                return self.respond(200, dict(ok=True))
            # Emergency stop remains available even after a login expires.
            person = None
            if self.path != '/api/stop':
                if not app.access.status(self.token())['authenticated']:
                    return self.respond(401, dict(error='请先完成人脸身份验证'))
                person = app.access.require(self.token())
                app.last_session_activity = time.time()
                app.ensure_session_person(person)
            if self.path == '/api/maps/select':
                selected = next((m for m in app.maps()['items'] if m['id'] == data.get('id')), None)
                if not selected:
                    raise ValueError('地图不存在')
                app.selected_map = selected
                app.log(dict(kind='map_selection_pending', map=selected['id'], time=time.time()))
                return self.respond(200, dict(ok=True, applied=False,
                    message='地图已选为待加载项；当前不会切换运行中的ROS地图，需在机器人联调时完成模式启动'))
            if self.path == '/api/navigation/goal':
                place = app.selected_goal(data)
                app.controller.identify(person['id'])
                app.controller.tick()
                app.controller.navigate(place)
                return self.respond(200, dict(ok=True, simulated=app.controller.nav.simulated))
            if self.path == '/api/mode':
                target = data.get('mode')
                if target not in ('nav', 'mapping'):
                    raise ValueError('只支持 nav 或 mapping')
                current = 'mapping' if app.mapping else ('nav' if app.args.allow_motion else 'static')
                if target == current:
                    return self.respond(200, dict(ok=True, mode=current, wait_seconds=0,
                                                  message='已经是该模式'))
                subprocess.Popen(['bash', os.path.expanduser('~/bobac_mode.sh'), target],
                                 stdout=open(os.devnull, 'w'), stderr=subprocess.STDOUT,
                                 preexec_fn=os.setsid)
                app.log(dict(kind='mode_switch', target=target, time=time.time()))
                return self.respond(200, dict(ok=True, mode=target, wait_seconds=45,
                                              message='正在切换模式'))
            if self.path == '/api/mapping/control':
                if not app.mapping:
                    raise ValueError('人工建图遥控未启用')
                app.mapping.request(data)
                return self.respond(200, dict(ok=True))
            if self.path == '/api/mapping/save':
                return self.respond(200, app.save_mapping_progress())
            if app.mapping and self.path not in ('/api/stop', '/api/speak'):
                raise ValueError('当前为人工建图，请使用建图控制页面')
            if self.path == '/api/command':
                text = data.get('text', '')
                if not isinstance(text, (type(u''), str)) or len(text) > 200:
                    raise ValueError('指令应为不超过 200 字的文字')
                app.controller.dispatch(text)
            elif self.path == '/api/stop':
                if app.mapping:
                    app.mapping.request(dict(session=app.mapping.session, action='stop', halt=True))
                app.controller.dispatch('停止')
            elif self.path == '/api/patrol':
                app.controller.start_patrol()
            elif self.path == '/api/demo-identity':
                if not app.controller.nav.simulated:
                    raise ValueError('仅静态演示允许模拟身份')
                person_id = data.get('person_id')
                if person_id not in [p['id'] for p in app.config['people']] + ['unknown']:
                    raise ValueError('未知人员编号')
                app.controller.identify(person_id, simulated_input=True)
            elif self.path == '/api/enroll':
                if data.get('consent') is not True:
                    raise ValueError('请确认本人同意且画面中只有该人员')
                app.enroll(data.get('person_id'))
            elif self.path == '/api/listen':
                app.listen()
            elif self.path == '/api/speak':
                app.speak_async(app.controller.snapshot()['reply'])
            elif self.path == '/api/save-place':
                if not app.runtime or not app.runtime.map_id:
                    raise ValueError('没有实际地图，不能记录目标点')
                pose = app.runtime.position()
                if pose is None:
                    raise ValueError('没有新鲜有效的地图定位')
                with app.controller.lock:
                    places = [p for p in app.config['places'] if p['id'] == data.get('place_id')]
                    if len(places) != 1:
                        raise ValueError('未知地点')
                    places[0].update(pose=dict(x=pose[0], y=pose[1], yaw=pose[2]), map_id=app.runtime.map_id)
                    save_json(app.args.config, app.config)
            else:
                return self.respond(404, {'error': '未找到'})
            self.respond(200, {'ok': True})
        except (ValueError, KeyError, TypeError) as exc:
            self.respond(400, {'error': as_text(exc)})
        except Exception as exc:
            app.log(dict(kind='request_failed', reason=as_text(exc), time=time.time()))
            self.respond(500, {'error': '操作未完成，请检查状态与日志'})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=os.path.expanduser('~/bobac_practicum_run/project.json'))
    parser.add_argument('--data', default='~/bobac_practicum_run/data')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--ros', action='store_true')
    parser.add_argument('--allow-motion', action='store_true')
    parser.add_argument('--auto-speech', action='store_true')
    parser.add_argument('--mapping-teleop', action='store_true')
    parser.add_argument('--mapping-keyboard', action='store_true')
    parser.add_argument('--mapping-test-speed', type=float, default=.05)
    arguments = sys.argv[1:]
    if '--ros' in arguments:
        import rospy
        arguments = rospy.myargv()[1:]
    args = parser.parse_args(arguments)
    if args.mapping_keyboard and not args.mapping_teleop:
        parser.error("--mapping-keyboard requires --mapping-teleop")
    if not os.path.isfile(args.config):
        parent = os.path.dirname(os.path.abspath(args.config))
        if not os.path.isdir(parent):
            os.makedirs(parent, 0o700)
        shutil.copyfile(ROOT + '/config/project.json', args.config)
    app = Application(args)
    server = Server(('127.0.0.1', args.port), Handler)
    server.app = app
    def stop_signal(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, stop_signal)
    print('Practicum HTTP ready on loopback port %d; simulated=%s' % (args.port, app.controller.nav.simulated))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if app.mapping:
            app.mapping.close()
        app.controller.nav.cancel()
        app.stopping.set()
        app.detector.close()
        server.server_close()


if __name__ == '__main__':
    main()
