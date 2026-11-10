#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Private stdin/stdout vision worker. Never imports ROS or opens a camera/port."""
from __future__ import print_function
import argparse
import os
import sys
import json
import struct


def read_exact(stream, size):
    chunks = []
    while size:
        part = stream.read(size)
        if not part:
            return None
        chunks.append(part)
        size -= len(part)
    return b''.join(chunks)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--deps', required=True)
    parser.add_argument('--data', default=os.path.expanduser('~/bobac_practicum_run/data'))
    parser.add_argument('--config', default=os.path.expanduser('~/bobac_practicum_run/project.json'))
    args = parser.parse_args()
    sys.path[:] = [p for p in sys.path if '/opt/ros/' not in p]
    sys.path.insert(0, args.deps)
    import cv2
    import numpy as np
    from face_recognition import FaceDetector, face_sample
    from face_embeddings import EmbeddingGallery
    cv2.setNumThreads(2)
    cv2.ocl.setUseOpenCL(False)
    detector = FaceDetector(cv2, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets'), isolated=False)
    if detector.net is None:
        raise ValueError('isolated DNN model not loaded: ' + detector.error)
    gallery, embedding_error = None, ''
    try:
        with open(args.config) as stream:
            config = json.load(stream)
        gallery = EmbeddingGallery(cv2, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets'), args.data, config)
    except Exception as exc:
        embedding_error = str(exc)
    print(json.dumps(dict(ready=True, opencv=cv2.__version__, embedding_ready=gallery is not None,
                         embedding_error=embedding_error)))
    sys.stdout.flush()
    while True:
        header = read_exact(sys.stdin, 4)
        if header is None:
            break
        size = struct.unpack('<I', header)[0]
        if size == 0:
            if gallery is not None:
                gallery.reload()
            print(json.dumps(dict(reloaded=True, embedding_ready=gallery is not None)))
            sys.stdout.flush()
            continue
        if not 1 <= size <= 4000000:
            raise ValueError('invalid JPEG length')
        body = read_exact(sys.stdin, size)
        if body is None:
            break
        frame = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
        try:
            boxes = detector.detect(frame)
            match = None
            if gallery is not None and len(boxes) == 1:
                crop, quality, reason = face_sample(cv2, cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), boxes[0])
                if not reason:
                    match = gallery.predict(crop)
            result = dict(boxes=boxes, match=match)
        except Exception as exc:
            result = dict(error=str(exc))
        print(json.dumps(result))
        sys.stdout.flush()


if __name__ == '__main__':
    main()
