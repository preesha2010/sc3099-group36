"""Mocked FaceClient response validation. Does not require Module 3 running."""
from __future__ import annotations

import math
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest

_BACKEND = Path(__file__).resolve().parents[2] / "module2-backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.integrations.face_client import FaceCall, FaceClient  # noqa: E402
from app.modules.checkins.schemas import CheckinCreate  # noqa: E402
from app.modules.checkins.service import _face_signals  # noqa: E402

VALID_HASH = "a" * 64
OTHER_HASH = "b" * 64


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, *, json_error: bool = False):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._payload


@contextmanager
def _fake_http(response: _FakeResponse):
    mock_client = Mock()
    mock_client.post.return_value = response
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    with patch("app.integrations.face_client.httpx.Client", return_value=mock_client):
        yield mock_client


@pytest.fixture
def client() -> FaceClient:
    return FaceClient(base_url="http://face.test", timeout=1.0)


def test_enroll_valid_201(client):
    body = {
        "enrollment_successful": True,
        "face_template_hash": VALID_HASH,
        "quality_score": 0.85,
        "details": {"face_detected": True},
    }
    with _fake_http(_FakeResponse(201, body)):
        result = client.enroll("user-1", "abc", True)
    assert result.kind == "ok"
    assert result.data["enrollment_successful"] is True
    assert result.data["face_template_hash"] == VALID_HASH
    assert result.data["quality_score"] == 0.85


def test_enroll_requires_explicit_success_and_valid_hash(client):
    with _fake_http(
        _FakeResponse(
            201,
            {"enrollment_successful": False, "face_template_hash": VALID_HASH, "quality_score": 0.9},
        )
    ):
        failed = client.enroll("user-1", "abc", True)
    assert failed.kind == "ok"
    assert failed.data["enrollment_successful"] is False
    assert "face_template_hash" not in failed.data

    with _fake_http(
        _FakeResponse(
            201,
            {"enrollment_successful": True, "face_template_hash": "not-a-hash", "quality_score": 0.9},
        )
    ):
        bad_hash = client.enroll("user-1", "abc", True)
    assert bad_hash.kind == "malformed"


def test_verify_failed_match_is_ok_biometric_failure(client):
    with _fake_http(
        _FakeResponse(
            200,
            {
                "match_passed": False,
                "match_score": 0.0,
                "match_threshold": 0.70,
                "face_detected": False,
                "current_template_hash": "",
            },
        )
    ):
        result = client.verify("img", VALID_HASH)
    assert result.kind == "ok"
    assert result.data["match_passed"] is False
    assert result.data["match_score"] == 0.0
    assert result.data["current_template_hash"] == ""


def test_liveness_explicit_failure_is_ok(client):
    with _fake_http(
        _FakeResponse(
            200,
            {
                "liveness_passed": False,
                "liveness_score": 0.12,
                "liveness_threshold": 0.60,
                "challenge_type": "passive",
                "face_embedding_hash": "",
                "details": {},
            },
        )
    ):
        result = client.liveness("img")
    assert result.kind == "ok"
    assert result.data["liveness_passed"] is False
    assert result.data["liveness_score"] == 0.12


def test_rejects_string_booleans_and_out_of_range_scores(client):
    with _fake_http(
        _FakeResponse(
            200,
            {
                "liveness_passed": "false",
                "liveness_score": 0.9,
                "face_embedding_hash": "",
            },
        )
    ):
        assert client.liveness("img").kind == "malformed"

    with _fake_http(
        _FakeResponse(
            200,
            {
                "match_passed": True,
                "match_score": 1.5,
                "face_detected": True,
                "current_template_hash": VALID_HASH,
            },
        )
    ):
        assert client.verify("img", VALID_HASH).kind == "malformed"

    with _fake_http(
        _FakeResponse(
            200,
            {
                "match_passed": True,
                "match_score": math.nan,
                "face_detected": True,
                "current_template_hash": VALID_HASH,
            },
        )
    ):
        assert client.verify("img", VALID_HASH).kind == "malformed"

    with _fake_http(
        _FakeResponse(
            201,
            {"enrollment_successful": 1, "face_template_hash": VALID_HASH, "quality_score": 0.8},
        )
    ):
        assert client.enroll("u", "img", True).kind == "malformed"


def test_malformed_non_json_and_missing_fields(client):
    with _fake_http(_FakeResponse(200, json_error=True)):
        assert client.liveness("img").kind == "malformed"
    with _fake_http(_FakeResponse(200, {})):
        assert client.verify("img", VALID_HASH).kind == "malformed"
    with _fake_http(_FakeResponse(201, {"enrollment_successful": True, "quality_score": 0.8})):
        assert client.enroll("u", "img", True).kind == "malformed"
    with _fake_http(
        _FakeResponse(200, {"liveness_passed": True, "liveness_score": 0.9})
    ):
        assert client.liveness("img").kind == "malformed"


def test_client_error_and_unavailable(client):
    with _fake_http(_FakeResponse(400, {"detail": "No face detected"})):
        err = client.enroll("u", "img", True)
    assert err.kind == "client_error"
    assert err.status == 400

    with _fake_http(_FakeResponse(503, {"detail": "busy"})):
        down = client.liveness("img")
    assert down.kind == "unavailable"

    with _fake_http(_FakeResponse(408, {"detail": "Request body read deadline exceeded"})):
        timed_out_upload = client.liveness("img")
    assert timed_out_upload.kind == "unavailable"
    assert timed_out_upload.status == 408

    mock_client = Mock()
    mock_client.post.side_effect = httpx.TimeoutException("timeout")
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    with patch("app.integrations.face_client.httpx.Client", return_value=mock_client):
        timed_out = client.verify("img", VALID_HASH)
    assert timed_out.kind == "unavailable"


def test_face_signals_omitted_image_does_not_call_module3():
    payload = CheckinCreate(session_id="sess-1")
    user = Mock(face_embedding_hash=VALID_HASH)
    with patch("app.modules.checkins.service.face_client") as mock_face:
        signals = _face_signals(payload, user)
    mock_face.liveness.assert_not_called()
    mock_face.verify.assert_not_called()
    assert signals["liveness_passed"] is None
    assert signals["face_match_passed"] is None


def test_face_signals_explicit_liveness_false_and_failed_match():
    payload = CheckinCreate(session_id="sess-1", liveness_challenge_response="img")
    user = Mock(face_embedding_hash=VALID_HASH)
    live = FaceCall(
        kind="ok",
        status=200,
        data={"liveness_passed": False, "liveness_score": 0.1, "face_embedding_hash": ""},
    )
    verify = FaceCall(
        kind="ok",
        status=200,
        data={
            "match_passed": False,
            "match_score": 0.0,
            "face_detected": True,
            "current_template_hash": OTHER_HASH,
        },
    )
    with patch("app.modules.checkins.service.face_client") as mock_face:
        mock_face.liveness.return_value = live
        mock_face.verify.return_value = verify
        signals = _face_signals(payload, user)
    assert signals["liveness_passed"] is False
    assert signals["face_match_passed"] is False
    assert signals["face_match_score"] == 0.0


def test_face_signals_malformed_and_unavailable_are_not_liveness_failures():
    payload = CheckinCreate(session_id="sess-1", liveness_challenge_response="img")
    user = Mock(face_embedding_hash=VALID_HASH)
    with patch("app.modules.checkins.service.face_client") as mock_face:
        mock_face.liveness.return_value = FaceCall(kind="malformed", status=200)
        mock_face.verify.return_value = FaceCall(kind="unavailable", status=503)
        signals = _face_signals(payload, user)
    assert signals["liveness_passed"] is None
    assert signals["face_match_passed"] is None


def test_face_signals_client_error_does_not_set_liveness_false():
    payload = CheckinCreate(session_id="sess-1", liveness_challenge_response="img")
    user = Mock(face_embedding_hash=None)
    with patch("app.modules.checkins.service.face_client") as mock_face:
        mock_face.liveness.return_value = FaceCall(kind="client_error", status=400)
        signals = _face_signals(payload, user)
    mock_face.verify.assert_not_called()
    assert signals["liveness_passed"] is None


def _valid_risk_body(**overrides):
    body = {
        "risk_score": 0.22,
        "risk_level": "LOW",
        "pass_threshold": True,
        "risk_threshold": 0.50,
        "signal_breakdown": {
            "liveness": 0.025,
            "face_match": 0.0125,
            "device": 0.1,
            "network": 0.075,
            "geolocation": 0.075,
        },
        "recommendations": ["Device trust is unverified; verify a signed server challenge"],
    }
    body.update(overrides)
    return body


def test_assess_risk_valid_response(client):
    with _fake_http(_FakeResponse(200, _valid_risk_body())):
        result = client.assess_risk({"liveness_score": 0.9, "face_match_score": 0.95})
    assert result.kind == "ok"
    assert result.data["risk_score"] == 0.22
    assert result.data["risk_level"] == "LOW"
    assert result.data["pass_threshold"] is True
    assert result.data["signal_breakdown"]["liveness"] == 0.025


def test_assess_risk_timeout_5xx_408_and_malformed(client):
    with _fake_http(_FakeResponse(503, {"detail": "busy"})):
        assert client.assess_risk({"liveness_score": 0.9}).kind == "unavailable"

    with _fake_http(_FakeResponse(408, {"risk_score": 0.1, "risk_level": "LOW", "pass_threshold": True, "signal_breakdown": {}})):
        timed_out = client.assess_risk({"liveness_score": 0.9})
    assert timed_out.kind == "unavailable"
    assert timed_out.status == 408

    with _fake_http(_FakeResponse(200, json_error=True)):
        assert client.assess_risk({"liveness_score": 0.9}).kind == "malformed"

    with _fake_http(_FakeResponse(200, {"risk_score": "high", "risk_level": "LOW", "pass_threshold": True, "signal_breakdown": {}})):
        assert client.assess_risk({"liveness_score": 0.9}).kind == "malformed"

    with _fake_http(_FakeResponse(200, {"risk_score": 0.2, "risk_level": "SAFE", "pass_threshold": True, "signal_breakdown": {}})):
        assert client.assess_risk({"liveness_score": 0.9}).kind == "malformed"

    with _fake_http(
        _FakeResponse(
            200,
            {"risk_score": 0.2, "risk_level": "LOW", "pass_threshold": True, "signal_breakdown": {"liveness": math.nan}},
        )
    ):
        assert client.assess_risk({"liveness_score": 0.9}).kind == "malformed"

    mock_client = Mock()
    mock_client.post.side_effect = httpx.TimeoutException("timeout")
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    with patch("app.integrations.face_client.httpx.Client", return_value=mock_client):
        assert client.assess_risk({"liveness_score": 0.9}).kind == "unavailable"


def test_assess_risk_client_error_is_not_success(client):
    with _fake_http(_FakeResponse(400, {"detail": "liveness_score must be between 0 and 1"})):
        result = client.assess_risk({"liveness_score": 1.5})
    assert result.kind == "client_error"
    assert result.status == 400
