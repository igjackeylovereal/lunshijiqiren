# -*- coding: utf-8 -*-
import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__))+'/scripts')
from ros_adapter import ensure_localization


class LocalizationTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.last_localization = 90.
        self.requests = 0
        self.respond = True
        self.fail = False

    def clock(self):
        return self.now

    def pause(self, seconds):
        self.now += seconds

    def request_localization_update(self):
        self.requests += 1
        if self.fail:
            raise RuntimeError('service unavailable')
        if self.respond:
            self.last_localization = self.now

    def test_fresh_pose_needs_no_forced_update(self):
        self.last_localization = 99.
        ensure_localization(self, self.clock, self.pause)
        self.assertEqual(self.requests, 0)

    def test_stationary_stale_pose_requires_new_observation(self):
        ensure_localization(self, self.clock, self.pause)
        self.assertEqual(self.requests, 1)
        self.assertEqual(self.last_localization, 100.)

    def test_no_new_observation_fails_closed(self):
        self.respond = False
        with self.assertRaises(ValueError):
            ensure_localization(self, self.clock, self.pause, timeout=.1)
        self.assertEqual(self.last_localization, 90.)

    def test_missing_amcl_service_fails_closed(self):
        self.fail = True
        with self.assertRaises(ValueError):
            ensure_localization(self, self.clock, self.pause)


if __name__ == '__main__': unittest.main()
