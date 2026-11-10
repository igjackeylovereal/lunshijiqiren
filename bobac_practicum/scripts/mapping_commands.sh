#!/usr/bin/env bash
# Default: read-only inspection. No mode in this file starts wheel command publishers.
set -eo pipefail
source /opt/ros/kinetic/setup.bash
source "$HOME/bobac2_ws/devel/setup.bash"
source "$HOME/bobac_practicum_ws/devel/setup.bash"
set -u
project_dir="$HOME/bobac_practicum_ws/src/bobac_practicum"

case "${1:-inspect}" in
  inspect)
    python "$project_dir/scripts/navigation_preflight.py"
    ;;
  lidar-only)
    if rosnode list | grep -qx '/rplidarNode'; then
      echo 'Lidar already running; do not start a duplicate.'
      exit 0
    fi
    exec roslaunch bobac_practicum laser_static.launch
    ;;
  isolated-check)
    echo 'CHECK ONLY: real laser with fixture stationary TF in isolated frames.'
    echo 'This does not build the classroom map or establish a parking target.'
    exec roslaunch bobac_practicum mapping_check.launch
    ;;
  *)
    echo 'Usage: bash mapping_commands.sh [inspect|lidar-only|isolated-check]'
    echo 'Real mapping with wheel motion is a separate, later field stage.'
    exit 2
    ;;
esac
