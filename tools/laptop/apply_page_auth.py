#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给机器人上的 bobac_practicum 打“每次进入配置/导航页都要重新刷脸”补丁。

用法（在 D:\\课设 下，用启动台同一套环境）：
    .\\console\\.venv\\Scripts\\python.exe console\\apply_page_auth.py --ip 10.224.117.14
    .\\console\\.venv\\Scripts\\python.exe console\\apply_page_auth.py --ip 10.224.117.14 --dry-run

改动：
  1) access_gate.py  会话增加 page_used 标记 + consume_page()
  2) app.py          /console 与 /mapping 改为一次性页面许可，未认证/已用过 -> 302 到 /?next=<path>
  3) login.js        登录成功后跳回 next 指定的页面

脚本可重复执行：已打过补丁会自动跳过；改前会在机器人上留 .bak 备份。
"""
import argparse
import os
import sys
import time

import paramiko

BASE = "/home/bobac2/bobac_practicum_ws/src/bobac_practicum"
FILES = {
    "app": BASE + "/scripts/app.py",
    "gate": BASE + "/scripts/access_gate.py",
    "login": BASE + "/web/login.js",
}


def connect(ip, user, pwd, retries=6):
    last = None
    for i in range(retries):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(ip, 22, user, pwd, timeout=12, banner_timeout=25,
                      auth_timeout=25, look_for_keys=False, allow_agent=False)
            return c
        except Exception as e:
            last = e
            print("  连接重试 %d: %s" % (i, e))
            time.sleep(4)
    raise last


def patch_gate(text):
    if "def consume_page" in text:
        return text, "already"
    if "candidate=None, since=now, denied=False)" in text and "page_used" not in text:
        text = text.replace(
            "candidate=None, since=now, denied=False)",
            "candidate=None, since=now, denied=False,\n                                        page_used=False)")
    method = '''
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

'''
    marker = "    def status(self, token):"
    if marker not in text:
        raise RuntimeError("access_gate.py 结构不符，找不到 status()")
    text = text.replace(marker, method.lstrip("\n") + marker, 1)
    return text, "patched"


def patch_app(text):
    if "consume_page" in text:
        return text, "already"
    old = ("        if path == '/console' or path == '/mapping':\n"
           "            if not app.access.status(self.token())['authenticated']:\n"
           "                self.send_response(302)\n"
           "                self.send_header('Location', '/')\n"
           "                self.end_headers()\n"
           "                return\n")
    new = ("        if path == '/console' or path == '/mapping':\n"
           "            # 每次进入受保护页面都必须重新完成人脸验证\n"
           "            if not app.access.consume_page(self.token()):\n"
           "                # 页面许可已用过（刷新/二次进入）：销毁会话，必须重新刷脸，避免登录页死循环\n"
           "                app.access.logout(self.token())\n"
           "                self.send_response(302)\n"
           "                self.send_header('Location', '/?next=' + path)\n"
           "                self.end_headers()\n"
           "                return\n")
    if old not in text:
        raise RuntimeError("app.py 结构不符，找不到 /console 认证块")
    return text.replace(old, new, 1), "patched"


def patch_login(text):
    if "URLSearchParams" in text:
        return text, "already"
    if "location.replace('/console')" not in text:
        raise RuntimeError("login.js 结构不符，找不到跳转到 /console")
    text = text.replace("location.replace('/console')", "location.replace(next)")
    if "location.href='/console'" in text:
        text = text.replace("location.href='/console'", "location.href=next")
    anchor = "const $=id=>document.getElementById(id);"
    inject = anchor + "const next=(new URLSearchParams(location.search).get('next')||'/console');"
    if anchor in text:
        text = text.replace(anchor, inject, 1)
    else:
        text = "const next=(new URLSearchParams(location.search).get('next')||'/console');" + text
    return text, "patched"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="10.224.117.14")
    ap.add_argument("--user", default="bobac2")
    ap.add_argument("--password", default="root")
    ap.add_argument("--dry-run", action="store_true", help="只打印改动，不写回机器人")
    args = ap.parse_args()

    print("连接 %s ..." % args.ip)
    c = connect(args.ip, args.user, args.password)
    sftp = c.open_sftp()

    texts = {}
    for key, remote in FILES.items():
        with sftp.open(remote, "rb") as f:
            texts[key] = f.read().decode("utf-8")
        print("读取 %s (%d 字节)" % (remote, len(texts[key])))

    results = {}
    texts["gate"], results["gate"] = patch_gate(texts["gate"])
    texts["app"], results["app"] = patch_app(texts["app"])
    texts["login"], results["login"] = patch_login(texts["login"])

    for key in ("gate", "app", "login"):
        print("%-6s %s" % (key, results[key]))

    if args.dry_run:
        outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "patched_preview")
        outdir = os.path.abspath(outdir)
        os.makedirs(outdir, exist_ok=True)
        for key, remote in FILES.items():
            name = os.path.basename(remote)
            with open(os.path.join(outdir, name), "w", encoding="utf-8", newline="") as f:
                f.write(texts[key])
            print("预览写入", os.path.join(outdir, name))
        print("dry-run 结束，未改动机器人")
        return

    stamp = time.strftime("%Y%m%d_%H%M%S")
    for key, remote in FILES.items():
        _in, out, _ = c.exec_command("cp -n %s %s.bak_%s && echo ok" % (remote, remote, stamp), timeout=20)
        out.read()
        with sftp.open(remote, "wb") as f:
            f.write(texts[key].encode("utf-8"))
        print("已写入", remote)

    print("重启应用 ...")
    cmd = (
        "pid=$(pgrep -f 'app.py --ros' | head -1); "
        "if [ -n \"$pid\" ]; then "
        "  args=$(tr '\\0' ' ' < /proc/$pid/cmdline); "
        "  kill $pid; sleep 2; kill -9 $pid 2>/dev/null; "
        "  cd /home/bobac2/bobac_practicum_run; "
        "  setsid nohup $args > /home/bobac2/bobac_practicum_run/app_console.log 2>&1 < /dev/null & "
        "  sleep 6; ss -ltn | grep -q 8765 && echo APP_UP || echo APP_DOWN; "
        "else echo NO_APP; fi"
    )
    _in, out, err = c.exec_command(cmd, timeout=60, get_pty=True)
    print(out.read().decode("utf-8", "ignore").strip())

    # 简单验收：未带 Cookie 访问 /console 必须 302
    time.sleep(1)
    _in, out, _ = c.exec_command(
        "curl -s -o /dev/null -w '%{http_code} %{redirect_url}\\n' http://127.0.0.1:8765/console", timeout=20)
    print("/console 未认证响应:", out.read().decode("utf-8", "ignore").strip())
    _in, out, _ = c.exec_command(
        "curl -s -o /dev/null -w '%{http_code}\\n' http://127.0.0.1:8765/", timeout=20)
    print("/ 响应:", out.read().decode("utf-8", "ignore").strip())

    sftp.close()
    c.close()
    print("完成。")


if __name__ == "__main__":
    main()
