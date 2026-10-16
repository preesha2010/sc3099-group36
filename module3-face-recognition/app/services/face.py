"""SHA-256 compatibility and optional local SFace/SimHash recognition."""

import hashlib
from typing import Any, Dict, Optional

import cv2
import mediapipe as mp
import numpy as np
from fastapi import HTTPException
from app.services.templates import template_mode, encode_simhash
from app.observability import timed


@timed("face_detect")
def detect_face(image_array: np.ndarray) -> Optional[Dict[str, Any]]:
    """Detect the highest-confidence face and return its bounded pixel box."""
    if template_mode() == "simhash":
        from app.services.neural import detect_neural_face
        return detect_neural_face(image_array)
    with mp.solutions.face_detection.FaceDetection(
        model_selection=0,
        min_detection_confidence=0.5,
    ) as detector:
        result = detector.process(image_array)
    if not result.detections:
        return None

    if len(result.detections) > 1:
        raise HTTPException(status_code=400, detail="Exactly one face is required")

    detection = max(result.detections, key=lambda item: item.score[0])
    confidence = float(detection.score[0])
    if confidence < 0.7:
        return None

    box = detection.location_data.relative_bounding_box
    height, width = image_array.shape[:2]
    x1 = max(0, int(box.xmin * width))
    y1 = max(0, int(box.ymin * height))
    x2 = min(width, int((box.xmin + box.width) * width))
    y2 = min(height, int((box.ymin + box.height) * height))
    if x2 <= x1 or y2 <= y1:
        return None
    return {"confidence": confidence, "bbox": (x1, y1, x2, y2)}


@timed("embedding")
def extract_face_embedding(image_array: np.ndarray, detection: Dict[str, Any]) -> np.ndarray:
    """Extract transient legacy pixels or aligned neural identity features."""
    if template_mode() == "simhash":
        from app.services.neural import neural_embedding
        return neural_embedding(image_array, detection)
    x1, y1, x2, y2 = detection["bbox"]
    face_crop = image_array[y1:y2, x1:x2]
    if face_crop.size == 0:
        raise HTTPException(status_code=400, detail="Could not extract face features")
    normalized = cv2.resize(face_crop, (128, 128), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(normalized, cv2.COLOR_RGB2GRAY).astype(np.uint8)


@timed("template")
def generate_face_hash(embedding: np.ndarray) -> str:
    """Return the selected 64-hex template; never persist the feature vector."""
    if template_mode() == "simhash":
        return encode_simhash(embedding)
    return hashlib.sha256(embedding.tobytes()).hexdigest()
