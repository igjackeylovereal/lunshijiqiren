# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import math
import os


def pixel_goal(meta, u, v, yaw):
    """Image uses top-left origin; ROS grid uses bottom-left and rotated origin."""
    values = (u, v, yaw)
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or
           math.isnan(x) or math.isinf(x) for x in values):
        raise ValueError('目标点必须为有限数值')
    w, h, r = meta['width'], meta['height'], meta['resolution']
    if not 0 <= u < w or not 0 <= v < h or not -math.pi <= yaw <= math.pi:
        raise ValueError('目标点或朝向超出范围')
    x, y = (int(u)+.5)*r, (h-1-int(v)+.5)*r
    ox, oy, angle = meta['origin']
    return dict(x=ox+x*math.cos(angle)-y*math.sin(angle),
                y=oy+x*math.sin(angle)+y*math.cos(angle), yaw=yaw)


def map_catalog(directory):
    """Inventory only: selecting an entry never starts a hardware process."""
    import yaml
    directory = os.path.realpath(directory)
    result = []
    if not os.path.isdir(directory):
        return result
    for name in sorted(os.listdir(directory)):
        if not name.endswith('.yaml'):
            continue
        path = os.path.realpath(os.path.join(directory, name))
        if os.path.dirname(path) != directory:
            continue
        try:
            with open(path) as stream:
                entry = yaml.safe_load(stream)
            image = os.path.realpath(os.path.join(directory, entry['image']))
            if not image.startswith(directory+os.sep) or not os.path.isfile(image):
                continue
            resolution = float(entry['resolution'])
            if not resolution > 0 or math.isinf(resolution):
                continue
            result.append(dict(id=name, yaml=path, resolution=resolution,
                               verified=False))
        except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError):
            continue
    return result
