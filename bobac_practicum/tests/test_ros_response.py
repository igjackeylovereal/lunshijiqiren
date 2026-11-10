# -*- coding: utf-8 -*-
import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)) + '/scripts')
from app import parse_ros_response
try:
    import yaml
except ImportError:
    yaml = None


@unittest.skipUnless(yaml is not None, 'PyYAML is provided by the robot ROS environment')
class ResponseTests(unittest.TestCase):
    def test_kinetic_chinese_scalar(self):
        response = parse_ros_response('iat_str: !!python/str "\\u53BB\\u6559\\u5BA4"\nnlp_str: ""')
        self.assertEqual(response['iat_str'], u'去教室')

    def test_arbitrary_python_tag_is_rejected(self):
        with self.assertRaises(yaml.constructor.ConstructorError):
            parse_ros_response('!!python/object/apply:os.system ["echo unexpected"]')


if __name__ == '__main__': unittest.main()
