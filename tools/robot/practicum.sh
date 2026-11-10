#!/bin/bash
# practicum.sh - bobac 实训一键控制（无图形界面）
#
# 用法：
#   bash ~/practicum.sh check                 # 系统体检
#   bash ~/practicum.sh map                   # 模式A：开始建图
#   bash ~/practicum.sh save [名字]           # 保存地图（默认 lab）
#   bash ~/practicum.sh stopmap               # 结束建图
#   bash ~/practicum.sh run                   # 模式B：有图，一键启动全部
#   bash ~/practicum.sh stop                  # 停止全部
#   bash ~/practicum.sh status                # 查看状态
#   bash ~/practicum.sh move 0.15 0 1.0       # 前进 1 秒
#   bash ~/practicum.sh pose 0 0 0            # 设定初始位姿 x y yaw
#   bash ~/practicum.sh goto 会议室            # 前往地点（按 position_info.txt）
#   bash ~/practicum.sh say "你好"             # 语音播报
#   bash ~/practicum.sh enroll 张三 30         # 采集人脸
#   bash ~/practicum.sh snap                  # 抓一帧存 /tmp/snap.jpg
#   bash ~/practicum.sh log [名字] [行数]      # 查看后台日志

set -u

# 自动定位工作空间（root 登录时 ~ 可能不是 reinovo 的家目录）
detect_ws() {
    local hit
    hit=$(find "$HOME" /home /opt -maxdepth 4 -type d -name bobac2_base 2>/dev/null | head -1)
    if [ -n "$hit" ]; then
        dirname "$(dirname "$hit")"
        return
    fi
    echo "$HOME/bobac2_ws"
}
WS=$(detect_ws)

RUN="$HOME/.ros/practicum"
MAPS="$WS/src/bobac2_navigation/maps"
MAP_NAME="${MAP_NAME:-lab}"
mkdir -p "$RUN" "$MAPS" 2>/dev/null

[ -f /opt/ros/kinetic/setup.bash ] && source /opt/ros/kinetic/setup.bash
[ -f "$WS/devel/setup.bash" ] && source "$WS/devel/setup.bash"

pf() { echo "$RUN/$1.pid"; }

is_running() {
    local f
    f=$(pf "$1")
    [ -f "$f" ] && kill -0 "$(cat "$f")" 2>/dev/null
}

start_bg() {
    local name=$1
    shift
    if is_running "$name"; then
        echo "[$name] 已在运行 (pid $(cat "$(pf "$name")"))"
        return 0
    fi
    setsid "$@" > "$RUN/$name.log" 2>&1 < /dev/null &
    echo $! > "$(pf "$name")"
    echo "[$name] 已启动 pid $! 日志 $RUN/$name.log"
}

stop_bg() {
    local name=$1 f pid i
    f=$(pf "$name")
    if [ ! -f "$f" ]; then
        echo "[$name] 未运行"
        return 0
    fi
    pid=$(cat "$f")
    kill -INT -"$pid" 2>/dev/null || kill -INT "$pid" 2>/dev/null
    for i in 1 2 3 4 5; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
    done
    kill -9 -"$pid" 2>/dev/null
    rm -f "$f"
    echo "[$name] 已停止"
}

slam_launch_file() { echo "$WS/src/bobac2_slam/launch/bobac2_slam.launch"; }

case "${1:-help}" in

check)
    echo "===== 系统 ====="
    hostname
    hostname -I
    echo "ROS: $(rosversion -d 2>/dev/null)"
    echo "MASTER: ${ROS_MASTER_URI:-未设置}"
    echo
    echo "===== 节点 ====="
    rosnode list 2>/dev/null
    echo
    echo "===== 服务（语音）====="
    rosservice list 2>/dev/null | grep -E "/(collect|awake|aiui|tts|voice_nav)$" || echo "语音服务未启动"
    echo
    echo "===== 关键话题频率 ====="
    for t in /scan /car_data /practicum/camera/image_raw; do
        printf "%-34s" "$t"
        out=$(timeout 3 rostopic hz "$t" 2>/dev/null | tail -2 | head -1)
        if [ -z "$out" ]; then echo "(无数据)"; else echo "$out"; fi
    done
    echo
    echo "===== 地图 ====="
    if [ -f "$MAPS/$MAP_NAME.yaml" ]; then
        ls -l "$MAPS/$MAP_NAME.yaml"
    else
        echo "无地图：$MAPS/$MAP_NAME.yaml"
    fi
    echo
    echo "===== 串口 ====="
    ls /dev/ttyUSB* 2>/dev/null || echo "无 ttyUSB 设备"
    ;;
    
status)
    echo "== 进程 =="
    for n in slam full enroll; do
        if is_running "$n"; then echo "$n: 运行中 pid $(cat "$(pf "$n")")"; else echo "$n: 未运行"; fi
    done
    echo "== 节点 =="
    rosnode list 2>/dev/null | tr '\n' ' '
    echo
    echo "== 地图 =="
    ls -l "$MAPS/$MAP_NAME.yaml" 2>/dev/null || echo "无地图"
    echo "== 频率 =="
    for t in /scan /car_data /cmd_vel; do
        printf "%-16s" "$t"
        timeout 2 rostopic hz "$t" 2>/dev/null | tail -2 | head -1
    done
    ;;

map)
    echo "== 模式A：建图 =="
    if [ ! -f "$(slam_launch_file)" ]; then
        echo "找不到 $(slam_launch_file)"
        exit 1
    fi
    stop_bg full >/dev/null 2>&1
    stop_bg slam >/dev/null 2>&1
    sleep 1
    ARG=""
    if grep -q 'name="open_rviz"' "$(slam_launch_file)" 2>/dev/null; then
        ARG="open_rviz:=false"
    fi
    start_bg slam roslaunch bobac2_slam bobac2_slam.launch $ARG
    echo "等待 5 秒后检查 /scan ..."
    sleep 5
    timeout 3 rostopic hz /scan 2>/dev/null | tail -2 | head -1 || echo "/scan 暂无数据"
    ;;

save)
    echo "== 保存地图 =="
    if ! is_running slam; then
        echo "建图未运行，无法保存（先执行 map）"
        exit 1
    fi
    NAME="${2:-$MAP_NAME}"
    timeout 40 rosrun map_server map_saver -f "$MAPS/$NAME"
    if [ -f "$MAPS/$NAME.yaml" ]; then
        ln -sf "$MAPS/$NAME.yaml" "$MAPS/$MAP_NAME.yaml" 2>/dev/null
        sed -i -E "s#maps/[A-Za-z0-9_]+\.yaml#maps/$NAME.yaml#" \
            "$WS/src/bobac2_navigation/launch/map_server.launch" 2>/dev/null
        echo "已保存：$MAPS/$NAME.yaml"
        echo "MAPFILE=$MAPS/$NAME"
        grep -E "resolution|origin" "$MAPS/$NAME.yaml" 2>/dev/null
    else
        echo "保存失败"
        exit 1
    fi
    ;;

stopmap)
    stop_bg slam
    ;;

run)
    echo "== 模式B：有图，启动全流程 =="
    if [ ! -f "$MAPS/$MAP_NAME.yaml" ]; then
        echo "没有地图：$MAPS/$MAP_NAME.yaml"
        echo "请先执行：bash ~/practicum.sh map 建图后 save"
        exit 2
    fi
    stop_bg slam >/dev/null 2>&1
    stop_bg full >/dev/null 2>&1
    sleep 1
    HAS_BASE=false
    HAS_LIDAR=false
    rosnode list 2>/dev/null | grep -q "/bobac2_base_node" && HAS_BASE=true
    rosnode list 2>/dev/null | grep -q "/rplidarNode" && HAS_LIDAR=true
    start_bg full roslaunch practicum_manager practicum_full.launch \
        start_base:=$([ "$HAS_BASE" = true ] && echo false || echo true) \
        start_lidar:=$([ "$HAS_LIDAR" = true ] && echo false || echo true)
    echo "等待 8 秒后检查服务 ..."
    sleep 8
    rosservice list 2>/dev/null | grep -E "/(collect|aiui|tts|voice_nav)$" || true
    rosnode list 2>/dev/null | tr '\n' ' '
    echo
    ;;

stop)
    stop_bg full
    stop_bg slam
    stop_bg enroll
    pkill -f "practicum_manager.py" 2>/dev/null
    echo "已全部停止"
    ;;

move)
    LX="${2:-0.15}"
    AZ="${3:-0}"
    DUR="${4:-1.0}"
    if ! rosnode list 2>/dev/null | grep -q "/bobac2_base_node"; then
        echo "底盘未启动"
        exit 1
    fi
    timeout "${DUR}s" rostopic pub -r 10 /cmd_vel geometry_msgs/Twist \
        "{linear: {x: $LX}, angular: {z: $AZ}}" >/dev/null 2>&1
    rostopic pub -1 /cmd_vel geometry_msgs/Twist \
        "{linear: {x: 0.0}, angular: {z: 0.0}}" >/dev/null 2>&1
    echo "移动完成 linear=$LX angular=$AZ ${DUR}s"
    ;;

pose)
    X="${2:-0}"
    Y="${3:-0}"
    YAW="${4:-0}"
    python - "$X" "$Y" "$YAW" <<'PY'
import sys, math, rospy
from geometry_msgs.msg import PoseWithCovarianceStamped
x, y, yaw = map(float, sys.argv[1:4])
rospy.init_node('practicum_pose', anonymous=True)
p = PoseWithCovarianceStamped()
p.header.frame_id = 'map'
p.header.stamp = rospy.Time.now()
p.pose.pose.position.x = x
p.pose.pose.position.y = y
p.pose.pose.orientation.z = math.sin(yaw / 2.0)
p.pose.pose.orientation.w = math.cos(yaw / 2.0)
pub = rospy.Publisher('/initialpose', PoseWithCovarianceStamped, queue_size=1)
rospy.sleep(0.6)
pub.publish(p)
rospy.sleep(0.4)
print('initial pose: %.2f %.2f %.2f' % (x, y, yaw))
PY
    ;;

goto)
    NAME="${2:-}"
    if [ -z "$NAME" ]; then
        echo "用法: goto <地点名>"
        exit 1
    fi
    PINFO="$HOME/.ros/source/voice_nav/position_info.txt"
    [ -f "$PINFO" ] || PINFO="$WS/src/bobac2_audio/voice_nav/config/voice_nav/position_info.txt"
    LINE=$(grep -m1 "^${NAME}[[:space:]]" "$PINFO" 2>/dev/null)
    if [ -z "$LINE" ]; then
        echo "找不到地点: $NAME"
        echo "可用地点:"
        awk '{print "  " $1}' "$PINFO" 2>/dev/null
        exit 2
    fi
    set -- $LINE
    python - "$1" "$2" "$3" "$6" <<'PY'
import sys, math, rospy
from geometry_msgs.msg import PoseStamped
name = sys.argv[1]
x, y, yaw = float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
rospy.init_node('practicum_goto', anonymous=True)
g = PoseStamped()
g.header.frame_id = 'map'
g.header.stamp = rospy.Time.now()
g.pose.position.x = x
g.pose.position.y = y
g.pose.orientation.z = math.sin(yaw / 2.0)
g.pose.orientation.w = math.cos(yaw / 2.0)
pub = rospy.Publisher('/move_base_simple/goal', PoseStamped, queue_size=1)
rospy.sleep(0.6)
pub.publish(g)
rospy.sleep(0.4)
print('goal sent: %s (%.2f, %.2f, %.2f)' % (name, x, y, yaw))
PY
    ;;

say)
    TEXT="${*:2}"
    if [ -z "$TEXT" ]; then
        echo "用法: say <要说的话>"
        exit 1
    fi
    OUT=$(rosservice call /tts "$TEXT" 2>&1)
    echo "$OUT"
    F=$(echo "$OUT" | sed -n 's/.*voice_file: *"\(.*\)".*/\1/p' | head -1)
    if [ -n "$F" ] && [ -f "$F" ]; then
        aplay -q "$F" &
        echo "playing $F"
    fi
    ;;

enroll)
    NM="${2:-}"
    CNT="${3:-30}"
    if [ -z "$NM" ]; then
        echo "用法: enroll <姓名> [张数]"
        exit 1
    fi
    start_bg enroll rosrun bobac2_face face_enroll.py _name:="$NM" _count:="$CNT"
    ;;

snap)
    OUT="${2:-/tmp/snap.jpg}"
    timeout 20 rosrun practicum_manager snap.py _out:="$OUT" >/dev/null 2>&1
    if [ -f "$OUT" ]; then
        echo "$OUT"
    else
        echo "抓图失败（相机话题是否有数据？）"
        exit 1
    fi
    ;;

log)
    NAME="${2:-full}"
    LINES="${3:-80}"
    tail -n "$LINES" "$RUN/$NAME.log" 2>/dev/null || echo "没有日志: $RUN/$NAME.log"
    ;;

places)
    PINFO="$HOME/.ros/source/voice_nav/position_info.txt"
    [ -f "$PINFO" ] || PINFO="$WS/src/bobac2_audio/voice_nav/config/voice_nav/position_info.txt"
    awk 'NF>=6 && $1 !~ /^#/ {print $1}' "$PINFO" 2>/dev/null
    ;;

*)
    sed -n '2,20p' "$0"
    ;;
esac
