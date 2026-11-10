#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Read-only navigation inventory: no motor ports, goals or velocity publishers."""
from __future__ import print_function, unicode_literals
import argparse
import glob
import hashlib
import io
import json
import os
import sys
import time


def inspect_map(path):
    import yaml
    path = os.path.realpath(os.path.expanduser(path))
    with io.open(path, encoding='utf-8') as stream:
        body = yaml.safe_load(stream)
    if not isinstance(body, dict) or not body.get('image'):
        raise ValueError('不是地图 YAML')
    image = body['image']
    image = os.path.realpath(image if os.path.isabs(image) else os.path.join(os.path.dirname(path), image))
    resolution, origin = body.get('resolution'), body.get('origin')
    if not isinstance(resolution, (int, float)) or resolution <= 0:
        raise ValueError('地图分辨率无效')
    if not isinstance(origin, list) or len(origin) != 3:
        raise ValueError('地图原点无效')
    if not os.path.isfile(image):
        raise ValueError('地图图像不存在：' + image)
    with open(image, 'rb') as stream:
        digest = hashlib.sha256(stream.read()).hexdigest()
    return dict(yaml=path, image=image, resolution=resolution, origin=origin, image_sha256=digest,
                classroom_confirmed=False)


def inventory(config, selected_map=None):
    import rospkg
    import rosgraph
    result = dict(timestamp=time.time(), motion_enabled=config.get('motion_enabled'),
                  audio_output=config.get('audio_output'), expected_action=config['navigation_action'],
                  this_probe_sends_motion_commands=False, packages={}, candidate_maps=[], blockers=[],
                  serial_devices=[dict(path=p, resolved=os.path.realpath(p)) for p in glob.glob('/dev/serial/by-id/*')])
    packages = rospkg.RosPack()
    hardware_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 'config', 'navigation_hardware.json')
    hardware = {}
    if os.path.isfile(hardware_file):
        with io.open(hardware_file, encoding='utf-8') as stream:
            hardware = json.load(stream)
        result['hardware_confirmation'] = hardware
    for name in ['bobac2_base', 'bobac2_kinematics', 'rplidar_ros', 'bobac2_navigation',
                 'move_base', 'amcl', 'map_server', 'gmapping', 'teb_local_planner', 'navfn']:
        try:
            result['packages'][name] = packages.get_path(name)
        except rospkg.ResourceNotFound:
            result['packages'][name] = None
            result['blockers'].append('missing_package:' + name)
    nav = result['packages'].get('bobac2_navigation')
    if nav:
        for path in sorted(glob.glob(nav + '/maps/*.yaml')):
            try:
                result['candidate_maps'].append(inspect_map(path))
            except (ValueError, IOError) as exc:
                result['candidate_maps'].append(dict(yaml=path, error=str(exc)))
    result['selected_map'] = inspect_map(selected_map) if selected_map else None
    if not selected_map:
        result['blockers'].append('classroom_map_not_selected_or_confirmed')
    result['unmarked_places'] = [p['id'] for p in config['places'] if not p.get('pose') or not p.get('map_id')]
    if result['unmarked_places']:
        result['blockers'].append('real_target_coordinates_missing')
    try:
        master = rosgraph.Master('/practicum_readonly_preflight')
        publishers, subscribers, services = master.getSystemState()
        types = dict(master.getPublishedTopics('/'))
        result['speed_publishers'] = dict((topic, nodes) for topic, nodes in publishers
                                           if topic in ('/cmd_vel', '/car_cmd'))
        result['action_status_topics'] = [t for t in types if t.endswith('/status')
                                          and types[t] == 'actionlib_msgs/GoalStatusArray']
        result['action_available'] = config['navigation_action'] + '/status' in result['action_status_topics']
        result['sensor_publishers'] = dict((topic, nodes) for topic, nodes in publishers
                                            if topic in ('/scan', '/odom', '/map', '/amcl_pose'))
        if not result['action_available']:
            result['blockers'].append('navigation_action_not_running')
        for topic in ('/scan', '/odom', '/map', '/amcl_pose'):
            if not result['sensor_publishers'].get(topic):
                result['blockers'].append('no_publisher:' + topic)
    except Exception as exc:
        result['ros_error'] = str(exc)
        result['blockers'].append('ros_master_unavailable')
    result['ready_for_real_navigation'] = False
    result['physical_checks_pending'] = ['真实底盘轮速反馈与里程计验证', '轮径、轮距与雷达安装位置校准',
        '当前教室完整建图', '地图定位与 TF', '建图后指定固定停放点', '急停和现场首次运动测试']
    if hardware.get('chassis', {}).get('type') != 'two_wheels':
        result['physical_checks_pending'].append('实物底盘类型确认')
    if not hardware.get('lidar', {}).get('verified'):
        result['physical_checks_pending'].append('雷达供电与串口确认')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=os.path.expanduser('~/bobac_practicum_run/project.json'))
    parser.add_argument('--map', dest='map_yaml')
    parser.add_argument('--output', default=os.path.expanduser('~/bobac_practicum_run/navigation_preflight.json'))
    args = parser.parse_args()
    with io.open(args.config, encoding='utf-8') as stream:
        config = json.load(stream)
    result = inventory(config, args.map_yaml)
    body = json.dumps(result, ensure_ascii=False, indent=2)
    with io.open(args.output, 'w', encoding='utf-8') as stream:
        stream.write(body)
    print(body.encode('utf-8') if sys.version_info[0] < 3 else body)


if __name__ == '__main__':
    main()
