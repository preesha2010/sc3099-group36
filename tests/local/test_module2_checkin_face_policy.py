"""Required face-verification outages and failed-match review (Workstream B phase 1)."""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

_BACKEND = Path(__file__).resolve().parents[2] / "module2-backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.db.enums import CheckinStatus  # noqa: E402
from app.integrations.face_client import FaceCall  # noqa: E402
from app.modules.checkins import risk_service  # noqa: E402
from app.modules.checkins.schemas import CheckinCreate  # noqa: E402
from app.modules.checkins.service import (  # noqa: E402
    _ADVISORY_LOG_ALLOWED,
    _advisory_risk_payload,
    _advisory_risk_record,
    _consult_advisory_risk,
    _face_signals,
    submit_checkin,
)

VALID_HASH = "a" * 64
LIVE_OK = FaceCall(
    kind="ok",
    status=200,
    data={"liveness_passed": True, "liveness_score": 0.9, "face_embedding_hash": VALID_HASH},
)
LIVE_FAIL = FaceCall(
    kind="ok",
    status=200,
    data={"liveness_passed": False, "liveness_score": 0.1, "face_embedding_hash": ""},
)
MATCH_FAIL = FaceCall(
    kind="ok",
    status=200,
    data={
        "match_passed": False,
        "match_score": 0.0,
        "face_detected": True,
        "current_template_hash": "b" * 64,
    },
)
MATCH_OK = FaceCall(
    kind="ok",
    status=200,
    data={
        "match_passed": True,
        "match_score": 0.95,
        "face_detected": True,
        "current_template_hash": VALID_HASH,
    },
)


def _unavailable(status=503):
    return FaceCall(kind="unavailable", status=status)


def _malformed():
    return FaceCall(kind="malformed", status=200, detail="verify response missing typed fields")


def _client_error(status=400):
    return FaceCall(kind="client_error", status=status, detail="Invalid or corrupt image")


def test_assess_failed_match_is_flagged_not_approved():
    result = risk_service.assess(
        distance_m=10.0,
        geofence_m=100.0,
        liveness_passed=True,
        face_match_passed=False,
        unknown_device=False,
        threshold=0.5,
    )
    assert result["status"] == CheckinStatus.FLAGGED.value
    assert result["risk_score"] < 0.5


def test_assess_failed_liveness_stays_rejected():
    result = risk_service.assess(
        distance_m=10.0,
        geofence_m=100.0,
        liveness_passed=False,
        face_match_passed=False,
        unknown_device=False,
        threshold=0.5,
    )
    assert result["status"] == CheckinStatus.REJECTED.value


def test_assess_gps_beyond_two_times_geofence_stays_rejected():
    result = risk_service.assess(
        distance_m=250.0,
        geofence_m=100.0,
        liveness_passed=True,
        face_match_passed=False,
        unknown_device=False,
        threshold=0.5,
    )
    assert result["status"] == CheckinStatus.REJECTED.value


def test_image_less_required_liveness_does_not_call_module3():
    payload = CheckinCreate(session_id="sess-1")
    user = Mock(face_embedding_hash=VALID_HASH)
    with patch("app.modules.checkins.service.face_client") as mock_face:
        signals = _face_signals(payload, user, require_liveness=True, require_face=True)
    mock_face.liveness.assert_not_called()
    mock_face.verify.assert_not_called()
    assert signals["liveness_passed"] is None
    assert signals["face_match_passed"] is None


def test_required_liveness_unavailable_raises_503():
    payload = CheckinCreate(session_id="sess-1", liveness_challenge_response="img")
    user = Mock(face_embedding_hash=None)
    with patch("app.modules.checkins.service.face_client") as mock_face:
        mock_face.liveness.return_value = _unavailable(None)
        with pytest.raises(HTTPException) as exc:
            _face_signals(payload, user, require_liveness=True, require_face=False)
    assert exc.value.status_code == 503
    mock_face.verify.assert_not_called()


def test_required_liveness_malformed_raises_503():
    payload = CheckinCreate(session_id="sess-1", liveness_challenge_response="img")
    user = Mock(face_embedding_hash=None)
    with patch("app.modules.checkins.service.face_client") as mock_face:
        mock_face.liveness.return_value = _malformed()
        with pytest.raises(HTTPException) as exc:
            _face_signals(payload, user, require_liveness=True)
    assert exc.value.status_code == 503


def test_required_liveness_invalid_image_raises_400_not_503():
    payload = CheckinCreate(session_id="sess-1", liveness_challenge_response="img")
    user = Mock(face_embedding_hash=None)
    with patch("app.modules.checkins.service.face_client") as mock_face:
        mock_face.liveness.return_value = _client_error(400)
        with pytest.raises(HTTPException) as exc:
            _face_signals(payload, user, require_liveness=True)
    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid face image"


def test_optional_verification_unavailable_does_not_raise():
    payload = CheckinCreate(session_id="sess-1", liveness_challenge_response="img")
    user = Mock(face_embedding_hash=VALID_HASH)
    with patch("app.modules.checkins.service.face_client") as mock_face:
        mock_face.liveness.return_value = _unavailable(503)
        mock_face.verify.return_value = _unavailable(503)
        signals = _face_signals(payload, user, require_liveness=False, require_face=False)
    assert signals["liveness_passed"] is None
    assert signals["face_match_passed"] is None


def test_explicit_failed_match_is_not_an_outage():
    payload = CheckinCreate(session_id="sess-1", liveness_challenge_response="img")
    user = Mock(face_embedding_hash=VALID_HASH)
    with patch("app.modules.checkins.service.face_client") as mock_face:
        mock_face.liveness.return_value = LIVE_OK
        mock_face.verify.return_value = MATCH_FAIL
        signals = _face_signals(payload, user, require_liveness=True, require_face=True)
    assert signals["face_match_passed"] is False
    assert signals["liveness_passed"] is True


def _active_session(*, require_liveness=True, require_face=False, require_course_face=False):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    course = Mock(
        risk_threshold=None,
        geofence_radius_meters=None,
        require_face_recognition=require_course_face,
    )
    session = Mock(
        id="sess-1",
        course_id="course-1",
        status="active",
        qr_code_secret=None,
        checkin_opens_at=now - timedelta(hours=1),
        checkin_closes_at=now + timedelta(hours=1),
        venue_latitude=1.3483,
        venue_longitude=103.6831,
        geofence_radius_meters=100.0,
        risk_threshold=0.5,
        require_liveness_check=require_liveness,
        require_face_match=require_face,
        course=course,
    )
    return session


def _student(*, face_hash=None):
    return Mock(id="student-1", face_embedding_hash=face_hash)


def _request():
    request = Mock()
    request.headers = {}
    request.client = Mock(host="127.0.0.1")
    return request


def _payload(*, image="img"):
    return CheckinCreate(
        session_id="sess-1",
        latitude=1.3483,
        longitude=103.6831,
        liveness_challenge_response=image,
    )


def _advisory_ok(**overrides):
    data = {
        "risk_score": 0.88,
        "risk_level": "CRITICAL",
        "pass_threshold": False,
        "signal_breakdown": {"liveness": 0.02, "face_match": 0.01, "device": 0.1, "network": 0.15, "geolocation": 0.15},
    }
    data.update(overrides)
    return FaceCall(kind="ok", status=200, data=data)


def _run_submit(session, user, payload, mock_face, *, existing=None):
    created = []

    def fake_create(_db, checkin):
        checkin.id = "chk-1"
        created.append(checkin)
        return checkin

    if not isinstance(mock_face.assess_risk.return_value, FaceCall):
        mock_face.assess_risk.return_value = _advisory_ok()

    db = Mock()
    with (
        patch("app.modules.checkins.service.sessions_repo") as sessions_repo,
        patch("app.modules.checkins.service.enrollments_repo") as enrollments_repo,
        patch("app.modules.checkins.service.checkins_repo") as checkins_repo,
        patch("app.modules.checkins.service.devices_repo"),
        patch("app.modules.checkins.service.append_audit"),
        patch("app.modules.checkins.service.face_client", mock_face),
    ):
        sessions_repo.get_by_id.return_value = session
        enrollments_repo.is_enrolled.return_value = True
        checkins_repo.get_by_session_student.return_value = existing
        checkins_repo.create.side_effect = fake_create
        try:
            result = submit_checkin(db, payload, user, _request())
        except HTTPException as exc:
            return exc, created, db
        return result, created, db


def test_required_timeout_returns_503_and_does_not_create_row():
    mock_face = Mock()
    mock_face.liveness.return_value = _unavailable(None)
    error, created, db = _run_submit(
        _active_session(require_liveness=True),
        _student(),
        _payload(),
        mock_face,
    )
    assert isinstance(error, HTTPException)
    assert error.status_code == 503
    assert created == []
    db.commit.assert_called()
    mock_face.assess_risk.assert_not_called()


def test_required_5xx_and_malformed_return_503_without_row():
    for call in (_unavailable(503), _malformed(), _unavailable(408)):
        mock_face = Mock()
        mock_face.liveness.return_value = call
        error, created, db = _run_submit(
            _active_session(require_liveness=True),
            _student(),
            _payload(),
            mock_face,
        )
        assert isinstance(error, HTTPException), call.kind
        assert error.status_code == 503
        assert created == []
        db.commit.assert_called()


def test_retry_after_recovery_creates_checkin():
    session = _active_session(require_liveness=True)
    user = _student()
    payload = _payload()

    mock_face = Mock()
    mock_face.liveness.return_value = _unavailable(503)
    error, created, _db = _run_submit(session, user, payload, mock_face)
    assert isinstance(error, HTTPException)
    assert error.status_code == 503
    assert created == []

    mock_face.liveness.return_value = LIVE_OK
    result, created, db = _run_submit(session, user, payload, mock_face)
    assert not isinstance(result, HTTPException)
    assert result["status"] in {
        CheckinStatus.APPROVED.value,
        CheckinStatus.FLAGGED.value,
        CheckinStatus.REJECTED.value,
    }
    assert len(created) == 1
    db.commit.assert_called()


def test_failed_face_match_is_flagged_and_creates_row():
    mock_face = Mock()
    mock_face.liveness.return_value = LIVE_OK
    mock_face.verify.return_value = MATCH_FAIL
    result, created, db = _run_submit(
        _active_session(require_liveness=True, require_face=True),
        _student(face_hash=VALID_HASH),
        _payload(),
        mock_face,
    )
    assert not isinstance(result, HTTPException)
    assert result["status"] == CheckinStatus.FLAGGED.value
    assert result["face_match_passed"] is False
    assert len(created) == 1
    db.commit.assert_called()


def test_failed_liveness_is_rejected_and_creates_row():
    mock_face = Mock()
    mock_face.liveness.return_value = LIVE_FAIL
    result, created, db = _run_submit(
        _active_session(require_liveness=True),
        _student(),
        _payload(),
        mock_face,
    )
    assert not isinstance(result, HTTPException)
    assert result["status"] == CheckinStatus.REJECTED.value
    assert result["liveness_passed"] is False
    assert len(created) == 1
    db.commit.assert_called()


def test_invalid_image_is_400_not_503_and_creates_no_row():
    mock_face = Mock()
    mock_face.liveness.return_value = _client_error(400)
    error, created, db = _run_submit(
        _active_session(require_liveness=True),
        _student(),
        _payload(),
        mock_face,
    )
    assert isinstance(error, HTTPException)
    assert error.status_code == 400
    assert created == []
    db.commit.assert_called()


def test_image_less_submit_still_creates_row_when_liveness_required():
    mock_face = Mock()
    result, created, db = _run_submit(
        _active_session(require_liveness=True),
        _student(),
        _payload(image=None),
        mock_face,
    )
    assert not isinstance(result, HTTPException)
    assert result["status"] in {
        CheckinStatus.APPROVED.value,
        CheckinStatus.FLAGGED.value,
        CheckinStatus.PENDING.value,
    }
    assert result["liveness_passed"] is None
    assert len(created) == 1
    mock_face.liveness.assert_not_called()
    mock_face.assess_risk.assert_not_called()
    db.commit.assert_called()


def test_advisory_success_does_not_change_m2_score_or_status():
    mock_face = Mock()
    mock_face.liveness.return_value = LIVE_OK
    mock_face.verify.return_value = MATCH_OK
    mock_face.assess_risk.return_value = _advisory_ok()
    result, created, db = _run_submit(
        _active_session(require_liveness=True, require_face=True),
        _student(face_hash=VALID_HASH),
        _payload(),
        mock_face,
    )
    local = risk_service.assess(
        distance_m=0.0,
        geofence_m=100.0,
        liveness_passed=True,
        face_match_passed=True,
        unknown_device=True,
        threshold=0.5,
    )
    assert not isinstance(result, HTTPException)
    assert result["status"] == local["status"]
    assert result["risk_score"] == local["risk_score"]
    assert result["status"] != CheckinStatus.REJECTED.value
    mock_face.assess_risk.assert_called_once()
    sent = mock_face.assess_risk.call_args.args[0]
    assert sent == {"liveness_score": 0.9, "face_match_score": 0.95}
    assert set(sent) <= {"liveness_score", "face_match_score"}
    db.commit.assert_called()
    assert len(created) == 1


def test_risk_service_outage_returns_503_without_row():
    for call in (
        FaceCall(kind="unavailable", status=None),
        FaceCall(kind="unavailable", status=503),
        FaceCall(kind="unavailable", status=408),
        FaceCall(kind="client_error", status=400),
    ):
        mock_face = Mock()
        mock_face.liveness.return_value = LIVE_OK
        mock_face.verify.return_value = MATCH_OK
        mock_face.assess_risk.return_value = call
        error, created, db = _run_submit(
            _active_session(require_liveness=True, require_face=True),
            _student(face_hash=VALID_HASH),
            _payload(),
            mock_face,
        )
        assert isinstance(error, HTTPException), call.status
        assert error.status_code == 503
        assert created == []
        db.commit.assert_called()
        mock_face.assess_risk.assert_called_once()


def test_malformed_risk_response_returns_503_without_row():
    mock_face = Mock()
    mock_face.liveness.return_value = LIVE_OK
    mock_face.verify.return_value = MATCH_OK
    mock_face.assess_risk.return_value = FaceCall(
        kind="malformed", status=200, detail="non-object risk body"
    )
    error, created, db = _run_submit(
        _active_session(require_liveness=True, require_face=True),
        _student(face_hash=VALID_HASH),
        _payload(),
        mock_face,
    )
    assert isinstance(error, HTTPException)
    assert error.status_code == 503
    assert created == []
    db.commit.assert_called()


def test_retry_after_risk_service_recovery_creates_checkin():
    session = _active_session(require_liveness=True, require_face=True)
    user = _student(face_hash=VALID_HASH)
    payload = _payload()

    mock_face = Mock()
    mock_face.liveness.return_value = LIVE_OK
    mock_face.verify.return_value = MATCH_OK
    mock_face.assess_risk.return_value = FaceCall(kind="unavailable", status=503)
    error, created, db = _run_submit(session, user, payload, mock_face)
    assert isinstance(error, HTTPException)
    assert error.status_code == 503
    assert created == []
    db.commit.assert_called()

    mock_face.assess_risk.return_value = _advisory_ok()
    result, created, db = _run_submit(session, user, payload, mock_face)
    local = risk_service.assess(
        distance_m=0.0,
        geofence_m=100.0,
        liveness_passed=True,
        face_match_passed=True,
        unknown_device=True,
        threshold=0.5,
    )
    assert not isinstance(result, HTTPException)
    assert result["status"] == local["status"]
    assert result["risk_score"] == local["risk_score"]
    assert len(created) == 1
    db.commit.assert_called()


def test_failed_match_stays_flagged_when_advisory_says_low():
    mock_face = Mock()
    mock_face.liveness.return_value = LIVE_OK
    mock_face.verify.return_value = MATCH_FAIL
    mock_face.assess_risk.return_value = _advisory_ok(
        risk_score=0.05, risk_level="LOW", pass_threshold=True
    )
    result, created, _db = _run_submit(
        _active_session(require_liveness=True, require_face=True),
        _student(face_hash=VALID_HASH),
        _payload(),
        mock_face,
    )
    assert result["status"] == CheckinStatus.FLAGGED.value
    assert result["face_match_passed"] is False
    assert len(created) == 1
    mock_face.assess_risk.assert_called_once()


def test_failed_liveness_stays_rejected_when_advisory_says_low():
    mock_face = Mock()
    mock_face.liveness.return_value = LIVE_FAIL
    mock_face.assess_risk.return_value = _advisory_ok(
        risk_score=0.05, risk_level="LOW", pass_threshold=True
    )
    result, created, _db = _run_submit(
        _active_session(require_liveness=True),
        _student(),
        _payload(),
        mock_face,
    )
    assert result["status"] == CheckinStatus.REJECTED.value
    assert result["liveness_passed"] is False
    assert len(created) == 1
    sent = mock_face.assess_risk.call_args.args[0]
    assert sent == {"liveness_score": 0.1}
    assert "face_match_score" not in sent


def test_advisory_payload_omits_incompatible_and_sensitive_fields():
    payload = _advisory_risk_payload(
        {
            "liveness_score": 0.9,
            "face_match_score": 0.95,
            "liveness_passed": True,
            "face_match_passed": True,
            "face_embedding_hash": VALID_HASH,
        }
    )
    assert payload == {"liveness_score": 0.9, "face_match_score": 0.95}
    assert _advisory_risk_payload({"liveness_passed": True}) is None
    assert _advisory_risk_payload({"liveness_score": None, "face_match_score": None}) is None


def test_advisory_log_record_has_no_sensitive_fields():
    call = _advisory_ok()
    record = _advisory_risk_record(call, ["liveness_score", "face_match_score"])
    assert set(record) <= _ADVISORY_LOG_ALLOWED
    dumped = str(record)
    for forbidden in (
        "image",
        "template",
        "hash",
        "ip_address",
        "user_agent",
        "latitude",
        "longitude",
        "device_fingerprint",
        "student",
        "email",
        "pass_threshold",
    ):
        assert forbidden not in dumped


def test_consult_advisory_outage_raises_503():
    mock_face = Mock()
    mock_face.assess_risk.return_value = FaceCall(kind="unavailable", status=503)
    with patch("app.modules.checkins.service.face_client", mock_face):
        with pytest.raises(HTTPException) as exc:
            _consult_advisory_risk({"liveness_score": 0.9})
    assert exc.value.status_code == 503
    mock_face.assess_risk.assert_called_once()


def test_consult_advisory_logs_without_templates_or_ids(caplog):
    mock_face = Mock()
    mock_face.assess_risk.return_value = _advisory_ok()
    with patch("app.modules.checkins.service.face_client", mock_face):
        with caplog.at_level(logging.INFO, logger="saiv.checkins.advisory_risk"):
            _consult_advisory_risk(
                {
                    "liveness_score": 0.9,
                    "face_match_score": 0.95,
                    "face_embedding_hash": VALID_HASH,
                }
            )
    assert VALID_HASH not in caplog.text
    assert "face_embedding_hash" not in caplog.text
    assert "CRITICAL" in caplog.text
    _consult_advisory_risk({"liveness_score": None})
    mock_face.assess_risk.assert_called_once()


def test_inactive_session_still_rejected_before_face_call():
    session = _active_session()
    session.status = "closed"
    mock_face = Mock()
    error, created, db = _run_submit(session, _student(), _payload(), mock_face)
    assert isinstance(error, HTTPException)
    assert error.status_code == 400
    mock_face.liveness.assert_not_called()
    assert created == []
    db.commit.assert_called()


def test_duplicate_checkin_still_rejected_before_face_call():
    mock_face = Mock()
    error, created, db = _run_submit(
        _active_session(),
        _student(),
        _payload(),
        mock_face,
        existing=Mock(id="existing"),
    )
    assert isinstance(error, HTTPException)
    assert error.status_code == 400
    mock_face.liveness.assert_not_called()
    assert created == []
    db.commit.assert_called()


# ---------------------------------------------------------------------------
# HTTP checks against the isolated backend: image-less and existing gates.
# ---------------------------------------------------------------------------


def test_http_image_less_checkin_unchanged(
    client, test_student, test_session, test_enrollment, auth_headers_student
):
    response = client.post(
        "/api/v1/checkins/",
        headers=auth_headers_student,
        json={
            "session_id": test_session["id"],
            "latitude": 1.3483,
            "longitude": 103.6831,
            "device_fingerprint": f"fp_{uuid4().hex[:10]}",
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] in ["pending", "approved", "flagged", "rejected"]
    assert data.get("liveness_passed") in (None, True, False)


def test_http_duplicate_checkin_unchanged(
    client, test_student, test_session, test_enrollment, auth_headers_student
):
    first = client.post(
        "/api/v1/checkins/",
        headers=auth_headers_student,
        json={
            "session_id": test_session["id"],
            "latitude": 1.3483,
            "longitude": 103.6831,
            "device_fingerprint": f"fp_{uuid4().hex[:10]}",
        },
    )
    assert first.status_code == 201, first.text
    duplicate = client.post(
        "/api/v1/checkins/",
        headers=auth_headers_student,
        json={
            "session_id": test_session["id"],
            "latitude": 1.3483,
            "longitude": 103.6831,
            "device_fingerprint": f"fp_{uuid4().hex[:10]}",
        },
    )
    assert duplicate.status_code == 400
