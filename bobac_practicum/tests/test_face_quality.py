from __future__ import unicode_literals
import os
import sys
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts'))
from face_recognition import face_sample
try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = np = None


@unittest.skipIf(cv2 is None, 'OpenCV tests run on robot')
class FaceQualityTests(unittest.TestCase):
    def setUp(self):
        self.image = np.indices((240, 320)).sum(axis=0).astype(np.uint8)
        self.image = (self.image % 2 * 100 + 70).astype(np.uint8)

    def test_clear_centered_face_can_be_used(self):
        sample, metrics, reason = face_sample(cv2, self.image, (70, 50, 128, 128))
        self.assertEqual(sample.shape, (128, 128))
        self.assertTrue(metrics['accepted'])
        self.assertEqual(reason, '')

    def test_frame_edge_blocks_incomplete_face(self):
        _, metrics, reason = face_sample(cv2, self.image, (0, 50, 128, 128))
        self.assertFalse(metrics['accepted'])
        self.assertTrue(metrics['clipped'])

    def test_small_face_cannot_enter_training(self):
        _, metrics, _ = face_sample(cv2, self.image, (70, 50, 60, 60))
        self.assertFalse(metrics['accepted'])

    def test_dark_and_overexposed_faces_blocked(self):
        for value in (20, 240):
            _, metrics, _ = face_sample(cv2, np.full((240, 320), value, np.uint8), (70, 50, 128, 128))
            self.assertFalse(metrics['accepted'])

    def test_blur_is_checked_before_histogram_equalization(self):
        image = np.full((240, 320), 100, np.uint8)
        _, metrics, _ = face_sample(cv2, image, (70, 50, 128, 128))
        self.assertFalse(metrics['accepted'])
        self.assertEqual(metrics['sharpness'], 0)
