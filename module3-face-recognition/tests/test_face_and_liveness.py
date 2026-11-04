import base64
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image

from app.services import face, liveness


SAMPLES = Path(__file__).resolve().parents[2] / "sample_images"


def sample(name):
    return base64.b64encode((SAMPLES / name).read_bytes()).decode()


@pytest.mark.parametrize("mode", ["blink", "head_turn"])
def test_single_image_never_claims_motion_success(client, mode):
    response = client.post("/liveness/check", json={"challenge_response": "unused", "challenge_type": mode})
    assert response.status_code == 400
    assert "multiple frames" in response.json()["detail"]


def test_real_sample_registers_and_different_identity_is_rejected(client):
    enrolled = client.post("/face/enroll", json={"user_id": "test", "image": sample("obama.jpg"), "camera_consent": True})
    assert enrolled.status_code == 201
    reference = enrolled.json()["face_template_hash"]
    for name, expected in (("obama.jpg", True), ("biden.jpg", False)):
        result = client.post("/face/verify", json={"image": sample(name), "reference_template_hash": reference})
        assert result.status_code == 200
        assert result.json()["match_passed"] is expected


def test_passive_default_and_documented_metadata(client):
    response = client.post("/liveness/check", json={"challenge_response": sample("obama.jpg")})
    assert response.status_code == 200
    data = response.json()
    assert data["challenge_type"] == "passive"
    assert data["details"]["motion_verified"] is False
    assert {"depth_detected", "texture_analysis_score", "color_distribution_score", "threshold"} <= data["details"].keys()
    assert data["liveness_passed"] == (data["liveness_score"] >= .6)


def test_blank_input_does_not_pass_liveness(client):
    buffer = BytesIO()
    Image.new("RGB", (256, 256), "gray").save(buffer, format="PNG")
    response = client.post("/liveness/check", json={"challenge_response": base64.b64encode(buffer.getvalue()).decode()})
    assert response.status_code == 200 and not response.json()["liveness_passed"]


def test_uniform_texture_cannot_pass_even_with_mesh(monkeypatch):
    monkeypatch.setattr(liveness, "analyze_face_mesh", lambda _: {
        "face_mesh_complete": True, "nose_tip_z": -.07, "depth_quality": "good", "landmark_count": 468,
    })
    image = np.full((256, 256, 3), 128, dtype=np.uint8)
    passed, score, _, details = liveness.assess_passive_liveness(image, {"confidence": .99, "bbox": (0, 0, 256, 256)})
    assert not passed and score < .6 and details["texture_analysis_score"] == 0


def test_missing_depth_cannot_be_outweighed_by_other_cues(monkeypatch):
    monkeypatch.setattr(liveness, "analyze_face_mesh", lambda _: {
        "face_mesh_complete": True, "nose_tip_z": 0, "depth_quality": "poor", "landmark_count": 468,
    })
    monkeypatch.setattr(liveness, "analyze_texture", lambda *_: {
        "sharpness": 1000, "texture_analysis_score": 1.0, "color_distribution_score": 1.0,
    })
    passed, score, _, _ = liveness.assess_passive_liveness(
        np.zeros((256, 256, 3), dtype=np.uint8), {"confidence": .99, "bbox": (0, 0, 256, 256)},
    )
    assert not passed and score < .6


def test_multiple_faces_are_rejected(monkeypatch):
    class Detector:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def process(self, _):
            return SimpleNamespace(detections=[object(), object()])

    monkeypatch.setattr(face.mp.solutions.face_detection, "FaceDetection", Detector)
    with pytest.raises(HTTPException) as error:
        face.detect_face(np.zeros((256, 256, 3), dtype=np.uint8))
    assert error.value.status_code == 400


def test_mesh_uses_468_points_without_retaining_input(monkeypatch):
    def analyze(image):
        assert image.shape == (256, 256, 3)
        return [SimpleNamespace(landmark=[SimpleNamespace(x=0., y=0., z=-.06) for _ in range(468)])]

    monkeypatch.setattr(liveness, "landmarks_for_image", analyze)
    original = np.zeros((256, 256, 3), np.uint8)
    result = liveness.analyze_face_mesh(original)
    assert result["landmark_count"] == 468 and result["depth_quality"] == "good"
    assert original.shape == (256, 256, 3)


@pytest.mark.parametrize("count,value", [(0, 0.), (467, 0.), (468, float("nan")), (468, float("inf"))])
def test_corrupt_mesh_output_returns_safe_service_error(client, monkeypatch, count, value):
    monkeypatch.setattr(liveness, "landmarks_for_image", lambda _: [SimpleNamespace(
        landmark=[SimpleNamespace(x=value, y=0., z=-.06) for _ in range(count)])])
    response = client.post("/liveness/check", json={"challenge_response": sample("obama.jpg")})
    assert response.status_code == 503
    assert response.json() == {"detail": "Invalid local face mesh output"}


@pytest.mark.parametrize("exception", [RuntimeError, ValueError])
def test_mesh_native_failure_is_redacted_and_slot_is_released(client, monkeypatch, exception):
    def fail(_):
        raise exception("private native error / image / path")

    monkeypatch.setattr(liveness, "landmarks_for_image", fail)
    for _ in range(5):  # More than four mesh slots: exceptions cannot leak slots.
        response = client.post("/liveness/check", json={"challenge_response": sample("obama.jpg")})
        assert response.status_code == 503
        assert response.json() == {"detail": "Local face mesh inference is unavailable"}


def test_health_is_not_blocked_by_visual_processing(client, monkeypatch):
    import app.main as api
    started, release = Event(), Event()

    def slow_detection(_):
        started.set()
        assert release.wait(5)
        return None

    monkeypatch.setattr(api, "decode_base64_image", lambda _: np.zeros((32, 32, 3), dtype=np.uint8))
    monkeypatch.setattr(api, "detect_face", slow_detection)
    with ThreadPoolExecutor(max_workers=2) as pool:
        request = pool.submit(client.post, "/face/enroll", json={"user_id": "test", "image": "unused", "camera_consent": True})
        try:
            assert started.wait(3)
            health = pool.submit(client.get, "/health").result(timeout=2)
            assert health.status_code == 200
        finally:
            release.set()
        assert request.result(timeout=3).status_code == 400
