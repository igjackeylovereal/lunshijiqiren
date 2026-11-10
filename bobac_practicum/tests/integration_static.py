# -*- coding: utf-8 -*-
"""Run manually against the static application. Never run against actual navigation."""
from __future__ import print_function, unicode_literals
import json
import os
import time
try:
    from urllib.request import Request, build_opener, HTTPCookieProcessor
    from urllib.error import HTTPError
except ImportError:
    from urllib2 import Request, build_opener, HTTPCookieProcessor, HTTPError

URL = 'http://127.0.0.1:8765'
client = build_opener(HTTPCookieProcessor())
urlopen = client.open


def status():
    return json.load(urlopen(URL + '/api/status', timeout=5))


def post(path, data=None, expected=200, extra_headers=None):
    headers = {'Content-Type': 'application/json'}
    headers.update(extra_headers or {})
    request = Request(URL + path, json.dumps(data or {}).encode('utf-8'), headers)
    try:
        response = urlopen(request, timeout=5)
        code, body = response.code, json.load(response)
    except HTTPError as exc:
        code, body = exc.code, json.load(exc)
    assert code == expected, (path, code, body)
    return body


def wait_state(target, seconds=5):
    deadline = time.time() + seconds
    while time.time() < deadline:
        value = status()
        if value['controller']['state'] == target:
            return value
        time.sleep(.1)
    raise AssertionError('state did not become ' + target)


def main():
    # A real static deployment also requires a genuine camera login.
    post('/api/access/begin')
    print('请在60秒内由一位已录入授权人员单独正面入镜，完成真实人脸验证。')
    deadline = time.time()+60
    while time.time() < deadline:
        access = json.load(urlopen(URL+'/api/access', timeout=5))
        if access['authenticated']:
            break
        time.sleep(.5)
    else:
        raise AssertionError('未完成真实人脸登录，停止集成测试')
    initial = status()
    assert initial['controller']['simulated'] is True
    assert initial['controller']['motion_enabled'] is False
    results = []
    post('/api/stop')
    post('/api/command', {'text': '去教室'})
    assert status()['controller']['state'] == 'PAUSED'
    results.append('unauthenticated navigation rejected')
    post('/api/enroll', {'person_id': 'p001', 'consent': False}, expected=400)
    results.append('enrollment requires explicit consent')
    post('/api/save-place', {'place_id': 'classroom'}, expected=400)
    results.append('no invented map coordinates')
    post('/api/command', {'text': '停止'}, expected=403, extra_headers={'Origin': 'http://untrusted.invalid'})
    results.append('cross-origin mutation rejected')
    post('/api/demo-identity', {'person_id': 'unknown'})
    assert status()['controller']['person'] is None
    results.append('unknown identity does not authorize')
    post('/api/patrol')
    post('/api/demo-identity', {'person_id': 'p002'})
    wait_state('WAITING_COMMAND')
    post('/api/command', {'text': '带我去教室'})
    wait_state('NAVIGATING')
    wait_state('PATROLLING', 6)
    results.append('simulated patrol-identity-dialogue-navigation-resume flow')
    post('/api/stop')
    post('/api/command', {'text': '你好你好'})
    assert '你好' in status()['controller']['reply']
    results.append('Chinese greeting accepted')
    post('/api/stop')
    audio = urlopen(URL + '/reply.wav', timeout=5).read()
    assert audio[:4] == b'RIFF' and len(audio) > 44
    results.append('PC audio endpoint serves a nonempty WAV')
    image = urlopen(URL + '/camera.jpg', timeout=5).read()
    assert image[:2] == b'\xff\xd8'
    results.append('live color camera JPEG endpoint')
    final = status()
    report = dict(timestamp=time.time(), simulated=True, results=results,
                  motion_enabled=final['controller']['motion_enabled'],
                  face_samples=final['camera']['samples'], model_ready=final['model_ready'],
                  camera_ready=final['camera']['ready'], health=final['health'])
    path = os.path.expanduser('~/bobac_practicum_run/static_integration.json')
    with open(path, 'w') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
