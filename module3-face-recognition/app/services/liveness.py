"""Single-image passive liveness analysis using MediaPipe Face Mesh."""

from typing import Any, Dict, Tuple

import mediapipe as mp
import numpy as np

from app.services.face import extract_face_embedding, generate_face_hash
from app.services.image import calculate_quality_score


def analyze_face_mesh(image_array: np.ndarray) -> Dict[str, Any]:
    """Return documented Face Mesh depth and completeness metadata."""
    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
    ) as face_mesh:
        result = face_mesh.process(image_array)
    if not result.multi_face_landmarks:
        return {"face_mesh_complete": False, "landmark_count": 0, "nose_tip_z": 0.0, "depth_quality": "poor"}

    landmarks = result.multi_face_landmarks[0].landmark
    nose_tip_z = float(landmarks[1].z)
    landmark_count = len(landmarks)
    depth = abs(nose_tip_z)
    depth_quality = "good" if landmark_count >= 468 and depth > 0.03 else "moderate" if landmark_count >= 468 and depth > 0.01 else "poor"
    return {
        "face_mesh_complete": landmark_count >= 468,
        "landmark_count": landmark_count,
        "nose_tip_z": round(nose_tip_z, 5),
        "depth_quality": depth_quality,
    }


def assess_passive_liveness(image_array: np.ndarray, detection: Dict[str, Any]) -> Tuple[bool, float, str, Dict[str, Any]]:
    """Combine documented quality and 3D mesh signals without retaining image data."""
    quality_score, image_quality = calculate_quality_score(image_array, detection)
    mesh_details = analyze_face_mesh(image_array)
    depth_score = 1.0 if mesh_details["depth_quality"] == "good" else 0.5 if mesh_details["depth_quality"] == "moderate" else 0.0
    mesh_score = 1.0 if mesh_details["face_mesh_complete"] else 0.0
    liveness_score = round(0.45 * quality_score + 0.30 * mesh_score + 0.25 * depth_score, 3)
    face_embedding_hash = generate_face_hash(extract_face_embedding(image_array, detection))
    return liveness_score >= 0.60, liveness_score, face_embedding_hash, {
        "face_detection_confidence": float(detection["confidence"]),
        "image_quality": image_quality,
        **mesh_details,
    }


def detect_blink(_: Any) -> bool:
    """A single still image cannot prove a blink; multi-frame support belongs to a future flow."""
    return False
