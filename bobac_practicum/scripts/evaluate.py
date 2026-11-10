#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Compute observed results only. Input CSV columns: expected,predicted.
Use person IDs or 'unknown' for face trials; 'occupied'/'free' for obstacle trials.
Each row should be an independent labelled trial, not a training image.
"""
from __future__ import print_function
import argparse
import csv
import io
import json
import sys


def evaluate(rows):
    if not rows:
        return {'trials': 0, 'accuracy': None, 'target_met': None}
    if any(not r.get('expected') or not r.get('predicted') for r in rows):
        raise ValueError('Each trial needs expected and predicted labels')
    correct = sum(r['expected'] == r['predicted'] for r in rows)
    unknown = [r for r in rows if r['expected'] == 'unknown']
    false_accepts = sum(r['predicted'] != 'unknown' for r in unknown)
    return dict(trials=len(rows), correct=correct, accuracy=float(correct)/len(rows),
                target_met=float(correct)/len(rows) >= .9,
                unknown_trials=len(unknown), false_accepts=false_accepts,
                false_accept_rate=float(false_accepts)/len(unknown) if unknown else None)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('csv_file')
    args = parser.parse_args()
    with open(args.csv_file, 'r') as stream:
        result = evaluate(list(csv.DictReader(stream)))
    print(json.dumps(result, indent=2))
