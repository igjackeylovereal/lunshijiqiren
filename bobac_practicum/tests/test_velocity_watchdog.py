import os
import sys
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts'))
from velocity_watchdog import VelocityLease


class VelocityWatchdogTests(unittest.TestCase):
    def test_no_command_means_zero(self):
        self.assertEqual(VelocityLease().value(10), (0, 0, 0))

    def test_lost_command_does_not_latch_last_speed(self):
        lease = VelocityLease()
        lease.update(10, .2, 0, .1)
        self.assertEqual(lease.value(10.1), (.2, 0, .1))
        self.assertEqual(lease.value(10.31), (0, 0, 0))

    def test_invalid_command_clears_previous_command(self):
        lease = VelocityLease()
        lease.update(10, .2, 0, .1)
        lease.update(10.1, float('nan'), 0, 0)
        self.assertEqual(lease.value(10.2), (0, 0, 0))

    def test_two_wheel_limits_and_clock_reset(self):
        lease = VelocityLease()
        lease.update(10, 1, 1, -2)
        self.assertEqual(lease.value(10.1), (.3, 0, -.5))
        self.assertEqual(lease.value(9), (0, 0, 0))
