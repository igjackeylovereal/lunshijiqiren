#!/usr/bin/env bash
set -e
source /opt/ros/kinetic/setup.bash
source "$HOME/bobac2_ws/devel/setup.bash"
root=$(cd "$(dirname "$0")/.." && pwd)
exec python -u "$root/scripts/app.py" --ros --auto-speech "$@"
