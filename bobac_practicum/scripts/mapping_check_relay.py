#!/usr/bin/env python
"""Copy real stationary laser into a test namespace; never publish actual odometry."""
import copy
import rospy
from sensor_msgs.msg import LaserScan


def main():
    rospy.init_node('mapping_check_scan_relay')
    if rospy.get_namespace() != '/practicum_mapping_check/':
        raise ValueError('isolated mapping test namespace required')
    pub = rospy.Publisher('scan', LaserScan, queue_size=2)

    def received(message):
        out = copy.deepcopy(message)
        out.header.frame_id = 'mapping_check/laser'
        pub.publish(out)

    rospy.Subscriber('/scan', LaserScan, received, queue_size=2)
    rospy.spin()


if __name__ == '__main__':
    main()
