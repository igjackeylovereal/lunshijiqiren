#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网页内切换“建图 / 导航”模式，并在重启后保持登录（不用重复刷脸）。

改动：
  scripts/access_gate.py  会话持久化到 data/sessions.json（0600），重启后自动恢复
  scripts/app.py          AccessGate 传入缓存路径；新增 POST /api/mode
  web/index.html          地图区增加两个切换按钮
  web/app.js              按钮绑定：POST /api/mode -> 等待 -> 跳转对应页面
  ~/bobac_mode.sh         真正执行 stop + up <mode>

用法：
    .\\console\\.venv\\Scripts\\python.exe console\\apply_modes.py --ip reinovo.local --dry-run
    .\\console\\.venv\\Scripts\\python.exe console\\apply_modes.py --ip reinovo.local
"""
import argparse
import os
import time

import paramiko

BASE = "/home/bobac2/bobac_practicum_ws/src/bobac_practicum"

MODE_SH = '''#!/bin/bash
# 网页“切换模式”调用：先停旧栈，再按目标模式启动
MODE="$1"
sleep 2
bash /home/bobac2/bobac_practicum_ctl.sh stop  > /tmp/bobac_mode_switch.log 2>&1
sleep 2
bash /home/bobac2/bobac_practicum_ctl.sh up "$MODE" >> /tmp/bobac_mode_switch.log 2>&1
'''


def patch_gate(text):
    if "cache_path" in text:
        return text, "already"
    text = text.replace(
        "import threading\nimport time\nimport uuid",
        "import json\nimport os\nimport threading\nimport time\nimport uuid", 1)
    text = text.replace(
        "    def __init__(self, people, clock=time.time, ttl=None):\n"
        "        self.people = dict((p['id'], p) for p in people if p.get('authorized'))\n"
        "        self.clock, self.ttl = clock, ttl\n"
        "        self.sessions = {}\n"
        "        self.lock = threading.RLock()\n",
        "    def __init__(self, people, clock=time.time, ttl=None, cache_path=None):\n"
        "        self.people = dict((p['id'], p) for p in people if p.get('authorized'))\n"
        "        self.clock, self.ttl = clock, ttl\n"
        "        self.sessions = {}\n"
        "        self.lock = threading.RLock()\n"
        "        self.cache_path = cache_path\n"
        "        self._load()\n\n"
        "    def _load(self):\n"
        "        if not self.cache_path or not os.path.isfile(self.cache_path):\n"
        "            return\n"
        "        try:\n"
        "            with open(self.cache_path) as stream:\n"
        "                data = json.load(stream)\n"
        "            now = self.clock()\n"
        "            for token, item in data.items():\n"
        "                if item.get('person') and (item.get('expires') is None or item['expires'] > now):\n"
        "                    self.sessions[token] = item\n"
        "        except Exception:\n"
        "            pass\n\n"
        "    def _save(self):\n"
        "        if not self.cache_path:\n"
        "            return\n"
        "        try:\n"
        "            data = dict((k, v) for k, v in self.sessions.items() if v.get('person'))\n"
        "            tmp = self.cache_path + '.tmp'\n"
        "            with open(tmp, 'w') as stream:\n"
        "                json.dump(data, stream)\n"
        "            os.chmod(tmp, 0o600)\n"
        "            try:\n"
        "                os.rename(tmp, self.cache_path)\n"
        "            except OSError:\n"
        "                try:\n"
        "                    os.remove(self.cache_path)\n"
        "                except OSError:\n"
        "                    pass\n"
        "                os.rename(tmp, self.cache_path)\n"
        "        except Exception:\n"
        "            pass\n", 1)
    text = text.replace(
        "                    session.update(person=self.people[candidate], expires=expires, denied=False)",
        "                    session.update(person=self.people[candidate], expires=expires, denied=False)\n"
        "                    self._save()", 1)
    text = text.replace(
        "    def logout(self, token):\n        with self.lock:\n            self.sessions.pop(token, None)",
        "    def logout(self, token):\n        with self.lock:\n            self.sessions.pop(token, None)\n            self._save()", 1)
    return text, "patched"


def patch_app(text):
    if "/api/mode" in text:
        return text, "already"
    old = '        self.access = AccessGate(self.config["people"])'
    new = ('        self.access = AccessGate(self.config["people"],\n'
           '                                cache_path=os.path.join(self.data, "sessions.json"))')
    if old not in text:
        raise RuntimeError("app.py 找不到 AccessGate 构造")
    text = text.replace(old, new, 1)

    anchor = "            if self.path == '/api/mapping/control':"
    block = '''            if self.path == '/api/mode':
                target = data.get('mode')
                if target not in ('nav', 'mapping'):
                    raise ValueError('只支持 nav 或 mapping')
                current = 'mapping' if app.mapping else ('nav' if app.args.allow_motion else 'static')
                if target == current:
                    return self.respond(200, dict(ok=True, mode=current, wait_seconds=0,
                                                  message='已经是该模式'))
                subprocess.Popen(['bash', os.path.expanduser('~/bobac_mode.sh'), target],
                                 stdout=open(os.devnull, 'w'), stderr=subprocess.STDOUT,
                                 preexec_fn=os.setsid)
                app.log(dict(kind='mode_switch', target=target, time=time.time()))
                return self.respond(200, dict(ok=True, mode=target, wait_seconds=45,
                                              message='正在切换模式'))
'''
    if anchor not in text:
        raise RuntimeError("app.py 找不到 mapping/control 分支")
    text = text.replace(anchor, block + anchor, 1)
    return text, "patched"


def patch_html(text):
    if "switchMapping" in text:
        return text, "already"
    old = '<a href="/mapping">进入建图控制</a></div>'
    new = ('<button id="switchMapping" class="secondary">切换到建图模式</button>'
           '<button id="switchNav" class="secondary">切换到导航模式</button>'
           '<a href="/mapping">进入建图控制</a></div>')
    if old not in text:
        raise RuntimeError("index.html 找不到建图链接")
    return text.replace(old, new, 1), "patched"


def patch_js(text):
    if "switchMode" in text:
        return text, "already"
    anchor = "async function refresh(){"
    block = '''async function switchMode(mode){try{const r=await fetch('/api/mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})});const j=await r.json();if(!r.ok)throw Error(j.error||'切换失败');message(j.message||'正在切换模式');setTimeout(()=>{location.href=mode==='mapping'?'/mapping':'/console'},(j.wait_seconds||45)*1000)}catch(e){message(e.message)}}
bind('switchMapping',()=>switchMode('mapping'));
bind('switchNav',()=>switchMode('nav'));
'''
    if anchor not in text:
        raise RuntimeError("app.js 找不到 refresh()")
    return text.replace(anchor, block + anchor, 1), "patched"


def connect(ip):
    for i in range(6):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(ip, 22, "bobac2", "root", timeout=12, look_for_keys=False, allow_agent=False)
            return c
        except Exception as e:
            print("retry", i, e)
            time.sleep(4)
    raise RuntimeError("ssh failed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="reinovo.local")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = {
        "gate": BASE + "/scripts/access_gate.py",
        "app": BASE + "/scripts/app.py",
        "html": BASE + "/web/index.html",
        "js": BASE + "/web/app.js",
    }
    c = connect(args.ip)
    sftp = c.open_sftp()
    texts = {}
    for k, remote in files.items():
        with sftp.open(remote, "rb") as f:
            texts[k] = f.read().decode("utf-8")

    texts["gate"], r1 = patch_gate(texts["gate"])
    texts["app"], r2 = patch_app(texts["app"])
    texts["html"], r3 = patch_html(texts["html"])
    texts["js"], r4 = patch_js(texts["js"])
    print("gate:", r1, "app:", r2, "html:", r3, "js:", r4)

    if args.dry_run:
        out = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "patched_mode"))
        os.makedirs(out, exist_ok=True)
        for k, remote in files.items():
            with open(os.path.join(out, os.path.basename(remote)), "w", encoding="utf-8", newline="") as f:
                f.write(texts[k])
        print("预览目录:", out)
        return

    stamp = time.strftime("%Y%m%d_%H%M%S")
    for k, remote in files.items():
        c.exec_command("cp -n %s %s.bak_%s" % (remote, remote, stamp))[1].read()
        with sftp.open(remote, "wb") as f:
            f.write(texts[k].encode("utf-8"))
        print("写入", remote)

    with sftp.open("/home/bobac2/bobac_mode.sh", "wb") as f:
        f.write(MODE_SH.encode("utf-8"))
    sftp.chmod("/home/bobac2/bobac_mode.sh", 0o755)
    print("写入 /home/bobac2/bobac_mode.sh")

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
