# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import json
import math
import threading
import time


def as_text(value):
    try:
        text_type = unicode
    except NameError:
        text_type = str
    return value.decode('utf-8') if isinstance(value, bytes) else text_type(value)


def parse_command(text, places):
    text = as_text(text).strip()
    if any(w in text for w in ['取消', '停止', '停下', '别走']):
        return {'intent': 'stop'}
    if any(w in text for w in ['你好', '您好']):
        return {'intent': 'greeting'}
    if any(w in text for w in ['你在哪', '在哪里', '当前位置', '位置在哪']):
        return {'intent': 'location'}
    if any(w in text for w in ['能做什么', '服务项目', '什么服务', '有什么功能']):
        return {'intent': 'help'}
    if any(w in text for w in ['继续巡航', '恢复巡航', '开始巡航']):
        return {'intent': 'patrol'}
    matches = []
    for place in places:
        if any(alias and alias in text for alias in place.get('aliases', []) + [place['name']]):
            matches.append(place['id'])
    if len(matches) > 1:
        return {'intent': 'ambiguous'}
    if matches:
        return {'intent': 'navigate', 'place_id': matches[0]}
    return {'intent': 'unknown'}


def validate_pose(place):
    pose = place.get('pose')
    if not place.get('map_id') or not isinstance(pose, dict):
        raise ValueError('地点未记录实际地图与坐标')
    for key in ('x', 'y', 'yaw'):
        val = pose.get(key)
        if isinstance(val, bool) or not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
            raise ValueError('地点坐标无效')
    return pose


class SimNavigation(object):
    simulated = True

    def __init__(self, clock=time.time):
        self.clock = clock
        self.deadline = None
        self.result = None

    def send(self, place):
        self.result = None
        self.deadline = self.clock() + 3.0

    def cancel(self):
        self.deadline = None
        self.result = 'cancelled'

    def stopped(self):
        return self.deadline is None

    def poll(self):
        if self.deadline is not None and self.clock() >= self.deadline:
            self.deadline = None
            self.result = 'succeeded'
        result, self.result = self.result, None
        return result

    def position(self):
        return None


class Controller(object):
    def __init__(self, config, navigation, logger, clock=time.time):
        self.config, self.nav, self.log, self.clock = config, navigation, logger, clock
        self.lock = threading.RLock()
        self.state = 'IDLE'
        self.person = None
        self.target = None
        self.reply = '系统已就绪，当前为静态联调。' if self.nav.simulated else '导航模式已就绪，请完成身份验证并确认目标位置。'
        self.deadline = None
        self.pending_person = None
        self.resume_patrol = False
        self.route_index = 0
        self.last_identity = {}
        self.last_unknown = 0

    def event(self, kind, **data):
        data.update(kind=kind, time=self.clock(), simulated=self.nav.simulated)
        self.log(data)

    def snapshot(self):
        with self.lock:
            return dict(state=self.state, person=self.person, target=self.target,
                        reply=self.reply, simulated=self.nav.simulated,
                        motion_enabled=not self.nav.simulated)

    def identify(self, person_id, simulated_input=False):
        with self.lock:
            if simulated_input and not self.nav.simulated:
                raise ValueError('实际导航模式不接受模拟身份事件')
            people = dict((p['id'], p) for p in self.config['people'])
            person = people.get(person_id)
            now = self.clock()
            if not person or not person.get('authorized'):
                self.invalidate_identity('出现未确认授权身份的人员')
                if now - self.last_unknown >= 10:
                    self.last_unknown = now
                    self.reply = '不是授权人员，请联系现场工作人员。'
                    self.event('unauthorized', person_id=person_id, simulated_input=simulated_input)
                return
            if self.state == 'WAITING_COMMAND' and self.person and self.person['id'] != person_id:
                self.invalidate_identity('交互人员发生变化')
            if self.state in ('IDENTIFYING', 'WAITING_COMMAND', 'NAVIGATING'):
                return
            if now - self.last_identity.get(person_id, -1e12) < self.config['identity_cooldown_seconds']:
                return
            self.last_identity[person_id] = now
            self.resume_patrol = self.state == 'PATROLLING'
            self.nav.cancel()
            self.pending_person = person
            self.state = 'IDENTIFYING'
            self.deadline = now + 5
            self.event('authorized_detected', person_id=person_id, simulated_input=simulated_input)

    def invalidate_identity(self, reason):
        with self.lock:
            if self.state in ('WAITING_COMMAND', 'IDENTIFYING'):
                self.nav.cancel()
                previous = self.person or self.pending_person
                if previous:
                    # Losing the face must not make a subsequent valid recognition
                    # wait through the greeting cooldown with an empty session.
                    self.last_identity.pop(previous['id'], None)
                self.state, self.person, self.pending_person = 'PAUSED', None, None
                self.deadline, self.resume_patrol = None, False
                self.reply = '当前交互身份需要重新确认。'
                self.event('identity_revoked', reason=reason)

    def touch(self, seconds=None):
        """页面仍活跃时给等待指令续期，避免固定 30 秒就超时。"""
        with self.lock:
            if self.state == 'WAITING_COMMAND' and self.person:
                self.deadline = self.clock() + (seconds or self.config.get('interaction_timeout_seconds', 300))

    def authorize(self, person_id):
        """浏览器会话已刷脸通过：直接授权中文交互，不依赖持续人脸检测。"""
        with self.lock:
            people = dict((p['id'], p) for p in self.config['people'])
            person = people.get(person_id)
            if not person or not person.get('authorized'):
                raise ValueError('不是授权人员')
            self.nav.cancel()
            self.person = person
            self.pending_person = None
            self.state = 'WAITING_COMMAND'
            self.deadline = self.clock() + self.config.get('interaction_timeout_seconds', 300)
            self.reply = '已确认%s，请说出您的指令。' % person['name']
            self.event('session_authorized', person_id=person_id)

    def dispatch(self, text):
        with self.lock:
            command = parse_command(text, self.config['places'])
            intent = command['intent']
            self.event('command', text=as_text(text), intent=intent)
            if intent == 'stop':
                self.nav.cancel()
                self.state, self.deadline, self.person = 'PAUSED', None, None
                self.pending_person, self.resume_patrol = None, False
                self.reply = '已取消当前任务。' if self.nav.simulated else '已请求取消，请确认机器人停车。'
            elif intent == 'help':
                self.reply = '我可以识别已录入人员、查询位置，并按指令前往已标定地点。'
            elif intent == 'greeting':
                self.reply = '你好，请问需要什么服务？导航服务需要先确认授权身份。'
            elif intent == 'location':
                pos = self.nav.position()
                self.reply = ('当前位置为地图坐标 x %.2f，y %.2f。' % (pos[0], pos[1])) if pos else '当前尚未取得可靠的实际地图位置。'
            elif self.state != 'WAITING_COMMAND' or self.person is None:
                self.reply = '请先完成授权人员身份识别，再下达服务指令。'
            elif intent == 'navigate':
                place = next(p for p in self.config['places'] if p['id'] == command['place_id'])
                try:
                    self.nav.send(place)
                    self.target = place['id']
                    self.state = 'NAVIGATING'
                    self.deadline = self.clock() + self.config['navigation_timeout_seconds']
                    self.reply = ('模拟前往' if self.nav.simulated else '正在前往') + place['name'] + '。'
                    self.event('navigation_started', place_id=place['id'])
                except Exception as exc:
                    self.reply = '导航未启动：' + as_text(exc)
                    self.event('navigation_rejected', reason=as_text(exc))
            elif intent == 'patrol':
                self.start_patrol()
            else:
                self.reply = '请说出一个明确地点，例如“去教室”，或询问我能提供什么服务。'
            return self.reply

    def navigate(self, place):
        with self.lock:
            if self.state != 'WAITING_COMMAND' or not self.person:
                raise ValueError('尚未确认停车与授权会话，请稍后再试')
            validate_pose(place)
            self.nav.send(place)
            self.target = place['id']
            self.state = 'NAVIGATING'
            self.deadline = self.clock() + self.config['navigation_timeout_seconds']
            self.reply = ('模拟前往' if self.nav.simulated else '正在前往') + place['name'] + '。'
            self.event('navigation_started', place_id=place['id'])

    def start_patrol(self):
        with self.lock:
            route = self.config.get('patrol_route', [])
            if not route:
                raise ValueError('尚未配置巡航路线')
            places = dict((p['id'], p) for p in self.config['places'])
            # 实际巡航必须预先验证整条路线，不能只检查第一个点。
            if not self.nav.simulated:
                for place_id in route:
                    validate_pose(places[place_id])
            self.nav.cancel()
            self.target = route[self.route_index % len(route)]
            self.nav.send(places[self.target])
            self.state, self.person, self.pending_person = 'PATROLLING', None, None
            self.deadline = self.clock() + self.config['navigation_timeout_seconds']
            self.reply = '模拟巡航已开始。' if self.nav.simulated else '巡航已开始。'
            self.event('patrol_started', place_id=self.target)

    def tick(self):
        with self.lock:
            now = self.clock()
            if self.state == 'IDENTIFYING':
                if self.nav.stopped():
                    self.person, self.pending_person = self.pending_person, None
                    self.state = 'WAITING_COMMAND'
                    self.deadline = now + self.config['interaction_timeout_seconds']
                    self.reply = '你好，' + self.person['name'] + '，请问需要什么服务？'
                    self.event('interaction_ready', person_id=self.person['id'])
                elif now >= self.deadline:
                    self.state, self.person, self.pending_person = 'FAULT', None, None
                    self.reply = '未确认停车，暂停交互，请现场检查。'
                    self.event('stop_not_confirmed')
                return
            if self.state in ('PATROLLING', 'NAVIGATING'):
                result = self.nav.poll()
                if result == 'succeeded':
                    self.event('navigation_succeeded', place_id=self.target)
                    if self.state == 'PATROLLING':
                        self.route_index += 1
                        self.start_patrol()
                    else:
                        self.reply = '模拟到达目标地点。' if self.nav.simulated else '已到达目标地点。'
                        self.state, self.person = 'IDLE', None
                        if self.resume_patrol:
                            self.resume_patrol = False
                            self.start_patrol()
                elif result in ('failed', 'cancelled') or (self.deadline and now >= self.deadline):
                    self.nav.cancel()
                    self.state, self.person = 'FAULT', None
                    self.reply = '导航未完成，已停止任务，请检查。'
                    self.event('navigation_failed', reason=result or 'timeout')
            elif self.state == 'WAITING_COMMAND' and now >= self.deadline:
                self.person = None
                self.state = 'IDLE'
                self.reply = '等待指令超时，交互已结束。'
                self.event('interaction_timeout')
                if self.resume_patrol:
                    self.resume_patrol = False
                    self.start_patrol()
