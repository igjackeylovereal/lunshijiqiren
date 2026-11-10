# -*- coding: utf-8 -*-
import json
import math
import os
import sys
import threading
import unittest
try:
    from urllib.request import Request, build_opener, HTTPCookieProcessor
    from urllib.error import HTTPError
except ImportError:
    from urllib2 import Request, build_opener, HTTPCookieProcessor, HTTPError
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__))+'/scripts')
from access_gate import AccessGate
from map_tools import pixel_goal
from offline_preview import Preview
from app import Handler, Server
from mapping_control import KeyboardLease


class GateTests(unittest.TestCase):
    def test_default_authorized_session_has_no_time_limit_and_logout_revokes(self):
        now = [100.]
        gate = AccessGate([dict(id='p001', authorized=True)], lambda: now[0])
        token = gate.begin()
        gate.observe('p001', True, True)
        now[0] += 3
        gate.observe('p001', True, True)
        now[0] += 60*60*24*30
        self.assertEqual(gate.require(token)['id'], 'p001')
        self.assertIsNone(gate.status(token)['expires'])
        gate.begin()  # Cleaning up old attempts must preserve logged-in sessions.
        self.assertTrue(gate.status(token)['authenticated'])
        gate.logout(token)
        with self.assertRaises(ValueError): gate.require(token)

    def test_unverified_attempt_still_times_out(self):
        now = [100.]
        gate = AccessGate([dict(id='p001', authorized=True)], lambda: now[0])
        token = gate.begin()
        now[0] += 61
        gate.observe('p001', True, True)
        self.assertTrue(gate.status(token)['expired'])

    def test_stable_identity_required_and_session_expires(self):
        now = [100.]
        gate = AccessGate([dict(id='p001', authorized=True)], lambda: now[0], ttl=10)
        token = gate.begin()
        gate.observe('p001', True, True)
        self.assertFalse(gate.status(token)['authenticated'])
        now[0] += 2.1
        gate.observe('p001', True, True)
        self.assertTrue(gate.status(token)['authenticated'])
        gate.observe(None, False, False)
        self.assertTrue(gate.status(token)['authenticated'])
        now[0] += 11
        with self.assertRaises(ValueError): gate.require(token)

    def test_unknown_and_multiple_faces_never_grant_access(self):
        now = [100.]
        gate = AccessGate([dict(id='p001', authorized=True)], lambda: now[0])
        token = gate.begin()
        gate.observe(None, True, True)
        now[0] += 3
        self.assertTrue(gate.observe(None, True, True))
        self.assertTrue(gate.status(token)['denied'])
        gate.observe('p001', True, True)
        now[0] += 1
        gate.observe('p001', False, False)
        now[0] += 3
        gate.observe('p001', True, True)
        self.assertFalse(gate.status(token)['authenticated'])

    def test_rotated_map_and_image_flip(self):
        meta = dict(width=10, height=20, resolution=1, origin=[10, 20, math.pi/2])
        pose = pixel_goal(meta, 0, 0, 0)
        self.assertAlmostEqual(pose['x'], -9.5)
        self.assertAlmostEqual(pose['y'], 20.5)
        for u, v, yaw in [(10, 0, 0), (0, -1, 0), (True, 0, 0), (0, 0, float('nan'))]:
            with self.assertRaises(ValueError): pixel_goal(meta, u, v, yaw)

    def test_direction_coverage_and_lost_heartbeat(self):
        policy = KeyboardLease()
        health = dict(scan_fresh=True, odom_fresh=True, map_ready=True, base_ready=True,
                      collision_clear=True, pose=(0, 0), direction_clearance=dict(left=.6))
        with self.assertRaises(ValueError): policy.renew_direction(u'back_token', 'backward', 1, health)
        policy.renew_direction(u'left_token', 'left', 1, health)
        self.assertEqual(policy.tick(1.1, health), (0, .18))
        self.assertEqual(policy.tick(1.3, health), (0, 0))


class ConsoleHttpTests(unittest.TestCase):
    def setUp(self):
        self.app = Preview()
        self.server = Server(('127.0.0.1', 0), Handler)
        self.server.app = self.app
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        self.url = 'http://127.0.0.1:%d' % self.server.server_port
        self.client = build_opener(HTTPCookieProcessor())

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(1)

    def call(self, path, body=None):
        data = json.dumps(body).encode('utf-8') if body is not None else None
        request = Request(self.url+path, data=data, headers={'Content-Type':'application/json'})
        return json.loads(self.client.open(request).read().decode('utf-8'))

    def login(self):
        self.call('/api/access/begin', {})
        self.call('/api/access/preview', dict(person_id='p001'))

    def test_protected_apis_and_stop_without_login(self):
        for path, body in [('/api/status', None), ('/api/enroll', {}), ('/api/navigation/goal', {})]:
            with self.assertRaises(HTTPError) as error: self.call(path, body)
            self.assertEqual(error.exception.code, 401)
        self.call('/api/stop', {})

    def test_login_map_goal_and_logout(self):
        self.login()
        self.assertTrue(self.call('/api/access')['authenticated'])
        self.assertTrue(self.call('/api/maps')['active']['ready'])
        goal = dict(map_id='OFFLINE_DEMO_ONLY', u=40, v=40, yaw=0)
        self.assertTrue(self.call('/api/navigation/goal', goal)['simulated'])
        self.assertEqual(self.app.controller.state, 'NAVIGATING')
        self.call('/api/stop', {})
        self.call('/api/access/logout', {})
        with self.assertRaises(HTTPError): self.call('/api/maps')

    def test_obstacles_stale_map_and_preview_endpoint_disabled_in_real_mode(self):
        self.login()
        for goal in [dict(map_id='old', u=40, v=40, yaw=0),
                     dict(map_id='OFFLINE_DEMO_ONLY', u=90, v=70, yaw=0)]:
            with self.assertRaises(HTTPError): self.call('/api/navigation/goal', goal)
        self.app.args.offline_preview = False
        with self.assertRaises(HTTPError): self.call('/api/access/preview', dict(person_id='p001'))


if __name__ == '__main__': unittest.main()
