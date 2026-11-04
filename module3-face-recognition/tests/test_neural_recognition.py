import base64
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageEnhance
from fastapi.testclient import TestClient

from app.model_assets import model_directory

SAMPLES = Path(__file__).resolve().parents[2] / "sample_images"
pytestmark = pytest.mark.skipif(not (model_directory() / "sface.onnx").is_file(), reason="Run scripts/bootstrap_models.py for model-backed tests")


def image(name, brightness=None):
    if brightness is None:
        return base64.b64encode((SAMPLES / name).read_bytes()).decode()
    with Image.open(SAMPLES / name) as source:
        buffer = BytesIO()
        ImageEnhance.Brightness(source).enhance(brightness).save(buffer, format="JPEG")
        return base64.b64encode(buffer.getvalue()).decode()


@pytest.fixture
def reference(monkeypatch):
    from app.main import app
    monkeypatch.setenv("FACE_TEMPLATE_MODE", "simhash")
    with TestClient(app) as client:
        result = client.post("/face/enroll", json={"user_id": "neural-test", "image": image("obama.jpg"), "camera_consent": True})
        assert result.status_code == 201, result.text
        assert result.json()["details"]["template_mode"] == "simhash"
        yield client, result.json()["face_template_hash"]


@pytest.mark.parametrize("name,brightness,expected", [
    ("obama.jpg", None, True), ("obama2.jpg", None, True), ("obama3.jpg", None, True),
    ("obama.jpg", .75, True), ("obama.jpg", 1.25, True), ("biden.jpg", None, False),
])
def test_identity_across_photos_and_lighting(reference, name, brightness, expected):
    client, template = reference
    result = client.post("/face/verify", json={"image": image(name, brightness), "reference_template_hash": template})
    assert result.status_code == 200, result.text
    assert result.json()["match_passed"] is expected


def test_neural_errors_do_not_fall_back_to_exact_image_matching(client, monkeypatch, tmp_path):
    monkeypatch.setenv("FACE_TEMPLATE_MODE", "simhash")
    monkeypatch.setenv("FACE_MODEL_DIR", str(tmp_path))
    result = client.post("/face/enroll", json={"user_id": "test", "image": image("obama.jpg"), "camera_consent": True})
    assert result.status_code == 503
    assert "model" in result.json()["detail"].lower()
