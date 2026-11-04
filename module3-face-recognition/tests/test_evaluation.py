import json
from pathlib import Path
import sys

import pytest

from app.evaluation import rate, summarize

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import evaluate_corpus as corpus
from evaluate_robustness import CONDITIONS, perturb
from support import report_target


def test_perturbations_preserve_exif_display_orientation_instead_of_turning_faces_sideways():
    import base64
    from io import BytesIO
    from PIL import Image
    from app.services.image import decode_base64_image
    source = Image.new("RGB", (64, 96), (0, 0, 0))
    source.paste((255, 80, 40), (0, 0, 32, 48))
    exif = Image.Exif()
    exif[274] = 6  # Raw portrait pixels require a clockwise display rotation.
    data = BytesIO()
    source.save(data, format="JPEG", exif=exif)
    for condition in CONDITIONS:
        image = decode_base64_image(base64.b64encode(perturb(data.getvalue(), condition)).decode())
        assert image.shape == (64, 96, 3)
        assert image[8:24, 60:84, 0].mean() > image[40:56, 12:36, 0].mean() + 50


def test_far_frr_and_pad_rates_with_no_face_rejections():
    rows = [(True, .9, True), (True, .5, True), (False, .8, True), (False, 0, False)]
    result = summarize(rows, .7, "identity")
    assert result["FAR"]["rate"] == .5
    assert result["FRR"]["rate"] == .5
    pad = summarize(rows, .6, "pad")
    assert pad["APCER"]["errors"] == pad["BPCER"]["errors"] == 1
    # A no-face response must never pass even at threshold zero.
    assert summarize([(True, 0, False)], 0, "identity")["FRR"]["rate"] == 1


def test_robustness_transforms_are_bounded_jpeg_in_memory_and_original_is_unchanged():
    from io import BytesIO
    from PIL import Image
    image = BytesIO()
    Image.new("RGB", (640, 480), (100, 120, 140)).save(image, format="JPEG")
    data = image.getvalue()
    assert perturb(data, "original") is data
    for condition in CONDITIONS:
        with Image.open(BytesIO(perturb(data, condition))) as transformed:
            assert transformed.format == "JPEG"
            assert transformed.width <= 640 and transformed.height <= 480
    with pytest.raises(ValueError):
        perturb(data, "unknown")


def test_empty_denominators_and_small_sample_intervals_are_honest():
    assert rate(0, 0)["rate"] is None
    assert rate(0, 0)["wilson_95"] is None
    assert rate(0, 1)["wilson_95"][1] > .79
    assert rate(1, 1)["wilson_95"][0] < .21


def test_manifest_requires_authorization_boolean_labels_and_safe_paths(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"authorized": False, "identity": []}))
    with pytest.raises(ValueError, match="authorization"):
        corpus.load_manifest(path)
    image = tmp_path / "sample.jpg"
    image.write_bytes(b"fixture-not-decoded-by-manifest-loader")
    manifest = {"authorized": True, "identity": [{"enroll": "sample.jpg", "probe": "sample.jpg", "same_person": True}]}
    path.write_text(json.dumps(manifest))
    assert len(corpus.load_manifest(path)[0]) == 1
    manifest["identity"][0]["same_person"] = "true"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="boolean"):
        corpus.load_manifest(path)
    for value in ("../outside.jpg", str(image.resolve()), "sample.txt"):
        with pytest.raises(ValueError):
            corpus.image_path(path, value)


def test_report_cannot_overwrite_code_models_or_other_modules():
    for target in ("../README.md", "app/main.py", "models/template.key", "evaluation/../app/main.py", "evaluation/nested/test.json"):
        with pytest.raises(ValueError):
            report_target(target)
    assert report_target("evaluation/test.json").name == "test.json"


def test_batch_evaluator_reports_http_errors_separately(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus, "photo", lambda *_: "secret-base64")

    class Response:
        def __init__(self, code, data):
            self.status_code, self.data = code, data

        def json(self):
            return self.data

    replies = iter([
        Response(201, {"face_template_hash": "private-template"}),
        Response(200, {"match_score": .9, "face_detected": True}),
        Response(400, {}),
        Response(200, {"liveness_score": .1, "details": {"face_detected": True}}),
        Response(503, {}),
    ])

    class Client:
        def post(self, *_args, **_kwargs):
            return next(replies)

    report = {"identity_http_errors": 0, "pad_http_errors": 0}
    corpus.evaluate(Client(), tmp_path / "manifest.json", [
        {"enroll": "a.jpg", "probe": "b.jpg", "same_person": True},
        {"enroll": "a.jpg", "probe": "c.jpg", "same_person": False}],
        [{"image": "d.jpg", "live": False}, {"image": "e.jpg", "live": True}], report)
    assert report["identity_evaluated"] == report["pad_evaluated"] == 1
    assert report["identity_http_errors"] == report["pad_http_errors"] == 1
    assert report["identity_at_api_threshold"]["FAR"]["rate"] is None
    assert "secret-base64" not in json.dumps(report)
    assert "private-template" not in json.dumps(report)


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "models" / "sface.onnx").is_file(),
                    reason="Run model bootstrap for the real neural corpus smoke test")
def test_corpus_evaluation_core_with_real_models_and_existing_public_samples(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv("FACE_TEMPLATE_MODE", "simhash")
    # Only existing public repo samples are read; no manifest or photos are written.
    base = Path(__file__).resolve().parents[2] / "sample_images" / "not-written.json"
    report = {"identity_http_errors": 0, "pad_http_errors": 0}
    with TestClient(app) as client:
        corpus.evaluate(client, base, [
            {"enroll": "obama.jpg", "probe": "obama2.jpg", "same_person": True},
            {"enroll": "obama.jpg", "probe": "biden.jpg", "same_person": False}], [], report)
    assert report["identity_evaluated"] == 2
    assert report["identity_at_api_threshold"]["FAR"]["errors"] == 0
    assert report["identity_at_api_threshold"]["FRR"]["errors"] == 0
    assert report["pad_at_api_threshold"]["APCER"]["rate"] is None
