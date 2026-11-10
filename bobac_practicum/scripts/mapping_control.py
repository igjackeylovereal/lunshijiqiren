# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import math
import threading
import time
import uuid


class MappingLease(object):
    """Initial operator test: forward only, bounded pulse and total travel."""
    def __init__(self, speed=.05):
        if not .02 <= speed <= .10:
            raise ValueError('initial test speed must be between 0.02 and 0.10 m/s')
        self.speed = speed
        self.pulse_seconds = min(.6, .03 / speed)
        self.active = None
        self.started = self.heartbeat = 0
        self.consumed = set()
        self.origin = None
        self.pulse_origin = None
        self.halted = False
        self.reason = '请按住前进按钮进行短距离测试'

    def stop(self, token=None, halt=False):
        if token:
            self.consumed.add(token)
        if self.active:
            self.consumed.add(self.active)
        self.active = None
        self.halted = self.halted or halt
        self.reason = '已停车并暂停' if self.halted else '已停车，松开后可重新按下'

    def readiness(self, health):
        if self.halted:
            return '遥控已暂停，请重新启用'
        if not health.get('scan_fresh') or not health.get('odom_fresh'):
            return '雷达或实际里程计数据不新鲜，禁止移动'
        if not health.get('map_ready'):
            return '实际SLAM地图或坐标变换尚未就绪，禁止移动'
        if not health.get('base_ready'):
            return '底盘写入回执异常或未就绪，禁止移动'
        if not health.get('collision_clear'):
            return '碰撞传感器未确认正常，禁止移动'
        pose = health.get('pose')
        if not pose or not all(not math.isnan(x) and not math.isinf(x) for x in pose):
            return '实际里程计位置无效'
        clearance = health.get('forward_clearance')
        if clearance is None or clearance < .35:
            return '前方通道不足0.35米或测距不足，已停止'
        if self.origin and math.hypot(pose[0]-self.origin[0], pose[1]-self.origin[1]) >= .10:
            return '首次测试累计位移已达约10厘米，请先核对实物方向和停车效果'
        return ''

    def renew(self, token, now, health):
        if not isinstance(token, type(u'')) or not 8 <= len(token) <= 80:
            raise ValueError('无效操作编号')
        if token in self.consumed:
            raise ValueError('本次脉冲已结束，请松开后重新按下')
        reason = self.readiness(health)
        if reason:
            self.stop(token)
            self.reason = reason
            raise ValueError(reason)
        if self.active and self.active != token:
            self.stop(token)
            raise ValueError('同时存在另一条操作，请先松开所有按钮')
        if self.active is None:
            self.active, self.started = token, now
            self.pulse_origin = health['pose'][:2]
            if self.origin is None:
                self.origin = health['pose'][:2]
        self.heartbeat = now

    def tick(self, now, health):
        reason = self.readiness(health)
        if self.active:
            if reason or now-self.heartbeat > .25 or now-self.heartbeat < 0:
                self.stop()
                self.reason = reason or '操作心跳结束，已停车'
            elif now-self.started >= self.pulse_seconds:
                self.stop()
                self.reason = '本次短脉冲结束，请松开按钮'
            elif math.hypot(health['pose'][0]-self.pulse_origin[0], health['pose'][1]-self.pulse_origin[1]) >= .04:
                self.stop()
                self.reason = '本次位移达到限制，已停车'
            else:
                self.reason = '前进微动中，松开立即停止'
                return self.speed, 0.
        elif reason:
            self.reason = reason
        else:
            self.reason = '已就绪，按住按钮开始下一次短脉冲'
        return 0., 0.


class KeyboardLease(MappingLease):
    """Held key control; unavailable directions fail closed on missing laser coverage."""
    velocities = dict(forward=(.06, 0.), backward=(-.04, 0.), left=(0., .18), right=(0., -.18))

    def __init__(self):
        super(KeyboardLease, self).__init__(.06)
        self.direction = 'forward'
        self.pulse_seconds = 5.

    def readiness(self, health):
        base = dict(health, forward_clearance=1., pose=health.get('pose'))
        origin, self.origin = self.origin, None
        try:
            reason = super(KeyboardLease, self).readiness(base)
        finally:
            self.origin = origin
        if reason:
            return reason
        clearance = health.get('direction_clearance', {}).get(self.direction)
        if clearance is None or clearance < .40:
            return '该方向激光覆盖不足或障碍距离小于0.40米，禁止移动'
        return ''

    def renew_direction(self, token, direction, now, health):
        if direction not in self.velocities:
            raise ValueError('未知方向')
        if self.active and direction != self.direction:
            self.stop(token)
            raise ValueError('切换方向前请松开按键')
        self.direction = direction
        self.renew(token, now, health)

    def tick(self, now, health):
        reason = self.readiness(health)
        if self.active:
            if reason or not 0 <= now-self.heartbeat <= .25 or not 0 <= now-self.started < 5:
                self.stop()
                self.reason = reason or '心跳或单次按住时限已到，请松开后再按'
            else:
                self.reason = '键盘遥控中，松开立即停车'
                return self.velocities[self.direction]
        return 0., 0.


class MappingControl(object):
    def __init__(self, runtime, speed=.05, keyboard=False):
        from geometry_msgs.msg import Twist
        self.Twist, self.runtime = Twist, runtime
        self.keyboard = keyboard
        self.policy = KeyboardLease() if keyboard else MappingLease(speed)
        self.policy.halted = True
        self.policy.reason = '遥控初始暂停，检查现场后点击重新启用操作'
        self.lock = threading.RLock()
        self.session = uuid.uuid4().hex
        self.publisher = runtime.rospy.Publisher('/cmd_vel', Twist, queue_size=1)
        self.last_velocity = 0.
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self.loop)
        self.thread.daemon = True
        self.thread.start()

    def loop(self):
        while not self.closed.is_set():
            try:
                with self.lock:
                    vx, wz = self.policy.tick(time.time(), self.runtime.teleop_health())
                    msg = self.Twist()
                    msg.linear.x, msg.angular.z = vx, wz
                    self.publisher.publish(msg)
                    self.last_velocity = vx
            except Exception:
                with self.lock:
                    self.policy.stop(halt=True)
                    self.last_velocity = 0.
                    self.publisher.publish(self.Twist())
            self.closed.wait(.05)

    def request(self, data):
        with self.lock:
            if data.get('action') == 'stop':
                token = data.get('press_id')
                self.policy.stop(token if isinstance(token, type(u'')) else None, halt=data.get('halt') is True)
                self.publisher.publish(self.Twist())
                self.last_velocity = 0.
                return
            if data.get('session') != self.session:
                raise ValueError('页面会话已过期，请刷新页面')
            action, token = data.get('action'), data.get('press_id')
            if self.keyboard and action in KeyboardLease.velocities:
                self.policy.renew_direction(token, action, time.time(), self.runtime.teleop_health())
            elif action == 'forward':
                self.policy.renew(token, time.time(), self.runtime.teleop_health())
            elif action == 'reset':
                self.policy.halted = False
                self.policy.stop(token)
            elif action == 'profile':
                if self.keyboard:
                    raise ValueError('键盘建图使用固定低速档位')
                speed = data.get('speed')
                if speed not in (.05, .08):
                    raise ValueError('只支持已限定行程的两个测试档位')
                health = self.runtime.teleop_health()
                if self.policy.active or health['linear_speed'] > .01 or health['angular_speed'] > .03:
                    raise ValueError('先停车，再调整测试档位')
                self.policy.stop(halt=True)
                self.policy.speed = speed
                self.policy.pulse_seconds = .03 / speed
            else:
                raise ValueError('首次测试只允许前进微动和停车')

    def snapshot(self):
        with self.lock:
            health = self.runtime.teleop_health()
            return dict(enabled=True, session=self.session, profile='keyboard_mapping' if self.keyboard else 'initial_forward_test',
                        directions=list(KeyboardLease.velocities) if self.keyboard else ['forward'],
                        active=bool(self.policy.active), halted=self.policy.halted,
                        ready=not bool(self.policy.readiness(health)), reason=self.policy.reason,
                        max_speed=self.policy.speed, max_pulse_seconds=self.policy.pulse_seconds,
                        max_initial_travel=None if self.keyboard else .10,
                        command_vx=self.last_velocity, health=health)

    def close(self):
        with self.lock:
            self.policy.stop(halt=True)
            self.closed.set()
            self.publisher.publish(self.Twist())
        self.thread.join(1)
        self.publisher.publish(self.Twist())
