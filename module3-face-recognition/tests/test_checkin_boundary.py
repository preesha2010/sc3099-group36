"""M3 component contract only; no pretend M2 persistence/attendance tests."""

import base64
from io import BytesIO

import cv2
from fastapi import HTTPException
from PIL import Image
import pytest


def blank():
    buffer = BytesIO()
    Image.new("RGB", (256, 256), "gray").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def test_enrollment_metadata_matches_deployment_root_without_changing_opaque_template(client):
    from pathlib import Path
    photo = (Path(__file__).resolve().parents[2] / "sample_images" / "obama.jpg").read_bytes()
    result = client.post("/face/enroll", json={"user_id": "contract", "camera_consent": True,
                                             "image": base64.b64encode(photo).decode()})
    assert result.status_code == 201
    assert len(result.json()["face_template_hash"]) == 64
    root = client.get("/").json()
    for name in ("template_mode", "template_format", "match_score_policy"):
        assert result.json()["details"][name] == root[name]


@pytest.mark.parametrize("path,body", [
    ("/face/enroll", {"user_id": "contract", "camera_consent": True}),
    ("/face/verify", {"reference_template_hash": "a" * 64}),
    ("/face/match", {"reference_hash": "a" * 64}),
    ("/liveness/check", {}),
])
def test_requested_visual_operation_never_treats_missing_image_as_pass(client, path, body):
    response = client.post(path, json=body)
    assert response.status_code == 422
    assert "passed" not in response.json() and "risk_score" not in response.json()


@pytest.mark.parametrize("path,payload,prefix", [
    ("/face/verify", lambda: {"image": blank(), "reference_template_hash": "a" * 64}, "match"),
    ("/liveness/check", lambda: {"challenge_response": blank()}, "liveness"),
])
def test_valid_no_face_is_negative_decision_not_outage(client, path, payload, prefix):
    result = client.post(path, json=payload())
    assert result.status_code == 200
    assert result.json()[prefix + "_passed"] is False and result.json()[prefix + "_score"] == 0


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("path,payload,prefix", [
    ("/face/verify", lambda: {"image": blank(), "reference_template_hash": "a" * 64}, "match"),
    ("/liveness/check", lambda: {"challenge_response": blank()}, "liveness"),
])
def test_unavailable_is_redacted_503_and_same_request_can_retry(client, monkeypatch, native, path, payload, prefix):
    import app.main as api
    original = api.detect_face

    def unavailable(_):
        if native:
            raise cv2.error("private-model-marker")
        raise HTTPException(503, "Local model is unavailable")

    monkeypatch.setattr(api, "detect_face", unavailable)
    body = payload()
    response = client.post(path, json=body)
    assert response.status_code == 503
    assert "private-model-marker" not in response.text
    assert prefix + "_passed" not in response.json()
    assert api.app.state.admitted == 0 and client.get("/health").status_code == 200
    monkeypatch.setattr(api, "detect_face", original)
    retry = client.post(path, json=body)
    assert retry.status_code == 200 and retry.json()[prefix + "_passed"] is False


def test_m3_risk_pass_does_not_imply_required_face_verification_pass(client):
    result = client.post("/risk/assess", json={
        "liveness_score": 1, "face_match_score": 0, "ip_address": "8.8.8.8",
        "geolocation": {"latitude": 1, "longitude": 103, "accuracy": 10}}).json()
    assert result["risk_score"] == .35 and result["pass_threshold"] is True
    # Deliberately documents why M2 MUST gate required evidence before scoring.
    assert "status" not in result and "approved" not in result
