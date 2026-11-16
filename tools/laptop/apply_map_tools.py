#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""地图页增强：设置初始位姿 + 新建地图。

- /api/initial_pose  把地图上点击的位置发布为 /initialpose（AMCL 重定位）
- /api/map/new       记录新地图名并切换到建图模式；建图页保存时用该名字
- 前端：地图区加“设目标点 / 设初始位姿”切换，确认按钮按模式执行；“新建地图”输入框+按钮
"""
import argparse
import os
import time

import paramiko

BASE = "/home/bobac2/bobac_practicum_ws/src/bobac_practicum"
APP = BASE + "/scripts/app.py"
HTML = BASE + "/web/index.html"
JS = BASE + "/web/modules.js"

PUB_INIT = '''        self.initial_pose_pub = None
        if self.runtime:
            try:
                from geometry_msgs.msg import PoseWithCovarianceStamped
                self.initial_pose_pub = self.runtime.rospy.Publisher(
                    '/initialpose', PoseWithCovarianceStamped, queue_size=1)
            except Exception:
                self.initial_pose_pub = None
'''

METHODS = '''    def set_initial_pose(self, pose):
        if self.initial_pose_pub is None:
            raise ValueError('ROS 未连接，无法设置初始位姿')
        import math
        from geometry_msgs.msg import PoseWithCovarianceStamped
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = self.config.get('map_frame', 'map')
        msg.header.stamp = self.runtime.rospy.Time.now()
        msg.pose.pose.position.x = float(pose[0])
        msg.pose.pose.position.y = float(pose[1])
        msg.pose.pose.orientation.z = math.sin(float(pose[2]) / 2.0)
        msg.pose.pose.orientation.w = math.cos(float(pose[2]) / 2.0)
        for _ in range(3):
            self.initial_pose_pub.publish(msg)
            time.sleep(0.1)
        self.log(dict(kind='initial_pose_set', x=pose[0], y=pose[1], yaw=pose[2], time=time.time()))

'''


def patch_app(text):
    if "/api/initial_pose" in text:
        return text, "already"

    anchor = "        self.last_session_activity = 0.0\n"
    if anchor not in text:
        raise RuntimeError("找不到 last_session_activity")
    text = text.replace(anchor, anchor + PUB_INIT, 1)

    anchor2 = "    def save_mapping_progress(self):"
    if anchor2 not in text:
        raise RuntimeError("找不到 save_mapping_progress")
    text = text.replace(anchor2, METHODS + anchor2, 1)

    # 保存地图时优先使用“新建地图”指定的名字
    old = "        prefix = directory + '/classroom_draft_' + time.strftime('%Y%m%d_%H%M%S')"
    new = ("        pending = os.path.join(self.data, 'pending_map.txt')\n"
           "        chosen = ''\n"
           "        if os.path.isfile(pending):\n"
           "            try:\n"
           "                chosen = open(pending).read().strip()\n"
           "                os.remove(pending)\n"
           "            except Exception:\n"
           "                chosen = ''\n"
           "        if chosen:\n"
           "            prefix = directory + '/' + chosen\n"
           "        else:\n"
           "            prefix = directory + '/classroom_draft_' + time.strftime('%Y%m%d_%H%M%S')")
    if old not in text:
        raise RuntimeError("找不到保存前缀")
    text = text.replace(old, new, 1)

    anchor3 = "            if self.path == '/api/mode':"
    block = '''            if self.path == '/api/initial_pose':
                meta = app.map_metadata()
                if not meta.get('ready'):
                    raise ValueError('地图尚未加载，无法设置初始位姿')
                pose = pixel_goal(meta, data.get('u'), data.get('v'), data.get('yaw', 0))
                app.set_initial_pose(pose)
                return self.respond(200, dict(ok=True, x=pose[0], y=pose[1], yaw=pose[2]))
            if self.path == '/api/map/new':
                name = (data.get('name') or '').strip()
                if not name or len(name) > 40:
                    raise ValueError('地图名长度需在 1~40 字')
                for bad in '/\\\\:*?"<>| ':
                    if bad in name:
                        raise ValueError('地图名不能包含空格或 / \\\\ : * ? " < > |')
                with open(os.path.join(app.data, 'pending_map.txt'), 'w') as stream:
                    stream.write(name)
                app.log(dict(kind='map_new_requested', name=name, time=time.time()))
                subprocess.Popen(['bash', os.path.expanduser('~/bobac_mode.sh'), 'mapping'],
                                 stdout=open(os.devnull, 'w'), stderr=subprocess.STDOUT,
                                 preexec_fn=os.setsid)
                return self.respond(200, dict(ok=True, switching=True, name=name, wait_seconds=45,
                                              message='正在切换到建图模式，建好后点保存即用此名字'))
'''
    if anchor3 not in text:
        raise RuntimeError("找不到 /api/mode")
    text = text.replace(anchor3, block + anchor3, 1)
    return text, "patched"


def patch_html(text):
    if "mapModeGoal" in text:
        return text, "already"
    old = '<button id="reloadMaps" class="secondary">刷新地图</button>'
    new = ('<button id="reloadMaps" class="secondary">刷新地图</button>'
           '<label><input type="radio" name="mapMode" id="mapModeGoal" value="goal" checked> 设目标点</label>'
           '<label><input type="radio" name="mapMode" id="mapModePose" value="pose"> 设初始位姿</label>')
    if old not in text:
        raise RuntimeError("index.html 找不到刷新地图按钮")
    text = text.replace(old, new, 1)

    old2 = '<button id="confirmGoal" disabled>确认目标并导航</button>'
    new2 = ('<button id="confirmGoal" disabled>确认目标并导航</button>'
            '<span class="row" style="display:inline-flex;gap:6px;margin-left:8px">'
            '<input id="newMapName" placeholder="新地图名称" maxlength="40" style="width:140px">'
            '<button id="newMap" class="secondary">新建地图</button></span>')
    if old2 not in text:
        raise RuntimeError("index.html 找不到确认按钮")
    text = text.replace(old2, new2, 1)
    return text, "patched"


def patch_js(text):
    if "mapModePose" in text:
        return text, "already"

    old = "let meta=null,point=null,rendered=null,busy=false;"
    new = "let meta=null,point=null,rendered=null,busy=false,mode='goal';"
    if old not in text:
        raise RuntimeError("modules.js 找不到状态变量")
    text = text.replace(old, new, 1)

    old = "ctx.strokeStyle='#d13232';"
    new = "ctx.strokeStyle=mode==='pose'?'#1f6feb':'#d13232';"
    text = text.replace(old, new, 1)

    old = "$('goalDetails').textContent=`目标地图坐标：x ${x.toFixed(2)} 米，y ${y.toFixed(2)} 米；朝向 ${$('goalYaw').value}°。`;"
    new = ("$('goalDetails').textContent=(mode==='pose'?'初始位姿':'目标')+`地图坐标：x ${x.toFixed(2)} 米，y ${y.toFixed(2)} 米；朝向 ${$('goalYaw').value}°。`;")
    if old not in text:
        raise RuntimeError("modules.js 找不到坐标提示")
    text = text.replace(old, new, 1)

    old = "$('confirmGoal').onclick=async()=>{if(!point)return;$('confirmGoal').disabled=true;try{const s=await api('/api/navigation/goal',{...point,yaw:Number($('goalYaw').value)*Math.PI/180});tell(s.simulated?'已提交模拟导航，不驱动机器人':'已提交实际导航目标');point=null}catch(e){tell(e.message)}finally{$('confirmGoal').disabled=!point}};"
    new = ("$('confirmGoal').onclick=async()=>{if(!point)return;$('confirmGoal').disabled=true;"
           "const yaw=Number($('goalYaw').value)*Math.PI/180;"
           "try{if(mode==='pose'){const s=await api('/api/initial_pose',{...point,yaw});tell(`初始位姿已设置为 x ${s.x.toFixed(2)}, y ${s.y.toFixed(2)}`)}"
           "else{const s=await api('/api/navigation/goal',{...point,yaw});tell(s.simulated?'已提交模拟导航，不驱动机器人':'已提交实际导航目标')}point=null}"
           "catch(e){tell(e.message)}finally{$('confirmGoal').disabled=!point}};")
    if old not in text:
        raise RuntimeError("modules.js 找不到确认按钮绑定")
    text = text.replace(old, new, 1)

    anchor = "$('goalYaw').oninput=()=>draw();"
    add = ("document.querySelectorAll('input[name=mapMode]').forEach(r=>r.onchange=()=>{mode=r.value;"
           "$('confirmGoal').textContent=mode==='pose'?'把选中点设为初始位姿':'确认目标并导航';draw()});"
           "$('newMap').onclick=async()=>{const name=($('newMapName').value||'').trim();if(!name){tell('请先填写新地图名称');return}"
           "try{const s=await api('/api/map/new',{name});tell(s.message||'正在切换到建图模式');setTimeout(()=>{location.href='/mapping'},(s.wait_seconds||45)*1000)}catch(e){tell(e.message)}};")
    if anchor not in text:
        raise RuntimeError("modules.js 找不到 goalYaw 绑定")
    text = text.replace(anchor, add + anchor, 1)
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
        out = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "patched_map"))
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
