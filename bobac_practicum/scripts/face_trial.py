#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Operator-labelled encounter trial; frames are diagnostics, not independent trials."""
from __future__ import print_function, unicode_literals
import argparse
import json
import os
import time
try:
    from urllib.request import urlopen
except ImportError:
    from urllib2 import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected', required=True, help='person id or unknown, declared by operator')
    parser.add_argument('--seconds', type=float, default=12)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    url = 'http://127.0.0.1:8765'
    initial = json.load(urlopen(url + '/api/status', timeout=5))
    if not initial['controller']['simulated']:
        raise ValueError('本脚本仅用于静态联调')
    start = time.time()
    time.sleep(min(30, max(3, args.seconds)))
    status = json.load(urlopen(url + '/api/status', timeout=5))
    diagnostics = json.load(urlopen(url + '/api/face-diagnostics', timeout=5))
    rows = [r for r in diagnostics['observations'] if r['time'] >= start and not r['enrolling']]
    single = [r for r in rows if r['faces'] == 1 and r.get('match') and r['match'].get('similarity') is not None]
    scores = [r['match']['similarity'] for r in single]
    events = [e for e in status['logs'] if e['time'] >= start]
    authorization = [e for e in events if e['kind'] == 'authorized_detected']
    result = dict(expected=args.expected, timestamp=start, duration_seconds=time.time()-start,
        actual_navigation=False, course_accuracy=None, sufficient_single_face_frames=len(single) >= 20,
        frames=len(rows), valid_single_face_frames=len(single),
        multiple_face_frames=sum(r['faces'] > 1 for r in rows),
        matched_candidate_frames=sum(r.get('person_id') is not None for r in rows),
        authorized_events=len(authorization), last_controller=status['controller'],
        similarity_min=min(scores) if scores else None, similarity_max=max(scores) if scores else None,
        threshold=status['camera'].get('embedding_threshold'),
        events=events, observations=rows)
    with open(os.path.expanduser(args.output), 'w') as stream:
        json.dump(result, stream, indent=2)
    summary = dict((k, v) for k, v in result.items() if k not in ('observations', 'events'))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
