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
    assert templates.diagnostic_hash_cosine(first, first) == 1.0
    assert templates.diagnostic_hash_cosine(first, second) > .9


def test_tampered_template_and_sha256_digest_are_not_accepted(simhash):
    first = templates.encode_simhash(np.ones(128, dtype=np.float32))
    corrupted = first[:-1] + ("0" if first[-1] != "0" else "1")
    for other in (corrupted, "a" * 64):
        with pytest.raises(HTTPException) as error:
            templates.diagnostic_hash_cosine(first, other)
        assert error.value.status_code == 400


def test_key_rotation_requires_new_enrollment(simhash, monkeypatch):
    first = templates.encode_simhash(np.ones(128, dtype=np.float32))
    monkeypatch.setattr(templates, "template_key", lambda: b"rotated-private-test-key-value!!"[:32])
    second = templates.encode_simhash(np.ones(128, dtype=np.float32))
    with pytest.raises(HTTPException):
        templates.diagnostic_hash_cosine(first, second)


def test_invalid_neural_vectors_are_rejected(simhash):
    for value in (np.zeros(128), np.ones(16), np.full(128, float("nan"))):
        with pytest.raises(HTTPException):
            templates.encode_simhash(value)


def test_sha256_compatibility_still_compares_exact_digests(monkeypatch):
    monkeypatch.setenv("FACE_TEMPLATE_MODE", "sha256")
    assert templates.match_templates("a" * 64, "a" * 64) == 1
    assert templates.match_templates("a" * 64, "b" * 64) == 0


def test_forged_reference_is_rejected_before_decoding_image(simhash, monkeypatch):
    import app.main as api
    from fastapi.testclient import TestClient

    def must_not_decode(_):
        raise AssertionError("Invalid references must not cause expensive image work")

    monkeypatch.setattr(api, "decode_base64_image", must_not_decode)
    with TestClient(api.app) as client:
        result = client.post("/face/verify", json={"image": "unused", "reference_template_hash": "a" * 64})
    assert result.status_code == 400


def test_unshipped_hash_only_diagnostic_is_cosine_not_affine_rescaling():
    assert templates.score_distance(0) == 1.
    assert templates.score_distance(16) == pytest.approx(.707107)
    assert templates.score_distance(17) < .7
    assert templates.score_distance(22) < .7  # Historical wrong-person acceptance boundary.
    assert templates.score_distance(32) == templates.score_distance(64) == 0.
    assert all(templates.score_distance(i) >= templates.score_distance(i + 1) for i in range(64))


@pytest.mark.parametrize("distance,bits", [(-1, 64), (65, 64), (1, 0), (True, 64), (1.5, 64)])
def test_invalid_distances_are_rejected(distance, bits):
    with pytest.raises(ValueError):
        templates.score_distance(distance, bits)


def test_existing_authenticated_template_bytes_do_not_need_reenrollment_for_scoring_fix(simhash):
    import hmac
    key = templates.template_key()
    def signed(code):
        payload = templates.PREFIX + templates.key_id(key) + code.to_bytes(8, "big")
        return (payload + hmac.digest(key, payload, "sha256")[:16]).hex()
    first = signed(0)
    assert templates.decode_simhash(first, key) == bytes(8)
    assert templates.diagnostic_hash_cosine(first, signed((1 << 16) - 1)) >= .7
    assert templates.diagnostic_hash_cosine(first, signed((1 << 17) - 1)) < .7


def test_simhash_matching_cannot_silently_fall_back_to_hash_only_comparison(simhash):
    value = templates.encode_simhash(np.ones(128))
    with pytest.raises(HTTPException) as error:
        templates.match_templates(value, value)
    assert error.value.status_code == 503


def test_query_margin_matches_fixed_gaussian_moment_formula_and_preserves_template(simhash):
    rng = np.random.default_rng(97)
    reference, query = rng.standard_normal((2, 128)).astype(np.float32)
    template = templates.encode_simhash(reference)
    key = templates.template_key()
    signs = np.unpackbits(np.frombuffer(templates.decode_simhash(template, key), np.uint8)) * 2. - 1.
    margins = templates.projection(key) @ (query / np.linalg.norm(query))
    expected = round(float(np.clip((1 + np.sqrt(np.pi / 2) * np.mean(signs * margins)) / 2, 0, 1)), 6)
    assert templates.match_query_to_template(query, template) == expected
    assert templates.match_query_to_template(query * 100., template) == expected
    assert templates.encode_simhash(reference) == template  # No encoding/key change.


@pytest.mark.parametrize("vector", [np.zeros(128), np.ones(127), np.full(128, np.nan), np.full(128, np.inf)])
def test_invalid_query_vectors_fail_closed_without_hash_only_fallback(simhash, vector):
    reference = templates.encode_simhash(np.ones(128))
    with pytest.raises(HTTPException) as error:
        templates.match_query_to_template(vector, reference)
    assert error.value.status_code == 503


@pytest.mark.parametrize("cosine", [-1., -.5, 0., .5, 1.])
def test_gaussian_moment_identity_on_synthetic_non_biometric_samples(cosine):
    # A synthetic distribution check, NOT face accuracy/calibration evidence.
    rng = np.random.default_rng(431)
    a, b = rng.standard_normal((2, 4000, 64))
    reference = cosine * a + np.sqrt(1 - cosine * cosine) * b
    estimate = np.sqrt(np.pi / 2) * np.mean(np.where(reference >= 0, 1., -1.) * a, axis=1)
    assert abs(estimate.mean() - cosine) < .025
    assert abs(estimate.var() - (np.pi / 2 - cosine * cosine) / 64) < .002
