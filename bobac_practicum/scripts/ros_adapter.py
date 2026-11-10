# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import hashlib
import json
import math
import threading
import time
from core import validate_pose
from perception import scan_observation


def ensure_localization(runtime, clock=time.time, pause=time.sleep, timeout=1.5):
    """Ask AMCL to process a real scan when its stationary pose has gone stale."""
    before = runtime.last_localization
    if 0 <= clock()-before <= 5:
        return
    try:
        runtime.request_localization_update()
    except Exception:
        raise ValueError('无法请求AMCL重新定位，请检查定位服务')
    deadline = clock()+timeout
    while runtime.last_localization <= before:
        if clock() >= deadline:
            raise ValueError('等待AMCL新定位超时，导航未启动')
        pause(.03)
    if not 0 <= clock()-runtime.last_localization <= 5:
        raise ValueError('AMCL定位时间无效，导航未启动')


class RosRuntime(object):
    def __init__(self, config):
        import rospy
        import tf
        from cv_bridge import CvBridge
        from sensor_msgs.msg import Image, LaserScan
        from nav_msgs.msg import Odometry, OccupancyGrid
        from geometry_msgs.msg import PoseWithCovarianceStamped
        from std_msgs.msg import String
        from bobac2_msgs.msg import car_data
        rospy.init_node('bobac_practicum', disable_signals=True)
        self.rospy, self.config = rospy, config
        self.bridge = CvBridge()
        self.image_pub = rospy.Publisher(config['camera_topic'], Image, queue_size=1)
        self.tf = tf.TransformListener()
        self.last_scan = self.last_odom = self.last_localization = 0
        self.linear = self.angular = 0
        self.covariance = float('inf')
        self.map_id = None
        self.obstacles = None
        self.scan_stamp = self.odom_stamp = 0.
        self.forward_clearance = None
        self.direction_clearance = {}
        self.odom_pose = None
        self.map_message = None
        self.io_status = {}
        self.io_received = 0.
        self.collision_clear = False
        self.infrared = []
        rospy.Subscriber('/scan', LaserScan, self.scan, queue_size=1)
        rospy.Subscriber('/odom', Odometry, self.odom, queue_size=1)
        rospy.Subscriber('/map', OccupancyGrid, self.map, queue_size=1)
        rospy.Subscriber('/amcl_pose', PoseWithCovarianceStamped, self.localization, queue_size=1)
        rospy.Subscriber('/practicum_base/io_status', String, self.base_status, queue_size=1)
        rospy.Subscriber('/car_data', car_data, self.base_sensors, queue_size=1)

    def base_status(self, msg):
        try:
            self.io_status = json.loads(msg.data)
            self.io_received = time.time()
        except (ValueError, TypeError):
            self.io_status = {}

    def base_sensors(self, msg):
        self.collision_clear = len(msg.crash) >= 3 and all(v == 1 for v in msg.crash)
        self.infrared = list(msg.infrared)

    def scan(self, msg):
        if msg.ranges:
            self.last_scan = time.time()
            self.scan_stamp = msg.header.stamp.to_sec()
            corridor = []
            for i, distance in enumerate(msg.ranges):
                if math.isnan(distance) or math.isinf(distance) or not msg.range_min <= distance <= msg.range_max:
                    continue
                angle = msg.angle_min + i * msg.angle_increment
                x, y = distance * math.cos(angle), distance * math.sin(angle)
                if x > 0 and abs(y) <= .23:
                    corridor.append(x)
            self.forward_clearance = min(corridor) if len(corridor) >= 3 else None
            # Rear requires actual angular coverage; never infer it from a clear front.
            sectors = dict(forward=[], backward=[], left=[], right=[])
            coverage = []
            for i, distance in enumerate(msg.ranges):
                angle = msg.angle_min+i*msg.angle_increment
                if math.isnan(distance) or math.isinf(distance) or not msg.range_min <= distance <= msg.range_max:
                    continue
                angle = math.atan2(math.sin(angle), math.cos(angle))
                coverage.append(angle)
                if abs(angle) < .7: sectors['forward'].append(distance)
                if abs(angle) > math.pi-.7: sectors['backward'].append(distance)
                sectors['left'].append(distance)
                sectors['right'].append(distance)
            self.direction_clearance = dict((k, min(v) if len(v) >= 5 else None) for k, v in sectors.items())

            self.obstacles = scan_observation(msg.ranges, msg.angle_min, msg.angle_increment,
                                              msg.range_min, msg.range_max)

    def odom(self, msg):
        self.last_odom = time.time()
        self.odom_stamp = msg.header.stamp.to_sec()
        self.odom_pose = (msg.pose.pose.position.x, msg.pose.pose.position.y)
        self.linear = math.hypot(msg.twist.twist.linear.x, msg.twist.twist.linear.y)
        self.angular = abs(msg.twist.twist.angular.z)

    def localization(self, msg):
        self.last_localization = time.time()
        self.covariance = max(msg.pose.covariance[0], msg.pose.covariance[7])

    def request_localization_update(self):
        from std_srvs.srv import Empty
        self.rospy.wait_for_service('/request_nomotion_update', timeout=.75)
        self.rospy.ServiceProxy('/request_nomotion_update', Empty)()

    def map(self, msg):
        self.map_message = msg
        origin = msg.info.origin
        metadata = [msg.info.width, msg.info.height, msg.info.resolution,
                    origin.position.x, origin.position.y, origin.orientation.z, origin.orientation.w]
        body = json.dumps(metadata).encode('ascii') + bytes(bytearray((v + 1) for v in msg.data))
        self.map_id = hashlib.sha256(body).hexdigest()

    def position(self):
        try:
            stamp = self.tf.getLatestCommonTime(self.config['map_frame'], self.config['base_frame'])
            if (self.rospy.Time.now() - stamp).to_sec() > 2:
                return None
            pos, quat = self.tf.lookupTransform(self.config['map_frame'], self.config['base_frame'], self.rospy.Time(0))
            import tf
            return pos[0], pos[1], tf.transformations.euler_from_quaternion(quat)[2]
        except Exception:
            return None

    def publish_frame(self, frame):
        msg = self.bridge.cv2_to_imgmsg(frame, encoding=b'bgr8')
        msg.header.stamp = self.rospy.Time.now()
        msg.header.frame_id = 'camera_rgb_optical_frame'
        self.image_pub.publish(msg)

    def health(self):
        now = time.time()
        return dict(scan_fresh=now - self.last_scan < 1.5,
                    odom_fresh=now - self.last_odom < 1,
                    localized=self.position() is not None,
                    map_id=self.map_id, obstacle_observation=self.obstacles)

    def teleop_health(self):
        now = time.time()
        ros_now = self.rospy.Time.now().to_sec()
        return dict(scan_fresh=now-self.last_scan < .6 and 0 <= ros_now-self.scan_stamp < .6,
                    odom_fresh=now-self.last_odom < .4 and 0 <= ros_now-self.odom_stamp < .4,
                    map_ready=self.map_message is not None and self.position() is not None,
                    forward_clearance=self.forward_clearance, direction_clearance=self.direction_clearance, pose=self.odom_pose,
                    base_ready=now-self.io_received < .5 and bool(self.io_status.get('write_ok'))
                        and not self.io_status.get('read_only', True) and not self.io_status.get('fault'),
                    collision_clear=self.collision_clear, infrared=self.infrared, base_io=self.io_status,
                    linear_speed=self.linear, angular_speed=self.angular)


class LiveNavigation(object):
    simulated = False

    def __init__(self, config, runtime, explicit_allow=False):
        if not config.get('motion_enabled') or not explicit_allow:
            raise ValueError('实际运动需要配置与启动参数同时明确启用')
        import actionlib
        from move_base_msgs.msg import MoveBaseAction
        self.config, self.runtime = config, runtime
        self.client = actionlib.SimpleActionClient(config['navigation_action'], MoveBaseAction)
        self.active = False
        self.result = None
        self.generation = 0

    def send(self, place):
        from move_base_msgs.msg import MoveBaseGoal
        import tf
        pose = validate_pose(place)
        health = self.runtime.health()
        if place['map_id'] != health['map_id']:
            raise ValueError('地点所属地图与当前地图不一致')
        if not all(health[k] for k in ('scan_fresh', 'odom_fresh', 'localized')):
            raise ValueError('雷达、里程计或定位尚未就绪')
        ensure_localization(self.runtime)
        if self.runtime.covariance > 1:
            raise ValueError('AMCL 定位尚未满足条件')
        if not self.client.wait_for_server(self.runtime.rospy.Duration(1)):
            raise ValueError('导航 Action 不可用')
        self.generation += 1
        generation = self.generation
        self.result = None
        goal = MoveBaseGoal()
        goal.target_pose.header.frame_id = self.config['map_frame']
        goal.target_pose.header.stamp = self.runtime.rospy.Time.now()
        goal.target_pose.pose.position.x = pose['x']
        goal.target_pose.pose.position.y = pose['y']
        q = tf.transformations.quaternion_from_euler(0, 0, pose['yaw'])
        goal.target_pose.pose.orientation.x, goal.target_pose.pose.orientation.y = q[0], q[1]
        goal.target_pose.pose.orientation.z, goal.target_pose.pose.orientation.w = q[2], q[3]

        def done(status, result):
            if generation != self.generation:
                return
            self.active = False
            self.result = 'succeeded' if status == 3 else ('cancelled' if status in (2, 8) else 'failed')
        self.active = True
        self.client.send_goal(goal, done_cb=done)

    def cancel(self):
        if self.active:
            self.client.cancel_goal()

    def stopped(self):
        return (not self.active and time.time() - self.runtime.last_odom < 1
                and self.runtime.linear < 0.02 and self.runtime.angular < 0.03)

    def poll(self):
        result, self.result = self.result, None
        return result

    def position(self):
        return self.runtime.position()
