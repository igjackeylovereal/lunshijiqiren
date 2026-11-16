#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""建图键盘模式：长按持续移动（去掉 5 秒上限）+ 提高速度。"""
import argparse
import os
import time

import paramiko

IP_DEFAULT = "10.166.34.14"
PATH = "/home/bobac2/bobac_practicum_ws/src/bobac_practicum/scripts/mapping_control.py"


def patch(text):
    if "3600." in text and "(0.15, 0.)" in text:
        return text, "already"

    old = ("    velocities = dict(forward=(.06, 0.), backward=(-.04, 0.), left=(0., .18), right=(0., -.18))")
    new = ("    velocities = dict(forward=(.15, 0.), backward=(-.12, 0.), left=(0., .6), right=(0., -.6))")
    if old not in text:
        raise RuntimeError("找不到 velocities")
    text = text.replace(old, new, 1)

    old = "        self.direction = 'forward'\n        self.pulse_seconds = 5."
    new = ("        self.direction = 'forward'\n"
           "        self.pulse_seconds = 3600.\n"
           "        self.speed = .15")
    if old not in text:
        raise RuntimeError("找不到 pulse_seconds=5")
    text = text.replace(old, new, 1)

    old = "not 0 <= now-self.started < 5"
    new = "not 0 <= now-self.started < self.pulse_seconds"
    if old not in text:
        raise RuntimeError("找不到 5 秒上限判断")
    text = text.replace(old, new, 1)
    return text, "patched"


def connect(ip):
    for i in range(6):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(ip, 22, "bobac2", "root", timeout=15, look_for_keys=False, allow_agent=False)
            return c
        except Exception as e:
            print("retry", i, e)
            time.sleep(4)
    raise RuntimeError("ssh failed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=IP_DEFAULT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    c = connect(args.ip)
    sftp = c.open_sftp()
    text = sftp.open(PATH, "rb").read().decode("utf-8")
    text, state = patch(text)
    print("patch:", state)
    if args.dry_run:
        out = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "patched_teleop"))
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "mapping_control.py"), "w", encoding="utf-8", newline="") as f:
            f.write(text)
        print("预览:", out)
        sftp.close()
        c.close()
        return

    c.exec_command("cp -n %s %s.bak_%s" % (PATH, PATH, time.strftime("%Y%m%d_%H%M%S")))[1].read()
    with sftp.open(PATH, "wb") as f:
        f.write(text.encode("utf-8"))
    print("写入", PATH)
    sftp.close()
    c.close()

    c = connect(args.ip)
    cmd = ("ps -eo pid,comm,args | grep 'app.py --ros' | grep -v grep | awk '$2 ~ /^python/ {print $1}' | xargs -r kill; sleep 2; "
           "source /opt/ros/kinetic/setup.bash; source /home/bobac2/bobac_practicum_ws/devel/setup.bash; "
           "cd /home/bobac2/bobac_practicum_run; "
           "setsid nohup python -u /home/bobac2/bobac_practicum_ws/src/bobac_practicum/scripts/app.py "
           "--ros --auto-speech --mapping-teleop --mapping-keyboard --port 8765 "
           "--config /home/bobac2/bobac_practicum_run/navigation_project_20261105.json "
           "> app_console.log 2>&1 < /dev/null & "
           "for i in $(seq 1 30); do ss -ltn | grep -q 8765 && break; sleep 1; done; "
           "ss -ltn | grep 8765 && echo APP_UP || { echo APP_DOWN; tail -n 12 app_console.log; }")
    _in, out, _ = c.exec_command(cmd, timeout=90, get_pty=True)
    print(out.read().decode("utf-8", "ignore"))
    c.close()


if __name__ == "__main__":
    main()
