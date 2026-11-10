#!/bin/bash
# 机器人端一键体检
source /opt/ros/kinetic/setup.bash 2>/dev/null
source "$HOME/bobac2_ws/devel/setup.bash" 2>/dev/null

echo "===== 系统 ====="
hostname
hostname -I
lsb_release -ds 2>/dev/null
echo "ROS: $(rosversion -d 2>/dev/null)"
echo "ROS_MASTER_URI=$ROS_MASTER_URI"

echo
echo "===== 节点 ====="
rosnode list 2>/dev/null

echo
echo "===== 服务 ====="
rosservice list 2>/dev/null

echo
echo "===== 关键话题频率 ====="
for t in /scan /car_data /cmd_vel /practicum/camera/image_raw /amcl_pose /odom; do
    printf "%-32s " "$t"
    out=$(timeout 3 rostopic hz "$t" 2>/dev/null | tail -2 | head -1)
    if [ -z "$out" ]; then echo "(no data)"; else echo "$out"; fi
done

echo
echo "===== /cmd_vel 发布者 ====="
rostopic info /cmd_vel 2>/dev/null

echo
echo "===== 串口设备 ====="
ls -l /dev/ttyUSB* /dev/video* 2>/dev/null

echo
echo "===== 导航/语音包 ====="
for p in bobac2_base bobac2_kinematics bobac2_slam bobac2_navigation rplidar_ros \
         bobac2_face practicum_manager audio_collect ifly_package speech_synthesis; do
    printf "%-24s " "$p"
    if rospack find "$p" >/dev/null 2>&1; then echo "OK"; else echo "MISSING"; fi
done
