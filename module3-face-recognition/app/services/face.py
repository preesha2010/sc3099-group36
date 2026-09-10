"""Face detection, deterministic feature extraction, and hash generation."""

import hashlib
from typing import Any, Dict, Optional

import cv2
import mediapipe as mp
import numpy as np
from fastapi import HTTPException


def detect_face(image_array: np.ndarray) -> Optional[Dict[str, Any]]:
    """Detect the highest-confidence face and return its bounded pixel box."""
    with mp.solutions.face_detection.FaceDetection(
        model_selection=0,
        min_detection_confidence=0.5,
    ) as detector:
        result = detector.process(image_array)
    if not result.detections:
        return None

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


def extract_face_embedding(image_array: np.ndarray, detection: Dict[str, Any]) -> np.ndarray:
    """Create the documented simple fixed-size face representation for hashing."""
    x1, y1, x2, y2 = detection["bbox"]
    face_crop = image_array[y1:y2, x1:x2]
    if face_crop.size == 0:
        raise HTTPException(status_code=400, detail="Could not extract face features")
    normalized = cv2.resize(face_crop, (128, 128), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(normalized, cv2.COLOR_RGB2GRAY).astype(np.uint8)


def generate_face_hash(embedding: np.ndarray) -> str:
    """Return the required 64-character SHA-256 hash; do not persist the embedding."""
    return hashlib.sha256(embedding.tobytes()).hexdigest()
