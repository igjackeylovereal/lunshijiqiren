from __future__ import unicode_literals
import os
import sys
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts'))
from face_recognition import IdentityWindow


class IdentityWindowTests(unittest.TestCase):
    def test_single_rejection_does_not_destroy_other_matching_votes(self):
        window = IdentityWindow()
        for i, key in enumerate(['p001', 'p001', 'unknown', 'p001']):
            self.assertIsNone(window.update(key, i * .2)[0])
        self.assertEqual(window.update('p001', .8)[0], 'p001')

    def test_old_majority_cannot_authorize_current_stranger(self):
        window = IdentityWindow()
        for i in range(4):
            window.update('p001', i * .2)
        self.assertIsNone(window.update('unknown', 1)[0])

    def test_no_cross_person_vote_combination(self):
        window = IdentityWindow()
        for i, key in enumerate(['p001', 'p002', 'p001', 'p002', 'p001', 'p002']):
            self.assertIsNone(window.update(key, i * .2)[0])

    def test_absence_resets_and_old_frames_expire(self):
        window = IdentityWindow()
        for i in range(3):
            window.update('p001', i * .2)
        self.assertIsNone(window.update('p001', 5)[0])
        window.clear()
        self.assertEqual(window.update('p001', 5.2)[1], 1)

    def test_unknown_needs_own_votes(self):
        window = IdentityWindow()
        for i in range(3):
            self.assertIsNone(window.update('unknown', i * .2)[0])
        self.assertEqual(window.update('unknown', .6)[0], 'unknown')


if __name__ == '__main__':
    unittest.main()
