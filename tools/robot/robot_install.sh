#!/bin/bash
# 在机器人上执行：编译两个包并设置脚本权限
set -e

HIT=$(find "$HOME" /home /opt -maxdepth 4 -type d -name bobac2_base 2>/dev/null | head -1)
if [ -n "$HIT" ]; then
    WS=$(dirname "$(dirname "$HIT")")
else
    WS="$HOME/bobac2_ws"
fi

echo "==> 工作空间：$WS"
[ -d "$WS/src" ] || { echo "找不到 $WS/src"; exit 1; }

echo "==> 检查包"
[ -d "$WS/src/bobac2_face" ]      || { echo "缺少 bobac2_face"; exit 1; }
[ -d "$WS/src/practicum_manager" ] || { echo "缺少 practicum_manager"; exit 1; }

echo "==> 修复可执行权限"
chmod +x "$WS/src/bobac2_face/scripts/"*.py 2>/dev/null || true
chmod +x "$WS/src/practicum_manager/scripts/"*.py 2>/dev/null || true
chmod +x "$HOME/practicum.sh" 2>/dev/null || true

echo "==> 编译（J1900 用 -j2 更稳）"
cd "$WS"
catkin_make -j2

echo "==> 检查"
source "$WS/devel/setup.bash"
rospack find bobac2_face
rospack find practicum_manager
echo "practicum.sh: $(test -x "$HOME/practicum.sh" && echo OK || echo MISSING)"
echo "WS=$WS"
echo "ALL_OK"
