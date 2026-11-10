import os
import sys
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts'))
from mapping_control import MappingLease


class MappingLeaseTests(unittest.TestCase):
    def setUp(self):
        self.health = dict(scan_fresh=True, odom_fresh=True, map_ready=True, base_ready=True,
                           collision_clear=True, pose=(0., 0.), forward_clearance=.5)
        self.policy = MappingLease()

    def test_no_operator_request_never_moves(self):
        self.assertEqual(self.policy.tick(1, self.health), (0, 0))

    def test_missing_heartbeat_stops_and_replay_cannot_restart(self):
        self.policy.renew(u'press_12345', 1, self.health)
        self.assertEqual(self.policy.tick(1.1, self.health), (.05, 0))
        self.assertEqual(self.policy.tick(1.3, self.health), (0, 0))
        with self.assertRaises(ValueError): self.policy.renew(u'press_12345', 1.31, self.health)

    def test_heartbeat_does_not_extend_pulse(self):
        self.policy.renew(u'press_12345', 1, self.health)
        for now in (1.1, 1.2, 1.3, 1.4, 1.5): self.policy.renew(u'press_12345', now, self.health)
        self.assertEqual(self.policy.tick(1.61, self.health), (0, 0))

    def test_stop_arriving_before_delayed_forward_consumes_token(self):
        self.policy.stop(u'press_12345')
        with self.assertRaises(ValueError): self.policy.renew(u'press_12345', 1, self.health)

    def test_stale_sensors_and_close_obstacle_block_movement(self):
        for change in [dict(scan_fresh=False), dict(odom_fresh=False), dict(map_ready=False), dict(base_ready=False),
                       dict(collision_clear=False), dict(forward_clearance=.2), dict(forward_clearance=None)]:
            health = dict(self.health, **change)
            with self.assertRaises(ValueError): MappingLease().renew(u'press_12345', 1, health)

    def test_step_and_total_distance_limits(self):
        self.policy.renew(u'press_12345', 1, self.health)
        moved = dict(self.health, pose=(.041, 0))
        self.assertEqual(self.policy.tick(1.1, moved), (0, 0))
        with self.assertRaises(ValueError): self.policy.renew(u'newpress_1', 1.2, dict(self.health, pose=(.11, 0)))

    def test_startup_calibration_does_not_increase_pulse_distance(self):
        policy = MappingLease(.08)
        self.assertAlmostEqual(policy.pulse_seconds, .375)
        self.assertAlmostEqual(policy.speed * policy.pulse_seconds, .03)
        policy.renew(u'press_12345', 1, self.health)
        policy.renew(u'press_12345', 1.3, self.health)
        self.assertEqual(policy.tick(1.4, self.health), (0, 0))
        with self.assertRaises(ValueError): MappingLease(.2)
