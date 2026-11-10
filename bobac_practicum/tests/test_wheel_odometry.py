import math
import os
import sys
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts'))
from wheel_odometry import DifferentialOdometry


class WheelOdometryTests(unittest.TestCase):
    def test_stationary_feedback_has_fresh_time_without_drift(self):
        odom = DifferentialOdometry()
        for tick in range(10):
            value = odom.update(100 + tick * .1, 0, 0)
        self.assertEqual(odom.last, 100.9)
        self.assertEqual((value['x'], value['y'], value['yaw']), (0, 0, 0))

    def test_straight_line_uses_vendor_left_wheel_sign(self):
        odom = DifferentialOdometry()
        for tick in range(11):
            value = odom.update(tick * .1, -60, 60)
        self.assertAlmostEqual(value['x'], 2 * math.pi * .068)
        self.assertAlmostEqual(value['y'], 0)
        self.assertAlmostEqual(value['wz'], 0)

    def test_in_place_turn_has_no_translation(self):
        odom = DifferentialOdometry()
        for tick in range(11):
            value = odom.update(tick * .1, 10, 10)
        self.assertAlmostEqual(value['x'], 0)
        self.assertAlmostEqual(value['y'], 0)
        self.assertGreater(value['yaw'], 0)

    def test_missing_encoder_interval_cannot_look_like_valid_odometry(self):
        odom = DifferentialOdometry()
        odom.update(1, -60, 60)
        with self.assertRaises(ValueError):
            odom.update(3, -60, 60)
        with self.assertRaises(ValueError):
            odom.update(3.1, 0, 0)
        self.assertEqual(odom.x, 0)

    def test_invalid_telemetry_and_backwards_clock_are_rejected(self):
        odom = DifferentialOdometry()
        with self.assertRaises(ValueError):
            odom.update(1, float('nan'), 0)
        odom.update(2, 0, 0)
        with self.assertRaises(ValueError):
            odom.update(1, 0, 0)
