# -*- coding: utf-8 -*-
"""恢复：刷脸一次后，本次会话内进 /console、/mapping 不再重复验证。"""
import paramiko, time

REMOTE = "/home/bobac2/bobac_practicum_ws/src/bobac_practicum/scripts/app.py"
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("reinovo.local", 22, "bobac2", "root", timeout=12, look_for_keys=False, allow_agent=False)
sftp = c.open_sftp()
text = sftp.open(REMOTE, "rb").read().decode("utf-8")

old = ("        if path == '/console' or path == '/mapping':\n"
       "            # 每次进入受保护页面都必须重新完成人脸验证\n"
       "            if not app.access.consume_page(self.token()):\n"
       "                # 页面许可已用过（刷新/二次进入）：销毁会话，必须重新刷脸，避免登录页死循环\n"
       "                app.access.logout(self.token())\n"
       "                self.send_response(302)\n"
       "                self.send_header('Location', '/?next=' + path)\n"
       "                self.end_headers()\n"
       "                return\n")
new = ("        if path == '/console' or path == '/mapping':\n"
       "            # 刷脸一次后，本次会话内可自由进出配置/建图页\n"
       "            if not app.access.status(self.token())['authenticated']:\n"
       "                self.send_response(302)\n"
       "                self.send_header('Location', '/?next=' + path)\n"
       "                self.end_headers()\n"
       "                return\n")

if old not in text:
    raise SystemExit("未找到一次性页面许可代码块")
if new in text:
    print("已恢复")
else:
    text = text.replace(old, new, 1)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    c.exec_command("cp -n %s %s.bak_%s" % (REMOTE, REMOTE, stamp))[1].read()
    with sftp.open(REMOTE, "wb") as f:
        f.write(text.encode("utf-8"))
    print("已写入：会话内不再重复验证")
sftp.close()
c.close()

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("reinovo.local", 22, "bobac2", "root", timeout=12, look_for_keys=False, allow_agent=False)
cmd = ("ps -eo pid,comm,args | grep 'app.py --ros' | grep -v grep | awk '$2 ~ /^python/ {print $1}' | xargs -r kill; sleep 2; "
       "source /opt/ros/kinetic/setup.bash; source /home/bobac2/bobac_practicum_ws/devel/setup.bash; "
       "cd /home/bobac2/bobac_practicum_run; "
       "setsid nohup python -u /home/bobac2/bobac_practicum_ws/src/bobac_practicum/scripts/app.py "
       "--ros --auto-speech --allow-motion --port 8765 "
       "--config /home/bobac2/bobac_practicum_run/navigation_project_20261105.json "
       "> app_console.log 2>&1 < /dev/null & "
       "for i in $(seq 1 30); do ss -ltn | grep -q 8765 && break; sleep 1; done; "
       "ss -ltn | grep 8765 && echo APP_UP || { echo APP_DOWN; tail -n 10 app_console.log; }")
_in, out, _ = c.exec_command(cmd, timeout=90, get_pty=True)
print(out.read().decode("utf-8", "ignore"))
c.close()
