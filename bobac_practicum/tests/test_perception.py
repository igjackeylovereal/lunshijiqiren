import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)) + '/scripts')
from perception import scan_observation


class ScanTests(unittest.TestCase):
    def test_invalid_ranges_are_not_obstacles(self):
        result = scan_observation([float('nan'), float('inf'), 0, 50], -0.1, .1, .15, 12)
        self.assertEqual(result['clusters'], 0)
        self.assertFalse(result['front_blocked'])

    def test_front_obstacle(self):
        result = scan_observation([.5, .51, .52, float('inf')], -.1, .1, .15, 12)
        self.assertTrue(result['front_blocked'])
        self.assertEqual(result['clusters'], 1)

    def test_isolated_noise_is_not_a_cluster(self):
        result = scan_observation([.4, float('inf'), .3], -.1, .1, .15, 12)
        self.assertEqual(result['clusters'], 0)


if __name__ == '__main__': unittest.main()
