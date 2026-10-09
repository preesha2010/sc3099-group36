"""Bounded local OpenCV model pools; never cache a user's pixels or features."""

from contextlib import contextmanager
import hashlib
import json
import os
from queue import LifoQueue, Empty
from threading import Lock

import cv2
import numpy as np
from fastapi import HTTPException

from app.model_assets import ASSETS, FAS_COMMIT, model_directory

_pools = {}
_pool_lock = Lock()


def verified_asset(name: str):
    path = model_directory() / name
    try:
        if name in ASSETS:
            expected = ASSETS[name][1]
        else:
            manifest = json.loads((model_directory() / "derived.json").read_text(encoding="utf-8"))
            if manifest["upstream_commit"] != FAS_COMMIT or manifest["torch"].split("+")[0] != "2.5.1":
                raise ValueError("wrong model conversion provenance")
            expected = manifest["models"][name]
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("checksum mismatch")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Model asset is missing or invalid; run model bootstrap") from exc
    return str(path)


class ModelPool:
    def __init__(self, factory):
        self.factory = factory
        self.available = LifoQueue()
        try:
            count = int(os.getenv("FACE_MODEL_WORKERS", "4"))
            if not 1 <= count <= 8:
                raise ValueError
        except ValueError as exc:
            raise HTTPException(status_code=503, detail="FACE_MODEL_WORKERS must be between 1 and 8") from exc
        cv2.setNumThreads(1)
        for _ in range(count):
            self.available.put(factory())

    @contextmanager
    def borrow(self):
        try:
            model = self.available.get(timeout=20)
        except Empty as exc:
            raise HTTPException(status_code=503, detail="Inference capacity is busy; retry later") from exc
        try:
            yield model
        except BaseException:
            # A failed inference/wipe must not return a dirty model to the pool.
            model = None
            raise
        finally:
            self.available.put(model if model is not None else self.factory())


def pool(kind: str) -> ModelPool:
    identity = (kind, str(model_directory()))
    with _pool_lock:
        if identity not in _pools:
            if kind == "yunet":
                path = verified_asset("yunet.onnx")
                factory = lambda: cv2.FaceDetectorYN.create(path, "", (320, 320), .7, .3, 5000)
            elif kind == "sface":
                path = verified_asset("sface.onnx")
                factory = lambda: cv2.FaceRecognizerSF.create(path, "")
            elif kind == "pad":
                retina, proto = verified_asset("retina.caffemodel"), verified_asset("retina.prototxt")
                paths = [verified_asset("minifas-v2.onnx"), verified_asset("minifas-v1se.onnx")]
                factory = lambda: (cv2.dnn.readNetFromCaffe(proto, retina), [cv2.dnn.readNetFromONNX(p) for p in paths])
            else:
                raise ValueError("Unknown model kind")
            _pools[identity] = ModelPool(factory)
        return _pools[identity]


def detect_neural_face(rgb: np.ndarray):
    height, width = rgb.shape[:2]
    # YuNet is designed for 320-sized detection input; alignment is applied to
    # the original-resolution image after mapping landmarks back to pixels.
    scale = min(1.0, 320.0 / max(width, height))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    resized = cv2.resize(bgr, (max(32, int(width * scale)), max(32, int(height * scale))))
    sx, sy = resized.shape[1] / width, resized.shape[0] / height
    with pool("yunet").borrow() as detector:
        detector.setInputSize((resized.shape[1], resized.shape[0]))
        try:
            _, faces = detector.detect(resized)
            faces = None if faces is None else faces.copy()
        finally:
            # Overwrite persistent DNN input/intermediate buffers with blank data.
            detector.detect(np.zeros_like(resized))
    if faces is None or len(faces) == 0:
        return None
    if len(faces) != 1:
        raise HTTPException(status_code=400, detail="Exactly one face is required")
    row = faces[0]
    row[[0, 2, 4, 6, 8, 10, 12]] /= sx
    row[[1, 3, 5, 7, 9, 11, 13]] /= sy
    x1, y1 = max(0, int(row[0])), max(0, int(row[1]))
    x2, y2 = min(width, int(row[0] + row[2])), min(height, int(row[1] + row[3]))
    if x2 <= x1 or y2 <= y1:
        return None
    return {"confidence": float(row[14]), "bbox": (x1, y1, x2, y2), "alignment": row}


def neural_embedding(rgb: np.ndarray, detection: dict) -> np.ndarray:
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    with pool("sface").borrow() as recognizer:
        try:
            aligned = recognizer.alignCrop(bgr, detection["alignment"])
            features = recognizer.feature(aligned).reshape(-1).copy()
        finally:
            recognizer.feature(np.zeros((112, 112, 3), dtype=np.uint8))
    norm = np.linalg.norm(features)
    if not np.isfinite(features).all() or norm < 1e-8:
        raise HTTPException(status_code=400, detail="Could not extract face identity features")
    return features / norm
