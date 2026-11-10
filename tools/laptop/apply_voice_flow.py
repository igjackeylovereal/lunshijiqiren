#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按《bobac2 使用文档》5.1“语音综合应用”替换语音识别逻辑。

保留：录音（机器人麦克风）、/aiui 识别、/tts 播报、网页按钮、人脸会话、导航栈。
替换：识别后的“意图处理”改为文档中的流程——
      唤醒“元宝”（元宝元宝）→ 切换模式（闲聊/控制/导航）→
      控制模式：前进/后退/左转/右转/停止；导航模式：“我要去<地点>”。
"""
import argparse
import os
import time

import paramiko

APP = "/home/bobac2/bobac_practicum_ws/src/bobac_practicum/scripts/app.py"

INIT = '''        self.voice_flow = {'awake': False, 'mode': 'chat', 'choosing': False, 'last': 0}
        self.voice_cmd_pub = None
        if self.runtime:
            try:
                from geometry_msgs.msg import Twist
                self.voice_cmd_pub = self.runtime.rospy.Publisher('/cmd_vel', Twist, queue_size=1)
            except Exception:
                self.voice_cmd_pub = None
'''

METHODS = '''    def _voice_move(self, linear, angular, seconds):
        """语音控制模式的一次短动作；导航进行中拒绝直接发速度。"""
        if self.voice_cmd_pub is None:
            return '底盘尚未就绪，无法执行动作。'
        if self.controller.snapshot()['state'] == 'NAVIGATING':
            return '正在导航，请先取消导航再手动控制。'
        try:
            from geometry_msgs.msg import Twist
        except Exception:
            return '缺少 geometry_msgs，无法执行动作。'

        def run():
            rate = self.runtime.rospy.Rate(10)
            end = time.time() + max(0.1, seconds)
            msg = Twist()
            msg.linear.x = linear
            msg.angular.z = angular
            while time.time() < end and not self.stopping.is_set():
                self.voice_cmd_pub.publish(msg)
                rate.sleep()
            self.voice_cmd_pub.publish(Twist())

        self.start_thread(run)
        return ''

    def voice_handle(self, text):
        """文档 5.1：先唤醒，再按模式处理（闲聊/控制/导航）。"""
        text = as_text(text).strip()
        flow = self.voice_flow
        now = time.time()
        if now - flow.get('last', 0) > 120:
            flow['awake'] = False
        flow['last'] = now

        if not flow['awake']:
            if u'元宝' in text:
                flow['awake'] = True
                return u'我在，请说指令。'
            return u'请先呼唤“元宝元宝”唤醒我。'

        if flow.get('choosing'):
            flow['choosing'] = False
            for key, name in ((u'闲聊', u'闲聊'), (u'控制', u'控制'), (u'导航', u'导航')):
                if key in text:
                    flow['mode'] = {'闲聊': 'chat', '控制': 'control', '导航': 'nav'}[name]
                    return u'已切换到%s模式。' % name
            return u'没有听清模式，请说闲聊模式、控制模式或导航模式。'

        if u'切换模式' in text or u'模式切换' in text:
            flow['choosing'] = True
            return u'请选择想要切换的模式：闲聊、控制或导航。'

        mode = flow.get('mode', 'chat')
        if mode == 'control':
            if any(w in text for w in [u'停止', u'停下', u'停']):
                err = self._voice_move(0, 0, 0.1)
                return err or u'已停车。'
            table = ((u'前进', 0.12, 0.0, 1.5), (u'后退', -0.10, 0.0, 1.5),
                     (u'左转', 0.0, 0.5, 1.2), (u'右转', 0.0, -0.5, 1.2))
            for word, linear, angular, seconds in table:
                if word in text:
                    err = self._voice_move(linear, angular, seconds)
                    return err or (u'执行%s。' % word)
            return u'控制模式请说前进、后退、左转、右转或停止。'

        if mode == 'nav':
            if any(w in text for w in [u'取消', u'停止']):
                self.controller.dispatch(u'停止')
                return u'已取消导航。'
            name = text
            for prefix in (u'我要去', u'我想去', u'带我去', u'去', u'到'):
                if prefix in name:
                    name = name.split(prefix, 1)[1]
                    break
            name = name.strip(u'，。, .！!')
            return self.controller.dispatch(name)

        return self.controller.dispatch(text)

'''


def patch(text):
    if "voice_handle" in text:
        return text, "already"
    anchor = "        self.last_session_activity = 0.0\n"
    if anchor not in text:
        raise RuntimeError("找不到 last_session_activity 初始化")
    text = text.replace(anchor, anchor + INIT, 1)

    anchor2 = "    def listen(self):"
    if anchor2 not in text:
        raise RuntimeError("找不到 listen()")
    text = text.replace(anchor2, METHODS + anchor2, 1)

    old = "                reply = self.controller.dispatch(text)\n"
    if old not in text:
        raise RuntimeError("listen 中找不到 dispatch 调用")
    text = text.replace(old, "                reply = self.voice_handle(text)\n", 1)
    return text, "patched"


def connect(ip):
    for i in range(6):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(ip, 22, "bobac2", "root", timeout=15, banner_timeout=25,
                      auth_timeout=25, look_for_keys=False, allow_agent=False)
            return c
        except Exception as e:
            print("retry", i, e)
            time.sleep(5)
    raise RuntimeError("ssh failed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="10.109.40.14")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    c = connect(args.ip)
    sftp = c.open_sftp()
    text = sftp.open(APP, "rb").read().decode("utf-8")
    text, state = patch(text)
    print("patch:", state)

    if args.dry_run:
        out = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "patched_voice"))
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "app.py"), "w", encoding="utf-8", newline="") as f:
            f.write(text)
        print("预览:", os.path.join(out, "app.py"))
        sftp.close()
        c.close()
        return

    c.exec_command("cp -n %s %s.bak_%s" % (APP, APP, time.strftime("%Y%m%d_%H%M%S")))[1].read()
    with sftp.open(APP, "wb") as f:
        f.write(text.encode("utf-8"))
    print("写入", APP)
    sftp.close()
    c.close()

    c = connect(args.ip)
    cmd = ("ps -eo pid,comm,args | grep 'app.py --ros' | grep -v grep | awk '$2 ~ /^python/ {print $1}' | xargs -r kill; sleep 2; "
           "source /opt/ros/kinetic/setup.bash; source /home/bobac2/bobac_practicum_ws/devel/setup.bash; "
           "cd /home/bobac2/bobac_practicum_run; "
           "setsid nohup python -u /home/bobac2/bobac_practicum_ws/src/bobac_practicum/scripts/app.py "
           "--ros --auto-speech --allow-motion --port 8765 "
           "--config /home/bobac2/bobac_practicum_run/navigation_project_20261105.json "
           "> app_console.log 2>&1 < /dev/null & "
           "for i in $(seq 1 30); do ss -ltn | grep -q 8765 && break; sleep 1; done; "
           "ss -ltn | grep 8765 && echo APP_UP || { echo APP_DOWN; tail -n 12 app_console.log; }")
    _in, out, _ = c.exec_command(cmd, timeout=90, get_pty=True)
    print(out.read().decode("utf-8", "ignore"))
    c.close()


if __name__ == "__main__":
    main()
