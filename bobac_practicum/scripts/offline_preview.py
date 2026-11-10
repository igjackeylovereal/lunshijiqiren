# -*- coding: utf-8 -*-
"""Isolated UI demo: no ROS imports, cameras, microphone or motion publishers."""
from __future__ import unicode_literals, print_function
import argparse
import io
import json
import os
import struct
import threading
import time
import zlib
from access_gate import AccessGate
from app import Application, Handler, Server
from core import Controller, SimNavigation
from map_tools import pixel_goal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Preview(Application):
    def __init__(self):
        with io.open(ROOT+'/config/project.json', encoding='utf-8') as stream:
            self.config = json.load(stream)
        self.args = argparse.Namespace(offline_preview=True)
        self.lock = threading.RLock()
        self.logs, self.selected_map = [], None
        self.access = AccessGate(self.config['people'])
        self.controller = Controller(self.config, SimNavigation(), self.log)
        self.runtime = self.mapping = self.enrollment = None
        self.frame_jpeg = None
        self.data = ROOT+'/../tmp/offline_preview_data'
        self.camera = dict(ready=False, samples=dict((p['id'], 0) for p in self.config['people']),
                           face_count=0, last_identity=None, enrollment=None, error='离线演示没有相机')
        self.voice = dict(busy=False, error='', last_text='', output='pc', audio_sequence=0)
        self.meta = dict(ready=True, map_id='OFFLINE_DEMO_ONLY', width=240, height=160,
                         resolution=.05, origin=[0, 0, 0])
        self.controller.reply = '离线演示已就绪，导航为模拟执行。'

    def log(self, event):
        with self.lock:
            self.logs.append(event)
            self.logs = self.logs[-100:]

    def preview_identity(self, person_id, token):
        if self.access.status(token)['expired']:
            raise ValueError('请先点击开始验证')
        with self.access.lock:
            session = self.access.sessions[token]
            session['person'] = self.access.people.get(person_id)
            session['denied'] = not bool(session['person'])
            session['expires'] = None if session['person'] else time.time()+60
        self.log(dict(kind='simulated_login', person_id=person_id, simulated_input=True, time=time.time()))
        if session['person']:
            self.controller.identify(person_id, simulated_input=True)
            self.controller.tick()

    def status(self):
        self.controller.tick()
        return dict(controller=self.controller.snapshot(), camera=self.camera, voice=self.voice,
                    people=self.config['people'], places=self.config['places'], health={},
                    logs=self.logs[-20:], pending=['离线演示不能验证实际识别率与导航效果'],
                    model_ready=False, mapping=None, offline_preview=True)

    def map_metadata(self):
        return dict(self.meta)

    def maps(self):
        return dict(items=[dict(id='离线示意图.yaml', verified=False)],
                    selected=self.selected_map, active=self.map_metadata())

    def selected_goal(self, data):
        if data.get('map_id') != self.meta['map_id']:
            raise ValueError('地图已变化，请重新选点')
        pose = pixel_goal(self.meta, data.get('u'), data.get('v'), data.get('yaw'))
        if self.cell(int(data['u']), int(data['v'])) != 255:
            raise ValueError('请选择白色空地')
        return dict(id='demo_goal', name='离线地图选点', pose=pose, map_id=self.meta['map_id'])

    @staticmethod
    def cell(x, y):
        return 0 if x < 5 or y < 5 or x > 234 or y > 154 or (80 < x < 100 and 40 < y < 120) else 255

    def mapping_image(self):
        w, h = self.meta['width'], self.meta['height']
        raw = b''.join(b'\0'+bytes(bytearray(self.cell(x, y) for x in range(w))) for y in range(h))
        def chunk(kind, body):
            return struct.pack('!I', len(body))+kind+body+struct.pack('!I', zlib.crc32(kind+body) & 0xffffffff)
        return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('!2I5B', w, h, 8, 0, 0, 0, 0))+chunk(b'IDAT', zlib.compress(raw))+chunk(b'IEND', b'')

    def enroll(self, person_id):
        raise ValueError('离线演示不采集人脸；请连接机器人后录入')

    def listen(self):
        raise ValueError('离线演示没有机器人麦克风，请使用文字指令')

    def speak_async(self, text):
        raise ValueError('离线演示未连接机器人语音服务')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    server = Server(('127.0.0.1', args.port), Handler)
    server.app = Preview()
    print('OFFLINE DEMO ONLY: http://127.0.0.1:%d/' % args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
