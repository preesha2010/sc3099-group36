"""Required M2 audit events: checkin_attempted, data_exported, security_violation."""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

_BACKEND = Path(__file__).resolve().parents[2] / "module2-backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.audit.model import AuditLog  # noqa: E402
from app.db.enums import AuditAction, CheckinStatus  # noqa: E402
from app.integrations.face_client import FaceCall  # noqa: E402
from app.modules.checkins.schemas import CheckinCreate  # noqa: E402
from app.modules.checkins.service import submit_checkin  # noqa: E402
from app.modules.export.service import attendance_export, session_export  # noqa: E402

PASSWORD = "testpassword123"
NTU_LAT, NTU_LNG = 1.3483, 103.6831
SENSITIVE_IMAGE = "SENSITIVE_FACE_PAYLOAD_" + ("A" * 48)
OUTCOME_ACTIONS = {
    AuditAction.CHECKIN_APPROVED.value,
    AuditAction.CHECKIN_FLAGGED.value,
    AuditAction.CHECKIN_REJECTED.value,
}


def _email(role: str) -> str:
    return f"{role}_{uuid.uuid4().hex[:10]}@test.com"


def _register_login(client, role: str, full_name: str | None = None) -> dict:
    email = _email(role)
    register = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "full_name": full_name or role.title(),
            "role": role,
        },
    )
    assert register.status_code == 201, register.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {
        "id": register.json()["id"],
        "email": email,
        "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
    }


def _assign(client, course_id: str, user_id: str, admin_headers: dict) -> None:
    response = client.post(
        f"/api/v1/admin/courses/{course_id}/instructors",
        headers=admin_headers,
        json={"instructor_id": user_id},
    )
    assert response.status_code in (200, 201), response.text


def _create_course(client, admin_headers: dict) -> dict:
    created = client.post(
        "/api/v1/courses/",
        headers=admin_headers,
        json={
            "code": f"AU{uuid.uuid4().hex[:4].upper()}",
            "name": "Audit Events Course",
            "semester": "AY2024-25 Sem 1",
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def _create_active_session(
    client, course_id: str, instructor_headers: dict, admin_headers: dict, **extra
) -> dict:
    now = datetime.now(timezone.utc)
    payload = {
        "course_id": course_id,
        "name": f"Audit Session {uuid.uuid4().hex[:6]}",
        "session_type": "lecture",
        "scheduled_start": (now + timedelta(minutes=5)).isoformat(),
        "scheduled_end": (now + timedelta(hours=2)).isoformat(),
        "checkin_opens_at": (now - timedelta(minutes=10)).isoformat(),
        "checkin_closes_at": (now + timedelta(minutes=30)).isoformat(),
        "venue_latitude": NTU_LAT,
        "venue_longitude": NTU_LNG,
        "geofence_radius_meters": 100.0,
        "risk_threshold": 0.5,
        "require_liveness_check": True,
        "require_face_match": False,
    }
    payload.update(extra)
    created = client.post("/api/v1/sessions/", headers=instructor_headers, json=payload)
    assert created.status_code in (200, 201), created.text
    session = created.json()
    activate = client.patch(
        f"/api/v1/admin/sessions/{session['id']}/status",
        headers=admin_headers,
        json={"status": "active"},
    )
    assert activate.status_code == 200, activate.text
    session["status"] = "active"
    return session


def _enroll(client, course_id: str, student_id: str, admin_headers: dict) -> None:
    enrolled = client.post(
        "/api/v1/enrollments/",
        headers=admin_headers,
        json={"student_id": student_id, "course_id": course_id},
    )
    assert enrolled.status_code == 201, enrolled.text


def _list_audit(client, admin_headers: dict, **params) -> list[dict]:
    response = client.get("/api/v1/audit/", headers=admin_headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _assert_no_sensitive_payload(row: dict, *values: str) -> None:
    blob = json.dumps(row, default=str)
    for value in values:
        if not value:
            continue
        assert value not in blob
    details = row.get("details") or {}
    if isinstance(details, dict):
        for key in ("latitude", "longitude", "password", "token", "jwt", "image", "liveness_challenge_response"):
            assert key not in details
        location = details.get("location")
        if location is not None:
            assert location in {"provided", "omitted"}


def _active_session(*, require_liveness=True):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    course = Mock(risk_threshold=None, geofence_radius_meters=None, require_face_recognition=False)
    return Mock(
        id="sess-1",
        course_id="course-1",
        status="active",
        qr_code_secret=None,
        checkin_opens_at=now - timedelta(hours=1),
        checkin_closes_at=now + timedelta(hours=1),
        venue_latitude=NTU_LAT,
        venue_longitude=NTU_LNG,
        geofence_radius_meters=100.0,
        risk_threshold=0.5,
        require_liveness_check=require_liveness,
        require_face_match=False,
        course=course,
    )


def _student():
    return Mock(id="student-1", face_embedding_hash=None)


def _request():
    request = Mock()
    request.headers = {}
    request.client = Mock(host="127.0.0.1")
    return request


def _payload(**overrides):
    data = {
        "session_id": "sess-1",
        "latitude": NTU_LAT,
        "longitude": NTU_LNG,
        "liveness_challenge_response": SENSITIVE_IMAGE,
    }
    data.update(overrides)
    return CheckinCreate(**data)


def _unavailable(status=503):
    return FaceCall(kind="unavailable", status=status)


def _submit_capturing_audit(session, user, payload, mock_face, *, existing=None):
    created = []
    added: list[AuditLog] = []

    def fake_create(_db, checkin):
        checkin.id = "chk-1"
        created.append(checkin)
        return checkin

    db = Mock()
    db.add.side_effect = lambda obj: added.append(obj)
    with (
        patch("app.modules.checkins.service.sessions_repo") as sessions_repo,
        patch("app.modules.checkins.service.enrollments_repo") as enrollments_repo,
        patch("app.modules.checkins.service.checkins_repo") as checkins_repo,
        patch("app.modules.checkins.service.devices_repo"),
        patch("app.modules.checkins.service.face_client", mock_face),
    ):
        sessions_repo.get_by_id.return_value = session
        enrollments_repo.is_enrolled.return_value = True
        checkins_repo.get_by_session_student.return_value = existing
        checkins_repo.create.side_effect = fake_create
        try:
            result = submit_checkin(db, payload, user, _request())
        except HTTPException as exc:
            return exc, created, added, db
    return result, created, added, db


def _audit_actions(rows: list[AuditLog]) -> list[str]:
    return [row.action for row in rows]


# ---------------------------------------------------------------------------
# Unit: check-in attempt / outcome / outage / location denial
# ---------------------------------------------------------------------------


def test_successful_checkin_logs_attempted_and_outcome():
    mock_face = Mock()
    mock_face.liveness.return_value = FaceCall(
        kind="ok",
        status=200,
        data={"liveness_passed": True, "liveness_score": 0.9, "face_embedding_hash": None},
    )
    mock_face.assess_risk.return_value = FaceCall(
        kind="ok",
        status=200,
        data={
            "risk_score": 0.1,
            "risk_level": "LOW",
            "pass_threshold": True,
            "signal_breakdown": {},
        },
    )
    result, created, added, db = _submit_capturing_audit(
        _active_session(),
        _student(),
        _payload(),
        mock_face,
    )
    assert not isinstance(result, HTTPException)
    assert len(created) == 1
    db.commit.assert_called()
    actions = _audit_actions(added)
    assert AuditAction.CHECKIN_ATTEMPTED.value in actions
    assert any(action in OUTCOME_ACTIONS for action in actions)
    attempted = next(row for row in added if row.action == AuditAction.CHECKIN_ATTEMPTED.value)
    assert attempted.success is True
    assert attempted.user_id == "student-1"
    assert attempted.resource_type == "session"
    assert attempted.resource_id == "sess-1"
    assert attempted.timestamp is not None
    details = json.loads(attempted.details)
    assert details["student_id"] == "student-1"
    assert details["session_id"] == "sess-1"
    assert details["location"] == "provided"
    assert SENSITIVE_IMAGE not in attempted.details
    assert "1.3483" not in attempted.details
    assert "103.6831" not in attempted.details


def test_m3_outage_returns_503_with_attempted_and_no_row():
    mock_face = Mock()
    mock_face.liveness.return_value = _unavailable(503)
    error, created, added, db = _submit_capturing_audit(
        _active_session(require_liveness=True),
        _student(),
        _payload(),
        mock_face,
    )
    assert isinstance(error, HTTPException)
    assert error.status_code == 503
    assert created == []
    db.rollback.assert_called()
    db.commit.assert_called()
    actions = _audit_actions(added)
    assert actions == [AuditAction.CHECKIN_ATTEMPTED.value]
    attempted = added[0]
    assert attempted.success is False
    details = json.loads(attempted.details)
    assert details["reason"] == "face_unavailable"
    assert details["http_status"] == 503
    assert details["location"] == "provided"
    assert SENSITIVE_IMAGE not in attempted.details


def test_session_not_found_logs_failed_attempt():
    mock_face = Mock()
    captured: list[AuditLog] = []
    db = Mock()
    db.add.side_effect = lambda obj: captured.append(obj)
    with (
        patch("app.modules.checkins.service.sessions_repo") as sessions_repo,
        patch("app.modules.checkins.service.checkins_repo") as checkins_repo,
        patch("app.modules.checkins.service.face_client", mock_face),
    ):
        sessions_repo.get_by_id.return_value = None
        with pytest.raises(HTTPException) as exc:
            submit_checkin(db, _payload(), _student(), _request())
    assert exc.value.status_code == 404
    checkins_repo.create.assert_not_called()
    assert _audit_actions(captured) == [AuditAction.CHECKIN_ATTEMPTED.value]
    details = json.loads(captured[0].details)
    assert details["reason"] == "session_not_found"
    assert details["http_status"] == 404
    db.commit.assert_called()


def test_already_checked_in_logs_failed_attempt_not_outcome():
    mock_face = Mock()
    error, created, added, db = _submit_capturing_audit(
        _active_session(),
        _student(),
        _payload(),
        mock_face,
        existing=Mock(id="existing"),
    )
    assert isinstance(error, HTTPException)
    assert error.status_code == 400
    assert created == []
    assert _audit_actions(added) == [AuditAction.CHECKIN_ATTEMPTED.value]
    details = json.loads(added[0].details)
    assert details["reason"] == "already_checked_in"
    assert AuditAction.CHECKIN_APPROVED.value not in _audit_actions(added)


def test_location_denied_logs_attempted_and_security_violation():
    mock_face = Mock()
    error, created, added, db = _submit_capturing_audit(
        _active_session(),
        _student(),
        _payload(latitude=51.5, longitude=-0.12),
        mock_face,
    )
    assert isinstance(error, HTTPException)
    assert error.status_code == 403
    assert created == []
    actions = _audit_actions(added)
    assert actions == [
        AuditAction.CHECKIN_ATTEMPTED.value,
        AuditAction.SECURITY_VIOLATION.value,
    ]
    attempted = added[0]
    violation = added[1]
    details = json.loads(attempted.details)
    assert details["reason"] == "location_denied"
    assert details["location"] == "provided"
    assert "51.5" not in attempted.details
    assert "-0.12" not in attempted.details
    assert json.loads(violation.details) == {"violation_type": "checkin_location_denied"}
    assert violation.user_id == "student-1"
    assert violation.success is False
    db.commit.assert_called()


def test_failed_attempt_audit_survives_rollback_before_commit():
    mock_face = Mock()
    mock_face.liveness.return_value = _unavailable(503)
    error, created, added, db = _submit_capturing_audit(
        _active_session(),
        _student(),
        _payload(),
        mock_face,
    )
    assert error.status_code == 503
    assert created == []
    assert db.rollback.called
    assert db.commit.called
    rollback_order = [call[0] for call in db.method_calls if call[0] in {"rollback", "commit", "add"}]
    assert "rollback" in rollback_order
    assert "commit" in rollback_order
    assert rollback_order.index("rollback") < rollback_order.index("commit")


# ---------------------------------------------------------------------------
# Unit: export audits
# ---------------------------------------------------------------------------


def test_authorized_attendance_export_logs_data_exported():
    db = Mock()
    user = Mock(id="instructor-1", role="instructor")
    request = Mock()
    request.headers = {}
    request.client = Mock(host="127.0.0.1")
    course = Mock(id="course-1")
    added: list[AuditLog] = []
    db.add.side_effect = lambda obj: added.append(obj)
    with (
        patch("app.modules.export.service.courses_repo") as courses_repo,
        patch("app.modules.export.service.enrollments_repo") as enrollments_repo,
        patch("app.modules.export.service._attendance_rows", return_value=[]),
    ):
        courses_repo.get_by_id.return_value = course
        enrollments_repo.user_manages_course.return_value = True
        result = attendance_export(
            db, "course-1", user, request, fmt="json", start_date=None, end_date=None
        )
    assert result == []
    assert _audit_actions(added) == [AuditAction.DATA_EXPORTED.value]
    row = added[0]
    assert row.user_id == "instructor-1"
    assert row.resource_type == "course"
    assert row.resource_id == "course-1"
    assert json.loads(row.details) == {"export_type": "attendance_json"}
    db.commit.assert_called()


def test_unauthorized_attendance_export_does_not_log_data_exported():
    db = Mock()
    user = Mock(id="instructor-2", role="instructor")
    request = Mock()
    request.headers = {}
    request.client = Mock(host="127.0.0.1")
    with (
        patch("app.modules.export.service.courses_repo") as courses_repo,
        patch("app.modules.export.service.enrollments_repo") as enrollments_repo,
        patch("app.modules.export.service.append_audit") as append_audit,
    ):
        courses_repo.get_by_id.return_value = Mock(id="course-1")
        enrollments_repo.user_manages_course.return_value = False
        with pytest.raises(HTTPException) as exc:
            attendance_export(
                db, "course-1", user, request, fmt="csv", start_date=None, end_date=None
            )
    assert exc.value.status_code == 403
    append_audit.assert_not_called()
    db.commit.assert_not_called()


def test_authorized_session_export_logs_data_exported():
    db = Mock()
    user = Mock(id="instructor-1", role="instructor")
    request = Mock()
    request.headers = {}
    request.client = Mock(host="127.0.0.1")
    session = Mock(id="sess-1", course_id="course-1", name="Lecture", scheduled_start=None)
    added: list[AuditLog] = []
    db.add.side_effect = lambda obj: added.append(obj)
    with (
        patch("app.modules.export.service.sessions_repo") as sessions_repo,
        patch("app.modules.export.service.can_manage_session", return_value=True),
        patch("app.modules.export.service.enrollments_repo") as enrollments_repo,
        patch("app.modules.export.service.checkins_repo") as checkins_repo,
    ):
        sessions_repo.get_by_id.return_value = session
        enrollments_repo.list_for_course.return_value = []
        checkins_repo.list_for_session.return_value = []
        payload = session_export(db, "sess-1", user, request, fmt="json")
    assert payload["session_id"] == "sess-1"
    assert _audit_actions(added) == [AuditAction.DATA_EXPORTED.value]
    assert json.loads(added[0].details) == {"export_type": "session_json"}
    db.commit.assert_called()


# ---------------------------------------------------------------------------
# HTTP: isolated backend
# ---------------------------------------------------------------------------


def test_http_successful_checkin_creates_attempted_and_outcome(client):
    admin = _register_login(client, "admin")
    instructor = _register_login(client, "instructor")
    student = _register_login(client, "student")
    course = _create_course(client, admin["headers"])
    _assign(client, course["id"], instructor["id"], admin["headers"])
    _enroll(client, course["id"], student["id"], admin["headers"])
    session = _create_active_session(client, course["id"], instructor["headers"], admin["headers"])

    created = client.post(
        "/api/v1/checkins/",
        headers=student["headers"],
        json={
            "session_id": session["id"],
            "latitude": NTU_LAT,
            "longitude": NTU_LNG,
            "device_fingerprint": f"fp_{uuid.uuid4().hex[:10]}",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] in {
        CheckinStatus.APPROVED.value,
        CheckinStatus.FLAGGED.value,
        CheckinStatus.REJECTED.value,
        CheckinStatus.PENDING.value,
    }

    attempted = _list_audit(
        client,
        admin["headers"],
        action=AuditAction.CHECKIN_ATTEMPTED.value,
        user_id=student["id"],
        resource_id=session["id"],
    )
    assert len(attempted) == 1
    row = attempted[0]
    assert row["success"] is True
    assert row["user_id"] == student["id"]
    assert row["action"] == AuditAction.CHECKIN_ATTEMPTED.value
    assert row["resource_type"] == "session"
    assert row["timestamp"]
    details = row["details"]
    assert details["student_id"] == student["id"]
    assert details["session_id"] == session["id"]
    assert details["location"] == "provided"
    _assert_no_sensitive_payload(row, SENSITIVE_IMAGE, PASSWORD, student["headers"]["Authorization"])

    outcome_action = {
        CheckinStatus.APPROVED.value: AuditAction.CHECKIN_APPROVED.value,
        CheckinStatus.FLAGGED.value: AuditAction.CHECKIN_FLAGGED.value,
        CheckinStatus.REJECTED.value: AuditAction.CHECKIN_REJECTED.value,
    }.get(body["status"])
    if outcome_action:
        outcomes = _list_audit(
            client,
            admin["headers"],
            action=outcome_action,
            user_id=student["id"],
            resource_id=body["id"],
        )
        assert len(outcomes) == 1
        assert outcomes[0]["resource_type"] == "checkin"


def test_http_rejected_attempts_are_logged(client):
    admin = _register_login(client, "admin")
    instructor = _register_login(client, "instructor")
    student = _register_login(client, "student")
    course = _create_course(client, admin["headers"])
    _assign(client, course["id"], instructor["id"], admin["headers"])
    session = _create_active_session(client, course["id"], instructor["headers"], admin["headers"])
    missing = str(uuid.uuid4())

    not_enrolled = client.post(
        "/api/v1/checkins/",
        headers=student["headers"],
        json={"session_id": session["id"], "latitude": NTU_LAT, "longitude": NTU_LNG},
    )
    assert not_enrolled.status_code == 400

    missing_session = client.post(
        "/api/v1/checkins/",
        headers=student["headers"],
        json={"session_id": missing, "latitude": NTU_LAT, "longitude": NTU_LNG},
    )
    assert missing_session.status_code == 404

    staff_forbidden = client.post(
        "/api/v1/checkins/",
        headers=instructor["headers"],
        json={"session_id": session["id"], "latitude": NTU_LAT, "longitude": NTU_LNG},
    )
    assert staff_forbidden.status_code == 403

    attempts = _list_audit(
        client,
        admin["headers"],
        action=AuditAction.CHECKIN_ATTEMPTED.value,
        user_id=student["id"],
    )
    reasons = {row["details"]["reason"] for row in attempts if isinstance(row.get("details"), dict)}
    assert "not_enrolled" in reasons
    assert "session_not_found" in reasons
    for row in attempts:
        assert row["success"] is False
        _assert_no_sensitive_payload(row)

    staff_attempts = _list_audit(
        client,
        admin["headers"],
        action=AuditAction.CHECKIN_ATTEMPTED.value,
        user_id=instructor["id"],
        resource_id=session["id"],
    )
    assert len(staff_attempts) == 1
    assert staff_attempts[0]["details"]["reason"] == "not_student"
    assert staff_attempts[0]["details"]["http_status"] == 403


def test_http_m3_outage_returns_503_without_checkin_row(client):
    admin = _register_login(client, "admin")
    instructor = _register_login(client, "instructor")
    student = _register_login(client, "student")
    course = _create_course(client, admin["headers"])
    _assign(client, course["id"], instructor["id"], admin["headers"])
    _enroll(client, course["id"], student["id"], admin["headers"])
    session = _create_active_session(client, course["id"], instructor["headers"], admin["headers"])

    response = client.post(
        "/api/v1/checkins/",
        headers=student["headers"],
        json={
            "session_id": session["id"],
            "latitude": NTU_LAT,
            "longitude": NTU_LNG,
            "liveness_challenge_response": SENSITIVE_IMAGE,
        },
    )
    if response.status_code == 201:
        pytest.skip("Isolated backend has Module 3 available; unit test covers required 503")
    assert response.status_code == 503, response.text

    listed = client.get(
        f"/api/v1/checkins/session/{session['id']}",
        headers=instructor["headers"],
    )
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    rows = payload["items"] if isinstance(payload, dict) and "items" in payload else payload
    assert rows == []

    attempted = _list_audit(
        client,
        admin["headers"],
        action=AuditAction.CHECKIN_ATTEMPTED.value,
        user_id=student["id"],
        resource_id=session["id"],
        success=False,
    )
    assert len(attempted) >= 1
    assert attempted[0]["details"]["reason"] == "face_unavailable"
    _assert_no_sensitive_payload(attempted[0], SENSITIVE_IMAGE)


def test_http_authorized_exports_create_data_exported(client):
    admin = _register_login(client, "admin")
    instructor = _register_login(client, "instructor")
    course = _create_course(client, admin["headers"])
    _assign(client, course["id"], instructor["id"], admin["headers"])
    session = _create_active_session(client, course["id"], instructor["headers"], admin["headers"])

    attendance = client.get(
        f"/api/v1/export/attendance/{course['id']}",
        headers=instructor["headers"],
        params={"format": "json"},
    )
    assert attendance.status_code == 200, attendance.text

    session_csv = client.get(
        f"/api/v1/export/session/{session['id']}",
        headers=instructor["headers"],
        params={"format": "csv"},
    )
    assert session_csv.status_code == 200, session_csv.text

    exported = _list_audit(
        client,
        admin["headers"],
        action=AuditAction.DATA_EXPORTED.value,
        user_id=instructor["id"],
    )
    types = {
        row["details"]["export_type"]
        for row in exported
        if isinstance(row.get("details"), dict)
    }
    assert "attendance_json" in types
    assert "session_csv" in types
    for row in exported:
        assert row["success"] is True
        assert row["timestamp"]
        _assert_no_sensitive_payload(row)


def test_http_unauthorized_export_does_not_create_data_exported(client):
    admin = _register_login(client, "admin")
    owner = _register_login(client, "instructor")
    outsider = _register_login(client, "instructor")
    student = _register_login(client, "student")
    course = _create_course(client, admin["headers"])
    _assign(client, course["id"], owner["id"], admin["headers"])
    session = _create_active_session(client, course["id"], owner["headers"], admin["headers"])

    student_export = client.get(
        f"/api/v1/export/attendance/{course['id']}",
        headers=student["headers"],
        params={"format": "json"},
    )
    assert student_export.status_code == 403

    outsider_export = client.get(
        f"/api/v1/export/session/{session['id']}",
        headers=outsider["headers"],
        params={"format": "csv"},
    )
    assert outsider_export.status_code == 403

    student_events = _list_audit(
        client,
        admin["headers"],
        action=AuditAction.DATA_EXPORTED.value,
        user_id=student["id"],
    )
    outsider_events = _list_audit(
        client,
        admin["headers"],
        action=AuditAction.DATA_EXPORTED.value,
        user_id=outsider["id"],
    )
    assert student_events == []
    assert outsider_events == []


def test_http_checkin_and_export_public_regressions_remain_stable(client):
    admin = _register_login(client, "admin")
    instructor = _register_login(client, "instructor")
    student = _register_login(client, "student")
    course = _create_course(client, admin["headers"])
    _assign(client, course["id"], instructor["id"], admin["headers"])
    _enroll(client, course["id"], student["id"], admin["headers"])
    session = _create_active_session(
        client,
        course["id"],
        instructor["headers"],
        admin["headers"],
        require_liveness_check=False,
    )

    first = client.post(
        "/api/v1/checkins/",
        headers=student["headers"],
        json={
            "session_id": session["id"],
            "latitude": NTU_LAT,
            "longitude": NTU_LNG,
            "device_fingerprint": f"fp_{uuid.uuid4().hex[:10]}",
        },
    )
    assert first.status_code == 201, first.text
    duplicate = client.post(
        "/api/v1/checkins/",
        headers=student["headers"],
        json={
            "session_id": session["id"],
            "latitude": NTU_LAT,
            "longitude": NTU_LNG,
        },
    )
    assert duplicate.status_code == 400

    export_ok = client.get(
        f"/api/v1/export/attendance/{course['id']}",
        headers=instructor["headers"],
        params={"format": "csv"},
    )
    assert export_ok.status_code == 200
    assert "text/csv" in export_ok.headers.get("content-type", "")

    unauthenticated = client.post(
        "/api/v1/checkins/",
        json={"session_id": session["id"], "latitude": NTU_LAT, "longitude": NTU_LNG},
    )
    assert unauthenticated.status_code == 401
    invalid = client.post(
        "/api/v1/checkins/",
        headers=student["headers"],
        json={"latitude": NTU_LAT},
    )
    assert invalid.status_code == 422
