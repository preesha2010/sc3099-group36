import numpy as np
import pytest
from fastapi import HTTPException

from app.services import templates


@pytest.fixture
def simhash(monkeypatch):
    monkeypatch.setenv("FACE_TEMPLATE_MODE", "simhash")
    monkeypatch.setattr(templates, "template_key", lambda: b"test-only-never-a-production-key!"[:32])


def test_signed_simhash_preserves_format_and_nearby_vectors(simhash):
    rng = np.random.default_rng(7)
    reference = rng.standard_normal(128).astype(np.float32)
    near = reference + rng.standard_normal(128).astype(np.float32) * .001
    first = templates.encode_simhash(reference)
    second = templates.encode_simhash(near)
    assert len(first) == 64 and len(bytes.fromhex(first)) == 32
    assert templates.match_templates(first, first) == 1.0
    assert templates.match_templates(first, second) > .9


def test_tampered_template_and_sha256_digest_are_not_accepted(simhash):
    first = templates.encode_simhash(np.ones(128, dtype=np.float32))
    corrupted = first[:-1] + ("0" if first[-1] != "0" else "1")
    for other in (corrupted, "a" * 64):
        with pytest.raises(HTTPException) as error:
            templates.match_templates(first, other)
        assert error.value.status_code == 400


def test_key_rotation_requires_new_enrollment(simhash, monkeypatch):
    first = templates.encode_simhash(np.ones(128, dtype=np.float32))
    monkeypatch.setattr(templates, "template_key", lambda: b"rotated-private-test-key-value!!"[:32])
    second = templates.encode_simhash(np.ones(128, dtype=np.float32))
    with pytest.raises(HTTPException):
        templates.match_templates(first, second)


def test_invalid_neural_vectors_are_rejected(simhash):
    for value in (np.zeros(128), np.ones(16), np.full(128, float("nan"))):
        with pytest.raises(HTTPException):
            templates.encode_simhash(value)


def test_sha256_compatibility_still_compares_exact_digests(monkeypatch):
    monkeypatch.setenv("FACE_TEMPLATE_MODE", "sha256")
    assert templates.match_templates("a" * 64, "a" * 64) == 1
    assert templates.match_templates("a" * 64, "b" * 64) == 0


def test_forged_reference_is_rejected_before_decoding_image(client, simhash, monkeypatch):
    import app.main as api

    def must_not_decode(_):
        raise AssertionError("Invalid references must not cause expensive image work")

    monkeypatch.setattr(api, "decode_base64_image", must_not_decode)
    result = client.post("/face/verify", json={"image": "unused", "reference_template_hash": "a" * 64})
    assert result.status_code == 400
