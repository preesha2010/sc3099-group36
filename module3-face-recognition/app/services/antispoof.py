"""Local MiniFASNet ensemble using the publisher's BGR/raw-255 preprocessing."""

import math

import cv2
import numpy as np
from fastapi import HTTPException

from app.services.neural import pool
from app.observability import timed


def expanded_crop(bgr: np.ndarray, bbox: tuple, scale: float) -> np.ndarray:
    """Reproduce the original 2.7x/4x patches including boundary translations."""
    height, width = bgr.shape[:2]
    x, y, box_w, box_h = bbox
    scale = min((height - 1) / box_h, (width - 1) / box_w, scale)
    w, h = box_w * scale, box_h * scale
    cx, cy = x + box_w / 2, y + box_h / 2
    left, top, right, bottom = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    if left < 0:
        right -= left
        left = 0
    if top < 0:
        bottom -= top
        top = 0
    if right > width - 1:
        left -= right - width + 1
        right = width - 1
    if bottom > height - 1:
        top -= bottom - height + 1
        bottom = height - 1
    crop = bgr[max(0, int(top)):int(bottom) + 1, max(0, int(left)):int(right) + 1]
    return cv2.resize(crop, (80, 80), interpolation=cv2.INTER_LINEAR)


@timed("anti_spoof")
def assess_presentation(rgb: np.ndarray) -> tuple[float, dict]:
    """Return real-class probability. Missing/weak detections cannot pass."""
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    height, width = bgr.shape[:2]
    ratio = width / height
    reduced = cv2.resize(bgr, (max(32, int(192 * math.sqrt(ratio))), max(32, int(192 / math.sqrt(ratio)))))
    with pool("pad").borrow() as (detector, nets):
        try:
            detector.setInput(cv2.dnn.blobFromImage(reduced, 1, mean=(104, 117, 123)), "data")
            output = detector.forward("detection_out")
            if output.size % 7 or not np.isfinite(output).all():
                raise HTTPException(status_code=503, detail="Invalid local anti-spoof model output")
            detections = output.reshape(-1, 7).copy()
            if not len(detections):
                return 0.0, {"anti_spoof_model": "MiniFASNetV2+V1SE", "anti_spoof_face_detected": False}
            best = detections[np.argmax(detections[:, 2])]
            if best[2] < .6:
                return 0.0, {"anti_spoof_model": "MiniFASNetV2+V1SE", "anti_spoof_face_detected": False}
            left, top, right, bottom = best[3:7] * np.array([width, height, width, height])
            bbox = (int(left), int(top), max(1, int(right - left + 1)), max(1, int(bottom - top + 1)))
            predictions = []
            for net, scale in zip(nets, (2.7, 4.0)):
                patch = expanded_crop(bgr, bbox, scale)
                # Upstream numpy ToTensor uses float BGR values in [0,255],
                # not RGB or /255 normalization. Changing this ruins predictions.
                net.setInput(cv2.dnn.blobFromImage(patch, 1.0, (80, 80), swapRB=False))
                logits = net.forward().reshape(-1).copy()
                if logits.shape != (3,) or not np.isfinite(logits).all():
                    raise HTTPException(status_code=503, detail="Invalid local anti-spoof model output")
                probabilities = np.exp(logits - logits.max())
                predictions.append(probabilities / probabilities.sum())
            ensemble = np.mean(predictions, axis=0)
            real_score = float(ensemble[1])
            return real_score, {
                "anti_spoof_model": "MiniFASNetV2+V1SE",
                "anti_spoof_face_detected": True,
                "anti_spoof_real_score": round(real_score, 6),
                "anti_spoof_predicted_class": int(np.argmax(ensemble)),
            }
        finally:
            # Clear the model's persistent input and intermediate tensors.
            detector.setInput(cv2.dnn.blobFromImage(np.zeros_like(reduced), 1, mean=(104, 117, 123)), "data")
            detector.forward("detection_out")
            for net in nets:
                net.setInput(np.zeros((1, 3, 80, 80), dtype=np.float32))
                net.forward()
