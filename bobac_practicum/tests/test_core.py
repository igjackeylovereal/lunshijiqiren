# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import copy
import io
import json
import os
import sys
import unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT + '/scripts')
from core import Controller, SimNavigation, parse_command, validate_pose


class Clock(object):
    def __init__(self): self.now = 1000
    def __call__(self): return self.now
    def advance(self, value): self.now += value


class CoreTests(unittest.TestCase):
    def setUp(self):
        with io.open(ROOT + '/config/project.json', encoding='utf-8') as stream:
            self.config = json.load(stream)
        self.clock = Clock()
        self.nav = SimNavigation(self.clock)
        self.events = []
        self.c = Controller(self.config, self.nav, self.events.append, self.clock)

    def authorize(self):
        self.c.identify('p001')
        self.c.tick()

    def test_no_navigation_without_identity(self):
        self.c.dispatch('去教室')
        self.assertEqual(self.c.state, 'IDLE')
        self.assertIsNone(self.nav.deadline)

    def test_patrol_identity_command_resume_flow(self):
        self.c.start_patrol()
        self.c.identify('p001')
        self.assertEqual(self.c.state, 'IDENTIFYING')
        self.c.tick()
        self.assertEqual(self.c.state, 'WAITING_COMMAND')
        self.c.dispatch('带我去教室')
        self.assertEqual(self.c.state, 'NAVIGATING')
        self.clock.advance(4)
        self.c.tick()
        self.assertEqual(self.c.state, 'PATROLLING')
        self.assertTrue(all(e['simulated'] for e in self.events))

    def test_cancel_removes_session_and_prevents_resume(self):
        self.c.start_patrol()
        self.authorize()
        self.c.dispatch('停止')
        self.clock.advance(100)
        self.c.tick()
        self.assertEqual(self.c.state, 'PAUSED')
        self.assertIsNone(self.c.person)
        self.assertFalse(self.c.resume_patrol)

    def test_unknown_never_opens_session(self):
        self.c.identify('unknown')
        self.c.tick()
        self.assertIsNone(self.c.person)
        self.assertEqual(self.events[-1]['kind'], 'unauthorized')

    def test_unknown_revokes_existing_authorization(self):
        self.authorize()
        self.c.identify('unknown')
        self.c.dispatch('去教室')
        self.assertIsNone(self.c.person)
        self.assertEqual(self.c.state, 'PAUSED')
        self.assertIsNone(self.nav.deadline)

    def test_multiple_people_revoke_session(self):
        self.authorize()
        self.c.invalidate_identity('multiple faces')
        self.c.dispatch('去教室')
        self.assertEqual(self.c.state, 'PAUSED')

    def test_greeting_is_available_without_navigation_access(self):
        self.assertIn('你好', self.c.dispatch('你好你好'))
        self.assertIsNone(self.nav.deadline)

    def test_duplicate_identity_does_not_restart_wait(self):
        self.authorize()
        deadline = self.c.deadline
        self.clock.advance(3)
        self.c.identify('p001')
        self.assertEqual(self.c.deadline, deadline)

    def test_wait_timeout_revokes_identity(self):
        self.authorize()
        self.clock.advance(31)
        self.c.tick()
        self.c.dispatch('去教室')
        self.assertEqual(self.c.state, 'IDLE')
        self.assertIsNone(self.c.person)

    def test_continuously_visible_person_can_reenter_after_timeout(self):
        self.authorize()
        self.clock.advance(31)
        self.c.tick()
        self.c.identify('p001')
        self.c.tick()
        self.assertEqual(self.c.state, 'WAITING_COMMAND')
        self.assertEqual(self.c.person['id'], 'p001')

    def test_valid_reentry_after_revocation_does_not_wait_for_greeting_cooldown(self):
        self.authorize()
        self.clock.advance(1)
        self.c.invalidate_identity('face temporarily lost')
        self.c.identify('p001')
        self.c.tick()
        self.assertEqual(self.c.state, 'WAITING_COMMAND')
        self.assertEqual(self.c.person['id'], 'p001')

    def test_navigation_timeout_faults(self):
        self.authorize()
        self.c.dispatch('去教室')
        self.nav.deadline = self.clock() + 1000
        self.clock.advance(121)
        self.c.tick()
        self.assertEqual(self.c.state, 'FAULT')
        self.assertTrue(self.nav.stopped())

    def test_stop_must_be_confirmed_before_dialogue(self):
        self.nav.stopped = lambda: False
        self.c.identify('p001')
        self.c.tick()
        self.assertEqual(self.c.state, 'IDENTIFYING')
        self.clock.advance(6)
        self.c.tick()
        self.assertEqual(self.c.state, 'FAULT')
        self.assertIsNone(self.c.person)

    def test_unknown_location_is_not_guessed(self):
        self.authorize()
        self.c.dispatch('带我去办公室')
        self.assertEqual(self.c.state, 'WAITING_COMMAND')
        self.assertIsNone(self.nav.deadline)

    def test_cancel_has_priority_over_destination(self):
        self.assertEqual(parse_command('取消去教室', self.config['places'])['intent'], 'stop')

    def test_multiple_destinations_require_clarification(self):
        places = copy.deepcopy(self.config['places']) + [dict(id='lab', name='实验室', aliases=[])]
        self.assertEqual(parse_command('去教室还是实验室', places)['intent'], 'ambiguous')

    def test_live_place_requires_map_and_finite_pose(self):
        place = copy.deepcopy(self.config['places'][0])
        with self.assertRaises(ValueError): validate_pose(place)
        place.update(map_id='actual', pose=dict(x=0, y=1, yaw=float('nan')))
        with self.assertRaises(ValueError): validate_pose(place)

    def test_location_does_not_invent_real_pose(self):
        self.assertIn('尚未取得', self.c.dispatch('你在哪里'))

    def test_demo_identity_refused_in_live_mode(self):
        self.nav.simulated = False
        with self.assertRaises(ValueError): self.c.identify('p001', simulated_input=True)


if __name__ == '__main__': unittest.main(verbosity=2)
