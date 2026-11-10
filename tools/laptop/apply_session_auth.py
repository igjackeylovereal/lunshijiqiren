#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""让“任务与中文交互”不再依赖持续人脸检测。

效果：
  - 浏览器刷脸登录成功后，控制器直接获得该人员的交互授权（不必一直站在相机前）
  - 会话活跃期间暂停人脸检测（退出配置或 120 秒无操作后自动恢复）
  - 录入人脸样本时仍会临时恢复检测

用法：
    .\\console\\.venv\\Scripts\\python.exe console\\apply_session_auth.py --ip reinovo.local --dry-run
    .\\console\\.venv\\Scripts\\python.exe console\\apply_session_auth.py --ip reinovo.local
"""
import argparse
import os
import time

import paramiko

BASE = "/home/bobac2/bobac_practicum_ws/src/bobac_practicum"

AUTHORIZE = '''
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

'''


def patch_core(text):
    if "def authorize(self, person_id)" in text:
        return text, "already"
    anchor = "    def dispatch(self, text):"
    if anchor not in text:
        raise RuntimeError("core.py 找不到 dispatch()")
    return text.replace(anchor, AUTHORIZE.lstrip("\n") + anchor, 1), "patched"


def patch_app(text):
    if "session_active" in text:
        return text, "already"

    # 1) 初始化字段
    old = "        self.stopping = threading.Event()"
    new = ("        self.stopping = threading.Event()\n"
           "        self.last_session_activity = 0.0\n"
           "        self.session_idle_seconds = 120")
    if old not in text:
        raise RuntimeError("app.py 找不到 stopping 初始化")
    text = text.replace(old, new, 1)

    # 2) 相机会话暂停 + 授权辅助方法
    old = "    def start_thread(self, function):"
    helper = '''    def session_active(self):
        """配置页仍在使用（最近有接口请求）时，认为会话活跃。"""
        return (time.time() - self.last_session_activity) < self.session_idle_seconds

    def ensure_session_person(self, person):
        """把浏览器会话里已认证的人员直接写进交互状态机。"""
        current = self.controller.snapshot()['person']
        if current and current['id'] == person['id']:
            return
        try:
            self.controller.authorize(person['id'])
        except Exception as exc:
            self.log(dict(kind='session_authorize_failed', reason=as_text(exc), time=time.time()))

'''
    if old not in text:
        raise RuntimeError("app.py 找不到 start_thread")
    text = text.replace(old, helper + old, 1)

    # 3) 相机循环：会话活跃且不在录入时跳过人脸检测
    old = "                self.camera['frames'] += 1\n"
    pause = ('''                if self.session_active() and not self.enrollment:
                    # 已刷脸登录：暂停人脸检测，只保留画面预览
                    self.camera.update(paused_for_session=True, face_count=0, last_identity=None,
                                       guidance='已通过身份验证，人脸检测已暂停；退出配置或 120 秒无操作后恢复')
                    self.last_face_seen = time.time()
                    success, jpeg = self.cv2.imencode('.jpg', frame, [int(self.cv2.IMWRITE_JPEG_QUALITY), 75])
                    if success:
                        self.frame_jpeg = jpeg.tostring()
                    if self.runtime:
                        try:
                            self.runtime.publish_frame(frame)
                        except Exception:
                            pass
                    time.sleep(0.2)
                    continue
                self.camera['paused_for_session'] = False
''')
    if old not in text:
        raise RuntimeError("app.py 找不到 frames 计数")
    text = text.replace(old, old + pause, 1)

    # 4) /api/status：刷新活跃时间并授权会话人员
    old = ("        if path == '/api/status':\n"
           "            return self.respond(200, app.status())\n")
    new = ("        if path == '/api/status':\n"
           "            app.last_session_activity = time.time()\n"
           "            app.ensure_session_person(app.access.require(self.token()))\n"
           "            return self.respond(200, app.status())\n")
    if old not in text:
        raise RuntimeError("app.py 找不到 /api/status")
    text = text.replace(old, new, 1)

    # 5) POST：任何受保护操作都刷新活跃时间并确保授权
    old = "                person = app.access.require(self.token())\n"
    new = ("                person = app.access.require(self.token())\n"
           "                app.last_session_activity = time.time()\n"
           "                app.ensure_session_person(person)\n")
    if old not in text:
        raise RuntimeError("app.py 找不到 require(token)")
    text = text.replace(old, new, 1)

    # 6) 相机状态字典增加字段
    old2 = "'last_identity': None,"
    if old2 in text and "paused_for_session" not in text.split(old2)[0][-400:]:
        text = text.replace(old2, "'last_identity': None, 'paused_for_session': False,", 1)

    return text, "patched"


def patch_js(text):
    if "paused_for_session" in text:
        return text, "already"
    old = "let faceText=`画面内 ${s.camera.face_count} 张人脸`;"
    new = ("let faceText=s.camera.paused_for_session?'已通过身份验证，人脸检测已暂停'"
           ":`画面内 ${s.camera.face_count} 张人脸`;")
    if old not in text:
        return text, "skipped"
    return text.replace(old, new, 1), "patched"


def connect(ip, user, pwd):
    for i in range(6):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(ip, 22, user, pwd, timeout=12, look_for_keys=False, allow_agent=False)
            return c
        except Exception as e:
            print("retry", i, e)
            time.sleep(4)
    raise RuntimeError("ssh failed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="reinovo.local")
    ap.add_argument("--user", default="bobac2")
    ap.add_argument("--password", default="root")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = {
        "core": BASE + "/scripts/core.py",
        "app": BASE + "/scripts/app.py",
        "js": BASE + "/web/app.js",
    }
    c = connect(args.ip, args.user, args.password)
    sftp = c.open_sftp()

    texts = {}
    for k, remote in files.items():
        with sftp.open(remote, "rb") as f:
            texts[k] = f.read().decode("utf-8")

    texts["core"], r1 = patch_core(texts["core"])
    texts["app"], r2 = patch_app(texts["app"])
    texts["js"], r3 = patch_js(texts["js"])
    print("core:", r1, " app:", r2, " js:", r3)

    if args.dry_run:
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "patched_preview2")
        out = os.path.abspath(out)
        os.makedirs(out, exist_ok=True)
        for k, remote in files.items():
            p = os.path.join(out, os.path.basename(remote))
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(texts[k])
            print("预览:", p)
        print("dry-run 结束")
        return

    stamp = time.strftime("%Y%m%d_%H%M%S")
    for k, remote in files.items():
        c.exec_command("cp -n %s %s.bak_%s" % (remote, remote, stamp))[1].read()
        with sftp.open(remote, "wb") as f:
            f.write(texts[k].encode("utf-8"))
        print("写入", remote)

    print("重启应用 ...")
    cmd = ("pid=$(pgrep -f 'app.py --ros' | head -1); "
           "if [ -n \"$pid\" ]; then args=$(tr '\\0' ' ' < /proc/$pid/cmdline); "
           "kill $pid; sleep 2; kill -9 $pid 2>/dev/null; "
           "cd /home/bobac2/bobac_practicum_run; "
           "setsid nohup $args > app_console.log 2>&1 < /dev/null & sleep 7; "
           "ss -ltn | grep -q 8765 && echo APP_UP || { echo APP_DOWN; tail -n 10 app_console.log; }; "
           "else echo NO_APP; fi")
    _in, out, _ = c.exec_command(cmd, timeout=60, get_pty=True)
    print(out.read().decode("utf-8", "ignore").strip())

    _in, out, _ = c.exec_command(
        "curl -s -o /dev/null -w '/ %{http_code}\\n' http://127.0.0.1:8765/", timeout=20)
    print("验收:", out.read().decode("utf-8", "ignore").strip())

    sftp.close()
    c.close()


if __name__ == "__main__":
    main()
