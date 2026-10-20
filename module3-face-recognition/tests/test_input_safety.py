import base64
from io import BytesIO

import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image

from app.services import image as image_service
from app.middleware import BodySizeLimitMiddleware


def encode_image(size=(64, 64), image_format="PNG"):
    buffer = BytesIO()
    Image.new("RGB", size, color=(80, 90, 100)).save(buffer, format=image_format)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


@pytest.mark.parametrize("payload", ["", "not/base64!!", base64.b64encode(b"not an image").decode()])
def test_invalid_images_return_safe_errors(client, payload):
    response = client.post("/face/enroll", json={"user_id": "test", "image": payload, "camera_consent": True})
    assert response.status_code == 400
    assert response.json()["detail"] in {"Image must be a non-empty base64 string", "Invalid or corrupt image"}


def test_only_documented_formats_and_sizes_are_decoded():
    for image_format in ("PNG", "JPEG"):
        decoded = image_service.decode_base64_image(encode_image(image_format=image_format))
        assert decoded.shape == (64, 64, 3)
        assert decoded.dtype == np.uint8 and decoded.flags.owndata
    for payload in (encode_image(image_format="BMP"), encode_image(size=(16, 16))):
        with pytest.raises(HTTPException) as error:
            image_service.decode_base64_image(payload)
        assert error.value.status_code == 400


def test_encoded_and_decoded_limits(monkeypatch):
    payload = encode_image()
    monkeypatch.setattr(image_service, "MAX_BASE64_CHARACTERS", 8)
    with pytest.raises(HTTPException) as error:
        image_service.decode_base64_image(payload)
    assert error.value.status_code == 413
    monkeypatch.setattr(image_service, "MAX_BASE64_CHARACTERS", 10000)
    monkeypatch.setattr(image_service, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(HTTPException) as error:
        image_service.decode_base64_image(payload)
    assert error.value.status_code == 413


def test_validation_does_not_echo_biometric_input(client):
    secret = "sensitive-image-marker"
    response = client.post("/face/enroll", json={"user_id": "test", "image": {"raw": secret}, "camera_consent": True})
    assert response.status_code == 422
    assert secret not in response.text
    assert "input" not in response.json()["detail"][0]


def test_consent_requires_actual_boolean(client):
    response = client.post("/face/enroll", json={"user_id": "test", "image": "unused", "camera_consent": "true"})
    assert response.status_code == 422
    response = client.post("/face/enroll", json={"user_id": "test", "image": "unused", "camera_consent": False})
    assert response.status_code == 400 and "consent" in response.json()["detail"].lower()


@pytest.mark.parametrize("field,value", [("liveness_score", 1.01), ("face_match_score", -0.1), ("liveness_score", "NaN"), ("face_match_score", "Infinity")])
def test_invalid_scores_rejected(client, field, value):
    assert client.post("/risk/assess", json={field: value}).status_code == 422


@pytest.mark.parametrize("geo", [
    {"latitude": 91, "longitude": 0, "accuracy": 10},
    {"latitude": 0, "longitude": 181, "accuracy": 10},
    {"latitude": 0, "longitude": 0, "accuracy": -1},
    {"latitude": 0, "longitude": 0, "accuracy": "NaN"},
])
def test_invalid_coordinates_rejected(client, geo):
    assert client.post("/risk/assess", json={"geolocation": geo}).status_code == 422


def test_invalid_reference_hash_rejected(client):
    assert client.post("/face/verify", json={"image": "unused", "reference_template_hash": "bad"}).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [False, True])
async def test_body_limit_rejects_header_and_chunked_uploads(declared):
    called = False
    messages = iter([
        {"type": "http.request", "body": b"1234", "more_body": True},
        {"type": "http.request", "body": b"5678", "more_body": False},
    ])
    responses = []

    async def downstream(*_):
        nonlocal called
        called = True

    async def receive():
        return next(messages)

    async def send(message):
        responses.append(message)

    scope = {"type": "http", "method": "POST", "headers": [(b"content-length", b"8")] if declared else []}
    await BodySizeLimitMiddleware(downstream, max_bytes=5, body_seconds=3)(scope, receive, send)
    assert not called
    assert responses[0]["status"] == 413
