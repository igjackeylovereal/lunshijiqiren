import os
import sys
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts'))
from base_io import encode_speeds, decode_speed, effective_command, velocity_to_rpm


class BaseIoTests(unittest.TestCase):
    def test_vendor_big_endian_double_registers(self):
        words = encode_speeds((1., -1., 0.))
        self.assertEqual(words[:4], [0x3ff0, 0, 0, 0])
        self.assertEqual(words[4:8], [0xbff0, 0, 0, 0])
        self.assertEqual(len(words), 13)
        self.assertEqual(words[-1], 0)

    def test_roundtrip_actual_command_and_feedback(self):
        words = encode_speeds((-7.021541607, 7.021541607, 0.))
        self.assertAlmostEqual(decode_speed(words[:4]), -7.021541607)
        self.assertAlmostEqual(decode_speed(words[4:8]), 7.021541607)

    def test_readonly_fault_and_old_command_never_write_motion(self):
        for kwargs in [dict(readonly=True), dict(fault=True)]:
            self.assertEqual(effective_command((-7, 7), .01, **kwargs), (0, 0, 0))
        self.assertEqual(effective_command((-7, 7), .3), (0, 0, 0))
        self.assertEqual(effective_command((-7, 7), -.1), (0, 0, 0))

    def test_bad_values_fail_closed(self):
        self.assertEqual(effective_command((float('nan'), 7), .1), (0, 0, 0))
        with self.assertRaises(ValueError): encode_speeds((0, float('inf'), 0))

    def test_velocity_conversion_matches_verified_vendor_signs(self):
        left, right, third = velocity_to_rpm(.05, 0)
        self.assertAlmostEqual(left, -7.021541606995383)
        self.assertAlmostEqual(right, 7.021541606995383)
        self.assertEqual(third, 0)

    def test_turn_and_nonfinite_input(self):
        left, right, _ = velocity_to_rpm(0, .1)
        self.assertGreater(left, 0)
        self.assertAlmostEqual(left, right)
        self.assertEqual(velocity_to_rpm(float('nan'), 0), (0, 0, 0))
