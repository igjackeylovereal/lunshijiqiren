from __future__ import unicode_literals
import os
import sys
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts'))
from face_embeddings import select_identity


class EmbeddingDecisionTests(unittest.TestCase):
    def test_single_registered_person_does_not_match_every_face(self):
        self.assertIsNone(select_identity({'p001': .4})['person_id'])

    def test_observed_borderline_stranger_candidate_is_rejected(self):
        self.assertIsNone(select_identity({'p001': .7877})['person_id'])

    def test_close_competing_identities_are_rejected(self):
        self.assertIsNone(select_identity({'p001': .86, 'p002': .83})['person_id'])

    def test_clear_match_is_accepted(self):
        self.assertEqual(select_identity({'p001': .90, 'p002': .60})['person_id'], 'p001')

    def test_empty_gallery_is_not_authorized(self):
        self.assertIsNone(select_identity({})['person_id'])
