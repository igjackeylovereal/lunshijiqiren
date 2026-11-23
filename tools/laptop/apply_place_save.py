#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新增：地图上选点→命名→保存为语音导航地点（“去<名称>”即可导航）。"""
import argparse
import os
import time

import paramiko

BASE = "/home/bobac2/bobac_practicum_ws/src/bobac_practicum"
APP = BASE + "/scripts/app.py"
HTML = BASE + "/web/index.html"
JS = BASE + "/web/modules.js"

ENDPOINT = '''            elif self.path == '/api/place/save_from_map':
                name = (data.get('name') or '').strip()
                if not name or len(name) > 20:
                    raise ValueError('地点名称需 1~20 个字')
                meta = app.map_metadata()
                if not meta.get('ready'):
                    raise ValueError('地图尚未加载，无法设定地点')
                if app.mapping:
                    raise ValueError('建图模式下不能设定导航地点')
                pose = pixel_goal(meta, data.get('u'), data.get('v'), data.get('yaw', 0))
                map_id = meta.get('map_id')
                with app.controller.lock:
                    places = app.config['places']
                    hit = [p for p in places if p.get('name') == name]
                    if hit:
                        target = hit[0]
                        target.update(pose=dict(x=pose[0], y=pose[1], yaw=pose[2]), map_id=map_id)
                        if name not in target.get('aliases', []):
                            target.setdefault('aliases', []).append(name)
                    else:
                        target = dict(id='place_%d' % (len(places) + 1), name=name,
                                      aliases=[name], map_id=map_id,
                                      pose=dict(x=pose[0], y=pose[1], yaw=pose[2]))
                        places.append(target)
                    save_json(app.args.config, app.config)
                app.log(dict(kind='place_saved', name=name, x=pose[0], y=pose[1],
                             map_id=map_id, time=time.time()))
                return self.respond(200, dict(ok=True, id=target['id'], name=name,
                                              x=pose[0], y=pose[1], yaw=pose[2]))
'''


def patch_app(text):
    if "/api/place/save_from_map" in text:
        return text, "already"
    anchor = "            elif self.path == '/api/save-place':"
    if anchor not in text:
        raise RuntimeError("找不到 save-place 分支")
    return text.replace(anchor, ENDPOINT + anchor, 1), "patched"


def patch_html(text):
    if "placeMode" in text:
        return text, "already"
    old = '<div class="row"><button id="listen">录音五秒并识别</button><button id="speak" class="secondary">播报当前回复</button></div>'
    new = (old + '<div class="row"><button id="placeMode" class="secondary">设定地点（地图选点并命名）</button>'
           '<span id="placeStatus" class="muted"></span></div>')
    if old not in text:
        raise RuntimeError("找不到语音按钮行")
    return text.replace(old, new, 1), "patched"


def patch_js(text):
    if "placeMode" in text:
        return text, "already"
    old = "let meta=null,point=null,rendered=null,busy=false;"
    new = "let meta=null,point=null,rendered=null,busy=false,placeMode=false;"
    if old in text:
        text = text.replace(old, new, 1)
    elif "let meta=null,point=null,rendered=null,busy=false,mode='goal';" in text:
        text = text.replace("let meta=null,point=null,rendered=null,busy=false,mode='goal';",
                            "let meta=null,point=null,rendered=null,busy=false,mode='goal',placeMode=false;", 1)
    else:
        raise RuntimeError("找不到状态变量")

    old = "canvas.onclick=e=>{if(!rendered)return;"
    new = ("canvas.onclick=e=>{if(!rendered)return;"
           "if(placeMode){const r=canvas.getBoundingClientRect();"
           "const u=Math.floor((e.clientX-r.left)*canvas.width/r.width);"
           "const v=Math.floor((e.clientY-r.top)*canvas.height/r.height);"
           "const name=(window.prompt('给这个地点起个名字（例如：教室）')||'').trim();"
           "if(!name){return}"
           "api('/api/place/save_from_map',{name,u,v,yaw:Number($('goalYaw').value)*Math.PI/180})"
           ".then(s=>{placeMode=false;$('placeMode').textContent='设定地点（地图选点并命名）';"
           "$('placeStatus').textContent=`已保存 ${s.name}：x ${s.x.toFixed(2)}, y ${s.y.toFixed(2)}`;"
           "tell('已保存地点 '+s.name+'，可直接说“去'+s.name+'”')})"
           ".catch(err=>{$('placeStatus').textContent=err.message});return;}")
    if old not in text:
        raise RuntimeError("找不到 canvas.onclick")
    text = text.replace(old, new, 1)

    anchor = "$('reloadMaps').onclick=load;"
    add = ("$('placeMode').onclick=()=>{placeMode=!placeMode;"
           "$('placeMode').textContent=placeMode?'取消设定地点':'设定地点（地图选点并命名）';"
           "$('placeStatus').textContent=placeMode?'请在地图上点选目标位置':'已取消';};")
    if anchor not in text:
        raise RuntimeError("找不到 reloadMaps 绑定")
    text = text.replace(anchor, add + anchor, 1)
    return text, "patched"


def connect(ip, tries=10):
    last = None
    for i in range(tries):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(ip, 22, "bobac2", "root", timeout=20, banner_timeout=30,
                      auth_timeout=30, look_for_keys=False, allow_agent=False)
            return c
        except Exception as e:
            last = e
            print("retry", i, str(e)[:70])
            time.sleep(8)
    raise last


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
        out = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "patched_place"))
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
