# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import glob
import os


def select_identity(scores, threshold=0.82, min_margin=0.08):
    """Absolute rejection remains necessary even with only one enrolled identity."""
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ordered:
        return dict(person_id=None, similarity=None, margin=None)
    best_id, best_score = ordered[0]
    margin = best_score - ordered[1][1] if len(ordered) > 1 else None
    accepted = best_score >= threshold and (margin is None or margin >= min_margin)
    return dict(person_id=best_id if accepted else None, similarity=float(best_score),
                margin=float(margin) if margin is not None else None)


class EmbeddingGallery(object):
    def __init__(self, cv2, assets, data, config):
        import numpy as np
        self.cv2, self.np = cv2, np
        self.data, self.config = data, config
        self.net = cv2.dnn.readNetFromTorch(os.path.join(assets, 'nn4.small2.v1.t7'))
        self.groups, self.counts = {}, {}
        self.reload()

    def vector(self, gray):
        cv2, np = self.cv2, self.np
        # Legacy consented samples are grayscale/equalized; use the same format live.
        color = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        blob = cv2.dnn.blobFromImage(color, 1.0/255.0, (96, 96), (0, 0, 0), True, False)
        self.net.setInput(blob)
        vector = self.net.forward().reshape(-1).astype(np.float32)
        norm = float(np.linalg.norm(vector))
        if vector.size != 128 or not np.isfinite(vector).all() or norm < 1e-8:
            raise ValueError('invalid face embedding')
        return vector / norm

    def reload(self):
        groups, counts = {}, {}
        for person in self.config['people']:
            paths = sorted(glob.glob(os.path.join(self.data, 'faces', person['id'], '*.png')))
            images = []
            for path in paths:
                image = self.cv2.imread(path, 0)
                if image is not None and image.shape == (128, 128):
                    images.append(image)
            counts[person['id']] = len(images)
            if len(images) >= 20 and person.get('authorized'):
                groups[person['id']] = self.np.asarray([self.vector(image) for image in images])
        self.groups, self.counts = groups, counts

    def predict(self, gray):
        vector = self.vector(gray)
        scores = {}
        for key, features in self.groups.items():
            similarities = self.np.dot(features, vector)
            # Require agreement with multiple templates instead of one lucky nearest image.
            scores[key] = float(self.np.sort(similarities)[-3:].mean())
        result = select_identity(scores, self.config.get('embedding_similarity_threshold', .82),
                                 self.config.get('embedding_min_margin', .08))
        result.update(method='OpenFace-128', threshold=self.config.get('embedding_similarity_threshold', .82))
        return result
