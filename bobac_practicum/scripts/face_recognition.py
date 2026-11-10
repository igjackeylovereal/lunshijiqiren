# -*- coding: utf-8 -*-
"""CPU face detection and time-bounded identity voting (Python 2/3)."""
from __future__ import unicode_literals
import os
import json
import struct
import select
import subprocess
from collections import deque, Counter


class IdentityWindow(object):
    def __init__(self, required=4, size=6, max_age=3.0):
        if required < 2 or required > size:
            raise ValueError('invalid identity voting window')
        self.required, self.size, self.max_age = required, size, max_age
        self.items = deque(maxlen=size)

    def clear(self):
        self.items.clear()

    def update(self, candidate, now):
        while self.items and now - self.items[0][0] > self.max_age:
            self.items.popleft()
        self.items.append((now, candidate))
        counts = Counter(key for _, key in self.items)
        votes = counts[candidate]
        # A stale majority must never authorize a different current face.
        return candidate if votes >= self.required else None, votes


class FaceDetector(object):
    def __init__(self, cv2, assets, isolated=True, config_path=None, data_path=None):
        self.cv2, self.net, self.error, self.worker = cv2, None, '', None
        self.worker_version = ''
        self.embedding_ready, self.embedding_error, self.identity_match = False, '', None
        self.haar = cv2.CascadeClassifier(os.path.join(assets, 'haarcascade_frontalface_default.xml'))
        try:
            deps = os.path.expanduser('~/bobac_practicum_run/vision_deps')
            if isolated and os.path.isfile(os.path.join(deps, 'cv2', '__init__.py')):
                env = dict(os.environ)
                env.pop('PYTHONPATH', None)
                env.pop('LD_LIBRARY_PATH', None)
                log = open(os.path.expanduser('~/bobac_practicum_run/vision_worker.log'), 'ab')
                command = ['/usr/bin/python2.7', os.path.join(os.path.dirname(__file__), 'vision_worker.py'), '--deps', deps]
                if config_path:
                    command.extend(['--config', config_path])
                if data_path:
                    command.extend(['--data', data_path])
                self.worker = subprocess.Popen(command,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, env=env, bufsize=0)
                log.close()
                result = self.worker_response(45)
                if not result.get('ready'):
                    raise ValueError('视觉子进程启动失败')
                self.worker_version = result['opencv']
                self.embedding_ready = result.get('embedding_ready', False)
                self.embedding_error = result.get('embedding_error', '')
            elif tuple(int(v) for v in cv2.__version__.split('.')[:2]) >= (3, 4):
                self.net = cv2.dnn.readNetFromCaffe(
                    os.path.join(assets, 'deploy.prototxt'),
                    os.path.join(assets, 'res10_300x300_ssd_iter_140000.caffemodel'))
            else:
                self.error = '旧 ROS OpenCV 使用 CLAHE 后备检测；独立视觉依赖尚未就绪'
        except Exception as exc:
            self.error = str(exc)
            self.close()
        if self.net is None and self.haar.empty():
            raise ValueError('人脸检测模型未加载')

    @property
    def name(self):
        if self.worker is not None:
            return 'OpenCV SSD ResNet-10 (isolated %s)' % self.worker_version
        return 'OpenCV SSD ResNet-10' if self.net is not None else 'Haar + CLAHE (fallback)'

    def worker_response(self, timeout):
        if not select.select([self.worker.stdout], [], [], timeout)[0]:
            raise ValueError('视觉子进程超时')
        line = self.worker.stdout.readline()
        if not line:
            raise ValueError('视觉子进程退出，请检查 vision_worker.log')
        result = json.loads(line)
        if result.get('error'):
            raise ValueError(result['error'])
        return result

    def close(self):
        if self.worker is not None:
            if self.worker.poll() is None:
                self.worker.terminate()
            self.worker.wait()
            self.worker = None
        self.embedding_ready, self.identity_match = False, None

    def reload_gallery(self):
        if self.worker is not None:
            self.worker.stdin.write(struct.pack('<I', 0))
            self.worker.stdin.flush()
            self.embedding_ready = self.worker_response(45).get('embedding_ready', False)

    def detect(self, frame):
        cv2 = self.cv2
        self.identity_match = None
        if self.worker is not None:
            try:
                ok, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                if not ok:
                    raise ValueError('无法编码视觉图像')
                data = jpeg.tostring()
                self.worker.stdin.write(struct.pack('<I', len(data)) + data)
                self.worker.stdin.flush()
                result = self.worker_response(5)
                self.identity_match = result.get('match')
                return [tuple(box) for box in result['boxes']]
            except Exception as exc:
                self.error = str(exc)
                self.close()
        if self.net is None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.createCLAHE(2.0, (8, 8)).apply(gray)
            return [tuple(int(v) for v in box) for box in self.haar.detectMultiScale(
                gray, scaleFactor=1.08, minNeighbors=5, minSize=(60, 60))]
        height, width = frame.shape[:2]
        blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)), 1.0,
                                     (300, 300), (104.0, 177.0, 123.0), False, False)
        self.net.setInput(blob)
        detections = self.net.forward()
        boxes = []
        for i in range(detections.shape[2]):
            row = detections[0, 0, i]
            if float(row[2]) < 0.65:
                continue
            left, top = max(0, int(row[3] * width)), max(0, int(row[4] * height))
            right, bottom = min(width, int(row[5] * width)), min(height, int(row[6] * height))
            if right - left >= 40 and bottom - top >= 40:
                boxes.append((left, top, right - left, bottom - top))
        return boxes


def face_sample(cv2, gray, box):
    x, y, width, height = box
    raw = gray[y:y+height, x:x+width]
    resized = cv2.resize(raw, (128, 128))
    sharpness, light = float(cv2.Laplacian(resized, cv2.CV_64F).var()), float(raw.mean())
    clipped = x <= 2 or y <= 2 or x + width >= gray.shape[1] - 2 or y + height >= gray.shape[0] - 2
    reason = ''
    if min(width, height) < 90:
        reason = '人脸偏小，请靠近一些（约 0.6～1 米）'
    elif clipped:
        reason = '人脸靠近画面边缘，请后退或调整高度，露出完整正脸'
    elif light < 45:
        reason = '脸部过暗，请面向光源，避免背光'
    elif light > 215:
        reason = '脸部过亮，请避免强光直射'
    elif sharpness < 40:
        reason = '画面模糊，请稍停并正对相机'
    metrics = dict(width=width, height=height, brightness=round(light, 1),
                   sharpness=round(sharpness, 1), clipped=clipped, accepted=not bool(reason))
    # Stored legacy samples use this same 128x128 histogram-equalized format.
    return cv2.equalizeHist(resized), metrics, reason
