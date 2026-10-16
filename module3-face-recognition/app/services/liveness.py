"""Single-image passive liveness analysis using MediaPipe Face Mesh."""

from typing import Any, Dict, Tuple
import os
from threading import BoundedSemaphore

import cv2
import mediapipe as mp
import numpy as np

from app.services.face import extract_face_embedding, generate_face_hash
from app.services.image import calculate_quality_score
from app.observability import timed


_mesh_slots = BoundedSemaphore(4)


@timed("mesh")
def analyze_face_mesh(image_array: np.ndarray) -> Dict[str, Any]:
    """Return documented Face Mesh depth and completeness metadata."""
    # Each graph is request-local and closed before releasing its slot.
    # Unbounded simultaneous graph construction can exhaust native resources.
    with _mesh_slots:
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
    depth_quality = "good" if landmark_count >= 468 and nose_tip_z < -0.05 else "moderate" if landmark_count >= 468 and nose_tip_z < -0.01 else "poor"
    return {
        "face_mesh_complete": landmark_count >= 468,
        "landmark_count": landmark_count,
        "nose_tip_z": round(nose_tip_z, 5),
        "depth_quality": depth_quality,
    }


def analyze_texture(image_array: np.ndarray, detection: Dict[str, Any]) -> Dict[str, float]:
    """Measure local sharpness and color variation as weak single-image cues.

    These features cannot prove a live subject: a sharp printed/replayed face
    may exhibit them too. They primarily reject blank, blurred, or flat inputs.
    """
    x1, y1, x2, y2 = detection["bbox"]
    crop = cv2.resize(image_array[y1:y2, x1:x2], (128, 128), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    color_variation = float(np.std(crop.astype(np.float32), axis=(0, 1)).mean())
    return {
        "sharpness": sharpness,
        "texture_analysis_score": min(1.0, sharpness / 100.0),
        "color_distribution_score": min(1.0, color_variation / 30.0),
    }


def assess_passive_liveness(image_array: np.ndarray, detection: Dict[str, Any]) -> Tuple[bool, float, str, Dict[str, Any]]:
    """Apply documented 30/25/25/20 cue weights plus a minimum quality gate."""
    quality_score, image_quality = calculate_quality_score(image_array, detection)
    mesh_details = analyze_face_mesh(image_array)
    texture_details = analyze_texture(image_array, detection)
    depth_score = 1.0 if mesh_details["depth_quality"] == "good" else 0.5 if mesh_details["depth_quality"] == "moderate" else 0.0
    mesh_score = 1.0 if mesh_details["face_mesh_complete"] else 0.0
    liveness_score = round(
        0.30 * depth_score + 0.25 * mesh_score
        + 0.25 * texture_details["texture_analysis_score"]
        + 0.20 * texture_details["color_distribution_score"], 3,
    )
    if (quality_score < 0.5 or texture_details["sharpness"] < 10.0
            or not mesh_details["face_mesh_complete"] or mesh_details["depth_quality"] == "poor"):
        liveness_score = min(liveness_score, 0.49)
    face_embedding_hash = generate_face_hash(extract_face_embedding(image_array, detection))
    details = {
        "face_detection_confidence": float(detection["confidence"]),
        "image_quality": image_quality,
        "quality_score": quality_score,
        "depth_detected": mesh_details["depth_quality"] == "good",
        "threshold": 0.60,
        "method": "single_image_heuristic",
        "motion_verified": False,
        **texture_details,
        **mesh_details,
    }
    backend = os.getenv("LIVENESS_BACKEND", "heuristic")
    if backend == "minifasnet":
        from app.services.antispoof import assess_presentation
        real_score, evidence = assess_presentation(image_array)
        liveness_score = round(min(liveness_score, real_score), 6)
        details.update(evidence)
        details["method"] = "minifasnet_ensemble_with_quality_gate"
    elif backend != "heuristic":
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Invalid liveness backend configuration")
    return liveness_score >= 0.60, liveness_score, face_embedding_hash, details
