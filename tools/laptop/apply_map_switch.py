#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复：①地图选择真正生效（重启导航栈加载所选地图）②新建空白地图（生成 pgm/yaml）。"""
import argparse
import os
import time

import paramiko

BASE = "/home/bobac2/bobac_practicum_ws/src/bobac_practicum"
APP = BASE + "/scripts/app.py"
HTML = BASE + "/web/index.html"
JS = BASE + "/web/modules.js"
MODE_SH = "/home/bobac2/bobac_mode.sh"

NEW_MODE_SH = '''#!/bin/bash
# 用法: bobac_mode.sh <nav|mapping|static> [map.yaml]
MODE="$1"
MAP="$2"
sleep 2
bash /home/bobac2/bobac_practicum_ctl.sh stop  > /tmp/bobac_mode_switch.log 2>&1
sleep 2
if [ "$MODE" = "nav" ] && [ -n "$MAP" ]; then
  bash /home/bobac2/bobac_practicum_ctl.sh up nav "$MAP" >> /tmp/bobac_mode_switch.log 2>&1
else
  bash /home/bobac2/bobac_practicum_ctl.sh up "$MODE" >> /tmp/bobac_mode_switch.log 2>&1
fi
'''

CREATE = '''            if self.path == '/api/map/create':
                name = (data.get('name') or '').strip()
                if not name or len(name) > 40:
                    raise ValueError('地图名长度需在 1~40 字')
                for bad in '/\\\\:*?"<>| ':
                    if bad in name:
                        raise ValueError('地图名不能包含空格或 / \\\\ : * ? " < > |')
                try:
                    size = float(data.get('size', 20.0))
                except (TypeError, ValueError):
                    raise ValueError('地图尺寸必须是数字（米）')
                if not 5.0 <= size <= 60.0:
                    raise ValueError('地图尺寸需在 5~60 米之间')
                resolution = 0.05
                cells = int(round(size / resolution))
                directory = os.path.expanduser('~/bobac_practicum_run/maps')
                if not os.path.isdir(directory):
                    os.makedirs(directory, 0o700)
                pgm = os.path.join(directory, name + '.pgm')
                yml = os.path.join(directory, name + '.yaml')
                if os.path.exists(yml):
                    raise ValueError('同名地图已存在')
                header = 'P5\\n%d %d\\n255\\n' % (cells, cells)
                with open(pgm, 'wb') as stream:
                    stream.write(header.encode('ascii'))
                    stream.write(b'\\xcd' * (cells * cells))
                half = size / 2.0
                with open(yml, 'w') as stream:
                    stream.write('image: %s.pgm\\nresolution: %.3f\\norigin: [%.3f, %.3f, 0.0]\\n'
                                 'negate: 0\\noccupied_thresh: 0.65\\nfree_thresh: 0.196\\n'
                                 % (name, resolution, -half, -half))
                self.log(dict(kind='map_created', name=name, size=size, time=time.time()))
                return self.respond(200, dict(ok=True, id=name + '.yaml', size=size,
                                              cells=cells, message='已创建空白地图 %s（%.0f×%.0f 格）' % (name, cells, cells)))
'''


def patch_app(text):
    if "/api/map/create" in text:
        return text, "already"

    anchor = "            if self.path == '/api/maps/select':"
    if anchor not in text:
        raise RuntimeError("找不到 maps/select")
    text = text.replace(anchor, CREATE + anchor, 1)

    old = ("                app.selected_map = selected\n"
           "                app.log(dict(kind='map_selection_pending', map=selected['id'], time=time.time()))\n"
           "                return self.respond(200, dict(ok=True, applied=False,\n"
           "                    message='地图已选为待加载项；当前不会切换运行中的ROS地图，需在机器人联调时完成模式启动'))")
    new = ("                app.selected_map = selected\n"
           "                app.log(dict(kind='map_switch', map=selected['id'], time=time.time()))\n"
           "                subprocess.Popen(['bash', os.path.expanduser('~/bobac_mode.sh'), 'nav', selected['yaml']],\n"
           "                                 stdout=open(os.devnull, 'w'), stderr=subprocess.STDOUT,\n"
           "                                 preexec_fn=os.setsid)\n"
           "                return self.respond(200, dict(ok=True, applied=True, switching=True, wait_seconds=45,\n"
           "                    message='正在加载地图 %s，约 45 秒后页面自动刷新' % selected['id']))")
    if old not in text:
        raise RuntimeError("找不到 maps/select 旧实现")
    text = text.replace(old, new, 1)
    return text, "patched"


def patch_html(text):
    if "mapCreate" in text:
        return text, "already"
    old = '<button id="reloadMaps" class="secondary">刷新地图</button>'
    new = ('<button id="reloadMaps" class="secondary">刷新地图</button>'
           '<input id="newMapName2" placeholder="空白地图名" maxlength="40" style="width:120px">'
           '<input id="newMapSize" type="number" value="20" min="5" max="60" step="1" style="width:60px" title="边长(米)">'
           '<button id="mapCreate" class="secondary">新建空白地图</button>')
    if old not in text:
        raise RuntimeError("index.html 找不到刷新地图")
    return text.replace(old, new, 1), "patched"


def patch_js(text):
    if "mapCreate" in text:
        return text, "already"
    old = ("$('selectMap').onclick=async()=>{try{const s=await api('/api/maps/select',{id:$('mapList').value});"
           "$('mapSelection').textContent=s.message}catch(e){tell(e.message)}};")
    new = ("$('selectMap').onclick=async()=>{try{const s=await api('/api/maps/select',{id:$('mapList').value});"
           "$('mapSelection').textContent=s.message;if(s.switching){setTimeout(()=>location.reload(),(s.wait_seconds||45)*1000)}}"
           "catch(e){tell(e.message)}};"
           "$('mapCreate').onclick=async()=>{const name=($('newMapName2').value||'').trim();"
           "if(!name){tell('请填写空白地图名称');return}const size=Number($('newMapSize').value||20);"
           "try{const s=await api('/api/map/create',{name,size});tell(s.message);await load()}catch(e){tell(e.message)}};")
    if old not in text:
        raise RuntimeError("modules.js 找不到 selectMap 绑定")
    return text.replace(old, new, 1), "patched"


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
    ap.add_argument("--ip", default="10.166.34.14")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    c = connect(args.ip)
    sftp = c.open_sftp()
    texts = {}
    for key, remote in (("app", APP), ("html", HTML), ("js", JS)):
        texts[key] = sftp.open(remote, "rb").read().decode("utf-8")
    texts["app"], r1 = patch_app(texts["app"])
    texts["html"], r2 = patch_html(texts["html"])
    texts["js"], r3 = patch_js(texts["js"])
    print("app:", r1, "html:", r2, "js:", r3)

    if args.dry_run:
        out = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "patched_mapswitch"))
        os.makedirs(out, exist_ok=True)
        for key, name in (("app", "app.py"), ("html", "index.html"), ("js", "modules.js")):
            with open(os.path.join(out, name), "w", encoding="utf-8", newline="") as f:
                f.write(texts[key])
        print("预览:", out)
        sftp.close()
        c.close()
        return

    stamp = time.strftime("%Y%m%d_%H%M%S")
    for key, remote in (("app", APP), ("html", HTML), ("js", JS)):
        c.exec_command("cp -n %s %s.bak_%s" % (remote, remote, stamp))[1].read()
        with sftp.open(remote, "wb") as f:
            f.write(texts[key].encode("utf-8"))
        print("写入", remote)
    with sftp.open(MODE_SH, "wb") as f:
        f.write(NEW_MODE_SH.encode("utf-8"))
    sftp.chmod(MODE_SH, 0o755)
    print("写入", MODE_SH)
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
