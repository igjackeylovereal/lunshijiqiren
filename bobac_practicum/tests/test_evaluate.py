import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)) + '/scripts')
from evaluate import evaluate


class EvaluationTests(unittest.TestCase):
    def test_no_trials_never_passes(self):
        self.assertIsNone(evaluate([])['target_met'])

    def test_false_accepts_are_reported_separately(self):
        result = evaluate([dict(expected='p001', predicted='p001'),
                           dict(expected='unknown', predicted='p001')])
        self.assertEqual(result['accuracy'], 0.5)
        self.assertEqual(result['false_accept_rate'], 1.0)

    def test_missing_labels_refused(self):
        with self.assertRaises(ValueError): evaluate([dict(expected='p001', predicted='')])


if __name__ == '__main__': unittest.main()
