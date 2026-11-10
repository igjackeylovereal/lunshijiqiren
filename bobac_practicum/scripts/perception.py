"""Laser occupancy observations; this does not classify furniture or drive motors."""
from __future__ import division
import math


def scan_observation(ranges, angle_min, angle_increment, range_min, range_max,
                     distance_limit=2.0, front_distance=0.8, min_cluster=3):
    clusters, current, front_hits = [], [], 0
    for index, value in enumerate(ranges):
        angle = angle_min + index * angle_increment
        valid = (not math.isnan(value) and not math.isinf(value)
                 and range_min <= value <= range_max and value <= distance_limit)
        if valid:
            if current and abs(value - current[-1][1]) > 0.25:
                if len(current) >= min_cluster: clusters.append(current)
                current = []
            current.append((angle, value))
            if abs(angle) <= math.pi / 6 and value <= front_distance:
                front_hits += 1
        else:
            if len(current) >= min_cluster: clusters.append(current)
            current = []
    if len(current) >= min_cluster: clusters.append(current)
    distances = [p[1] for c in clusters for p in c]
    return dict(clusters=len(clusters), front_blocked=front_hits >= min_cluster,
                nearest=min(distances) if distances else None)
