#!/bin/bash
# bobac_practicum_ctl.sh - 从笔记本远程管理机器人上的实训运行栈
#
# 用法:
#   bash ~/bobac_practicum_ctl.sh status
#   bash ~/bobac_practicum_ctl.sh up nav [map.yaml] [x y yaw]
#   bash ~/bobac_practicum_ctl.sh up mapping
#   bash ~/bobac_practicum_ctl.sh up static
#   bash ~/bobac_practicum_ctl.sh stop            # 停应用+launch，保留 roscore
#   bash ~/bobac_practicum_ctl.sh stop --all      # 连 roscore 一起停
#   bash ~/bobac_practicum_ctl.sh save-map NAME
#   bash ~/bobac_practicum_ctl.sh maps
#   bash ~/bobac_practicum_ctl.sh log app|nav 60
set +u

WS=/home/bobac2/bobac_practicum_ws
FWS=/home/bobac2/bobac2_ws
RUN=/home/bobac2/bobac_practicum_run
MAPDIR=$RUN/maps
APP=$WS/src/bobac_practicum/scripts/app.py
PORT=8765

source /opt/ros/kinetic/setup.bash 2>/dev/null
[ -f "$FWS/devel/setup.bash" ] && source "$FWS/devel/setup.bash"
[ -f "$WS/devel/setup.bash" ] && source "$WS/devel/setup.bash"

ros_up()   { pgrep -f "rosmaster --core" >/dev/null 2>&1; }
app_up()   { pgrep -f "app.py --ros" >/dev/null 2>&1; }
app_pid()  { pgrep -f "app.py --ros" 2>/dev/null | head -1; }
port_up()  { ss -ltn 2>/dev/null | grep -q "127.0.0.1:$PORT"; }
nav_up()   { pgrep -f "navigation.launch" >/dev/null 2>&1; }
map_up()   { pgrep -f "mapping.launch" >/dev/null 2>&1; }
static_up(){ pgrep -f "static.launch" >/dev/null 2>&1; }
voice_up() { pgrep -f "voice_services.launch" >/dev/null 2>&1; }

wait_for() {  # wait_for <seconds> <cmd...>
    local n=$1; shift
    local i=0
    while [ $i -lt "$n" ]; do
        "$@" && return 0
        sleep 1; i=$((i+1))
    done
    return 1
}

start_ros() {
    ros_up && { echo "roscore: 已在运行"; return 0; }
    echo "roscore: 启动"
    setsid nohup roscore > "$RUN/roscore_console.log" 2>&1 < /dev/null &
    wait_for 15 ros_up && echo "roscore: OK" || echo "roscore: 超时"
}

start_voice() {
    voice_up && { echo "voice: 已在运行"; return 0; }
    echo "voice: 启动"
    setsid nohup roslaunch --wait bobac_practicum voice_services.launch \
        > "$RUN/voice_console.log" 2>&1 < /dev/null &
    sleep 3
    echo "voice: 已启动"
}

stop_app() {
    app_up || { echo "app: 未运行"; return 0; }
    pkill -f "app.py --ros" 2>/dev/null
    sleep 2
    pkill -9 -f "app.py --ros" 2>/dev/null
    echo "app: 已停止"
}

stop_launches() {
    pkill -f "navigation.launch" 2>/dev/null
    pkill -f "mapping.launch" 2>/dev/null
    pkill -f "static.launch" 2>/dev/null
    pkill -f "voice_services.launch" 2>/dev/null
    sleep 2
    echo "launch: 已停止"
}

stop_nodes() {
    ros_up || return 0
    rosnode kill -a >/dev/null 2>&1
    sleep 1
}

pick_cfg() {
    if [ -n "${CFG:-}" ] && [ -f "$CFG" ]; then echo "$CFG"; return; fi
    local c
    c=$(ls -t "$RUN"/navigation_project_*.json 2>/dev/null | head -1)
    [ -n "$c" ] || c=$(ls -t "$RUN"/*project*.json 2>/dev/null | head -1)
    [ -n "$c" ] || c="$RUN/project.json"
    echo "$c"
}

app_cmd() {  # app_cmd <extra flags...>
    local cfg
    cfg=$(pick_cfg)
    echo "app: 启动 (config=$cfg) $*"
    setsid nohup python -u "$APP" --ros --auto-speech --config "$cfg" "$@" \
        > "$RUN/app_console.log" 2>&1 < /dev/null &
    if wait_for 25 port_up; then
        echo "app: 端口 $PORT 就绪"
    else
        echo "app: 启动失败，日志尾部："
        tail -n 12 "$RUN/app_console.log" 2>/dev/null
    fi
}

# ---------------------------------------------------------------- commands
case "${1:-status}" in

status)
    echo "CTL_VERSION=3"
    echo "HOST=$(hostname)"
    if ros_up; then echo "ROSCORE=up"; else echo "ROSCORE=down"; fi
    if app_up; then echo "APP=up PID=$(app_pid)"; else echo "APP=down"; fi
    if port_up; then echo "PORT=up"; else echo "PORT=down"; fi
    if nav_up; then echo "MODE=navigation"; elif map_up; then echo "MODE=mapping";
    elif static_up; then echo "MODE=static"; else echo "MODE=none"; fi
    if voice_up; then echo "VOICE=up"; else echo "VOICE=down"; fi
    if rostopic list 2>/dev/null | grep -qx "/map"; then echo "MAP_TOPIC=live"; else echo "MAP_TOPIC=none"; fi
    MAPYAML=$(ps -ef | grep navigation.launch | grep -v grep | grep -o "map_yaml:=[^ ]*" | head -1 | cut -d= -f2)
    echo "MAP_YAML=${MAPYAML:-}"
    NAVPS=$(ps -ef | grep navigation.launch | grep -v grep)
    PX=$(echo "$NAVPS" | grep -o "initial_pose_x:=[^ ]*" | head -1 | cut -d= -f2)
    PY=$(echo "$NAVPS" | grep -o "initial_pose_y:=[^ ]*" | head -1 | cut -d= -f2)
    PA=$(echo "$NAVPS" | grep -o "initial_pose_a:=[^ ]*" | head -1 | cut -d= -f2)
    echo "POSE_X=${PX:-}"; echo "POSE_Y=${PY:-}"; echo "POSE_A=${PA:-}"
    echo "NODES=$(rosnode list 2>/dev/null | wc -l)"
    ;;

up)
    MODE="${2:-nav}"
    start_ros
    case "$MODE" in
    nav|navigation)
        MAP="${3:-}"
        if [ -z "$MAP" ]; then
            MAP=$(ls -t "$MAPDIR"/*navigation*.yaml 2>/dev/null | head -1)
        fi
        if [ -z "$MAP" ] || [ ! -f "$MAP" ]; then
            echo "没有可用导航地图：$MAPDIR/*navigation*.yaml"
            exit 2
        fi
        IX="${4:-}"; IY="${5:-}"; IA="${6:-}"
        if [ -z "$IX" ]; then
            if [ -f "$RUN/last_pose.txt" ]; then
                read IX IY IA < "$RUN/last_pose.txt"
            else
                IX=0; IY=0; IA=0
            fi
        fi
        echo "$IX $IY $IA" > "$RUN/last_pose.txt"
        stop_app; stop_launches
        start_voice
        echo "nav: map=$MAP pose=($IX,$IY,$IA)"
        setsid nohup roslaunch --wait bobac_practicum navigation.launch \
            map_yaml:="$MAP" initial_pose_x:="$IX" initial_pose_y:="$IY" \
            initial_pose_a:="$IA" start_base:=true start_lidar:=true \
            allow_wheel_commands:=true > "$RUN/nav_console.log" 2>&1 < /dev/null &
        sleep 8
        if pgrep -f "navigation.launch" >/dev/null 2>&1; then
            echo "nav: 已启动"
        else
            echo "nav: 启动失败，日志尾部："
            tail -n 15 "$RUN/nav_console.log" 2>/dev/null
            exit 3
        fi
        app_cmd --allow-motion --port $PORT
        echo "NAV_MAP=$MAP"
        ;;
    mapping|map)
        stop_app; stop_launches
        start_voice
        echo "map: 启动建图"
        setsid nohup roslaunch --wait bobac_practicum mapping.launch \
            start_base:=true start_lidar:=true allow_wheel_commands:=true \
            > "$RUN/mapping_console.log" 2>&1 < /dev/null &
        sleep 8
        app_cmd --mapping-teleop --mapping-keyboard --port $PORT
        ;;
    static)
        stop_app; stop_launches
        start_voice
        setsid nohup roslaunch --wait bobac_practicum static.launch \
            > "$RUN/static_console.log" 2>&1 < /dev/null &
        sleep 6
        wait_for 20 port_up && echo "app: 端口 $PORT 就绪" || echo "app: 未就绪"
        ;;
    *)
        echo "未知模式: $MODE (nav|mapping|static)"; exit 1;;
    esac
    ;;

stop)
    stop_app
    stop_launches
    if [ "${2:-}" = "--all" ]; then
        stop_nodes
        pkill -f "rosmaster --core" 2>/dev/null
        echo "roscore: 已停止"
    fi
    ;;

restart)
    MODE="${2:-nav}"
    bash "$0" stop
    sleep 2
    shift 2 2>/dev/null || true
    bash "$0" up "$MODE" "$@"
    ;;

save-map)
    NAME="${2:-map_$(date +%Y%m%d_%H%M%S)}"
    mkdir -p "$MAPDIR"
    timeout 30 rosrun map_server map_saver -f "$MAPDIR/$NAME" map:=/map
    if [ -f "$MAPDIR/$NAME.yaml" ]; then
        echo "SAVED=$MAPDIR/$NAME.yaml"
    else
        echo "保存失败（建图模式是否在运行？）"
        exit 1
    fi
    ;;

maps)
    ls -1t "$MAPDIR"/*.yaml 2>/dev/null | head -20
    ;;

log)
    case "${2:-app}" in
        app) F="$RUN/app_console.log";;
        nav) F="$RUN/nav_console.log";;
        map) F="$RUN/mapping_console.log";;
        voice) F="$RUN/voice_console.log";;
        *) F="$RUN/app_console.log";;
    esac
    tail -n "${3:-60}" "$F" 2>/dev/null || echo "没有日志 $F"
    ;;

*)
    sed -n '2,16p' "$0"
    ;;
esac
