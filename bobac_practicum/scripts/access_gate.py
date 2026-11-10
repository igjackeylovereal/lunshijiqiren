# -*- coding: utf-8 -*-
"""Browser sessions are granted only by fresh, stable camera observations."""
from __future__ import unicode_literals
import json
import os
import threading
import time
import uuid


class AccessGate(object):
    def __init__(self, people, clock=time.time, ttl=None, cache_path=None):
        self.people = dict((p['id'], p) for p in people if p.get('authorized'))
        self.clock, self.ttl = clock, ttl
        self.sessions = {}
        self.lock = threading.RLock()
        self.cache_path = cache_path
        self._load()

    def _load(self):
        if not self.cache_path or not os.path.isfile(self.cache_path):
            return
        try:
            with open(self.cache_path) as stream:
                data = json.load(stream)
            now = self.clock()
            for token, item in data.items():
                if item.get('person') and (item.get('expires') is None or item['expires'] > now):
                    self.sessions[token] = item
        except Exception:
            pass

    def _save(self):
        if not self.cache_path:
            return
        try:
            data = dict((k, v) for k, v in self.sessions.items() if v.get('person'))
            tmp = self.cache_path + '.tmp'
            with open(tmp, 'w') as stream:
                json.dump(data, stream)
            os.chmod(tmp, 0o600)
            try:
                os.rename(tmp, self.cache_path)
            except OSError:
                try:
                    os.remove(self.cache_path)
                except OSError:
                    pass
                os.rename(tmp, self.cache_path)
        except Exception:
            pass

    def begin(self):
        with self.lock:
            now = self.clock()
            self.sessions = dict((k, v) for k, v in self.sessions.items()
                                 if v['expires'] is None or v['expires'] > now)
            token = uuid.uuid4().hex + uuid.uuid4().hex
            self.sessions[token] = dict(started=now, expires=now+60, person=None,
                                        candidate=None, since=now, denied=False,
                                        page_used=False)
            return token

    def observe(self, person_id, valid_single_face, stable):
        denied = False
        with self.lock:
            now = self.clock()
            for session in self.sessions.values():
                if session['person'] or (session['expires'] is not None and session['expires'] <= now):
                    continue
                candidate = person_id if valid_single_face else None
                if not valid_single_face or not stable:
                    session.update(candidate=None, since=now)
                    continue
                key = candidate or 'unknown'
                if session['candidate'] != key:
                    session.update(candidate=key, since=now)
                if now-session['since'] < 2:
                    continue
                if candidate in self.people:
                    expires = None if self.ttl is None else now+self.ttl
                    session.update(person=self.people[candidate], expires=expires, denied=False)
                    self._save()
                elif not session['denied']:
                    session['denied'] = True
                    denied = True
        return denied

    def consume_page(self, token):
        """每次进入受保护页面都要求重新验证：一个会话只允许打开一次页面。"""
        with self.lock:
            session = self.sessions.get(token)
            if not session or not session.get('person'):
                return False
            if session.get('page_used'):
                return False
            session['page_used'] = True
            return True

    def status(self, token):
        with self.lock:
            session = self.sessions.get(token)
            if not session or (session['expires'] is not None and session['expires'] <= self.clock()):
                return dict(authenticated=False, expired=True, denied=False, person=None)
            return dict(authenticated=bool(session['person']), expired=False,
                        denied=session['denied'], person=session['person'], expires=session['expires'])

    def require(self, token):
        result = self.status(token)
        if not result['authenticated']:
            raise ValueError('请先完成人脸身份验证')
        return result['person']

    def logout(self, token):
        with self.lock:
            self.sessions.pop(token, None)
            self._save()
