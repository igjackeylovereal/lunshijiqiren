#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Odometry from actual car_data only. Never subscribes to command velocity."""
from __future__ import division
import math


class DifferentialOdometry(object):
    def __init__(self, radius=.068, separation=.32374, max_gap=.5):
        if radius <= 0 or separation <= 0 or max_gap <= 0:
            raise ValueError('invalid odometry dimensions')
        self.radius, self.separation, self.max_gap = radius, separation, max_gap
        self.x = self.y = self.yaw = 0.0
        self.last = None
        self.vx = self.wz = 0.0
        self.fault = False

    def update(self, now, left_rpm, right_rpm):
        if self.fault:
            raise ValueError('odometry fault latched; restart after checking telemetry')
        if not all(not math.isnan(v) and not math.isinf(v) for v in (now, left_rpm, right_rpm)):
            raise ValueError('invalid encoder telemetry')
        if max(abs(left_rpm), abs(right_rpm)) > 300:
            raise ValueError('implausible encoder RPM')
        vx = (right_rpm - left_rpm) * math.pi * self.radius / 60.0
        wz = (right_rpm + left_rpm) * 2 * math.pi * self.radius / (60.0 * self.separation)
        if self.last is not None:
            dt = now - self.last
            if dt < 0 or dt > self.max_gap:
                self.fault = True
                raise ValueError('encoder gap or clock jump; refusing to integrate missing interval')
            v, w = (vx + self.vx) / 2, (wz + self.wz) / 2
            final_yaw = self.yaw + w * dt
            if abs(w) < 1e-8:
                self.x += v * math.cos(self.yaw) * dt
                self.y += v * math.sin(self.yaw) * dt
            else:
                self.x += v / w * (math.sin(final_yaw) - math.sin(self.yaw))
                self.y -= v / w * (math.cos(final_yaw) - math.cos(self.yaw))
            self.yaw = math.atan2(math.sin(final_yaw), math.cos(final_yaw))
        self.last, self.vx, self.wz = now, vx, wz
        return dict(x=self.x, y=self.y, yaw=self.yaw, vx=vx, wz=wz)


def main():
    import rospy
    import tf
    from nav_msgs.msg import Odometry
    from bobac2_msgs.msg import car_data
    rospy.init_node('practicum_wheel_odometry')
    model = DifferentialOdometry(rospy.get_param('~wheel_radius', .068),
                                 rospy.get_param('~wheel_separation', .32374),
                                 rospy.get_param('~max_gap', .5))
    frame = rospy.get_param('~odom_frame', 'odom')
    base = rospy.get_param('~base_frame', 'base_footprint')
    publisher = rospy.Publisher('odom', Odometry, queue_size=5)
    broadcaster = tf.TransformBroadcaster()

    def received(message):
        if len(message.speed) < 2:
            rospy.logerr_throttle(5, 'car_data lacks two encoder speeds')
            return
        stamp = rospy.Time.now()
        try:
            value = model.update(stamp.to_sec(), message.speed[0], message.speed[1])
        except ValueError as exc:
            rospy.logerr_throttle(5, str(exc))
            return
        quat = tf.transformations.quaternion_from_euler(0, 0, value['yaw'])
        msg = Odometry()
        msg.header.stamp, msg.header.frame_id, msg.child_frame_id = stamp, frame, base
        msg.pose.pose.position.x, msg.pose.pose.position.y = value['x'], value['y']
        msg.pose.pose.orientation.x, msg.pose.pose.orientation.y = quat[0], quat[1]
        msg.pose.pose.orientation.z, msg.pose.pose.orientation.w = quat[2], quat[3]
        msg.twist.twist.linear.x, msg.twist.twist.angular.z = value['vx'], value['wz']
        for axis in (0, 7, 35):
            msg.pose.covariance[axis], msg.twist.covariance[axis] = .05, .05
        for axis in (14, 21, 28):
            msg.pose.covariance[axis], msg.twist.covariance[axis] = 1e6, 1e6
        publisher.publish(msg)
        broadcaster.sendTransform((value['x'], value['y'], 0), quat, stamp, base, frame)

    rospy.Subscriber('car_data', car_data, received, queue_size=5)
    # No telemetry => no odometry / TF. A periodic zero would hide a disconnected base.
    rospy.spin()


if __name__ == '__main__':
    main()
