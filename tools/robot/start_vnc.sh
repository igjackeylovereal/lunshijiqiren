#!/bin/bash
# 在机器人上启动远程桌面（供笔记本 VNC Viewer 连接）
# 依赖： sudo apt-get install -y x11vnc xvfb

PORT=5900

if pgrep -x x11vnc >/dev/null 2>&1; then
    echo "x11vnc 已在运行，端口 $PORT"
    exit 0
fi

# 优先使用已存在的桌面会话 :0
if [ -e /tmp/.X11-unix/X0 ]; then
    DISP=:0
    echo "使用已有桌面会话 $DISP"
else
    if ! command -v Xvfb >/dev/null 2>&1; then
        echo "未安装 Xvfb：sudo apt-get install -y xvfb"
        exit 1
    fi
    DISP=:1
    echo "启动虚拟桌面 $DISP (1366x768)"
    Xvfb :1 -screen 0 1366x768x24 >/tmp/xvfb.log 2>&1 &
    sleep 1
fi

# 软件渲染：J1900 上没有独显时 rviz 更稳
export LIBGL_ALWAYS_SOFTWARE=1

nohup x11vnc -display "$DISP" -forever -shared -nopw -rfbport "$PORT" \
      >/tmp/x11vnc.log 2>&1 &

sleep 1
if pgrep -x x11vnc >/dev/null 2>&1; then
    echo "VNC 已启动：$DISP 端口 $PORT"
    echo "笔记本用 VNC Viewer 连接  $(hostname -I | awk '{print $1}'):$PORT"
    echo "首次连接如需密码，可改用：x11vnc -display $DISP -passwd 你的密码"
else
    echo "启动失败，查看 /tmp/x11vnc.log"
    tail -20 /tmp/x11vnc.log
fi
