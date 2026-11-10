#!/usr/bin/env python
"""Only launched when wheel commands are explicitly enabled."""
import math
import threading


class VelocityLease(object):
    def __init__(self, timeout=.3, max_vx=.3, max_wz=.5):
        self.timeout, self.max_vx, self.max_wz = timeout, max_vx, max_wz
        self.last, self.command = None, (0., 0., 0.)
        self.lock = threading.Lock()

    def update(self, now, vx, vy, wz):
        with self.lock:
            if not all(not math.isnan(v) and not math.isinf(v) for v in (now, vx, vy, wz)):
                self.last, self.command = None, (0., 0., 0.)
                return
            self.last = now
            self.command = (max(-self.max_vx, min(self.max_vx, vx)), 0.,
                            max(-self.max_wz, min(self.max_wz, wz)))

    def value(self, now):
        with self.lock:
            if self.last is None or not 0 <= now - self.last <= self.timeout:
                return (0., 0., 0.)
            return self.command


def main():
    import rospy
    from geometry_msgs.msg import Twist
    rospy.init_node('practicum_velocity_watchdog')
    lease = VelocityLease(rospy.get_param('~timeout', .3))
    publisher = rospy.Publisher('guarded_cmd_vel', Twist, queue_size=1)

    def received(msg):
        lease.update(rospy.Time.now().to_sec(), msg.linear.x, msg.linear.y, msg.angular.z)

    def tick(event):
        msg = Twist()
        msg.linear.x, msg.linear.y, msg.angular.z = lease.value(rospy.Time.now().to_sec())
        publisher.publish(msg)

    rospy.Subscriber('cmd_vel', Twist, received, queue_size=1)
    rospy.Timer(rospy.Duration(.05), tick)
    rospy.on_shutdown(lambda: publisher.publish(Twist()))
    rospy.spin()


if __name__ == '__main__':
    main()
