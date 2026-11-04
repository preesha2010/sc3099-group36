"""Targeted local coverage for published hidden-test categories.

HTTP cases hit the isolated running backend. Unit cases cover Redis fallback
and GPS helpers without touching the shared `saiv` database.
"""
from __future__ import annotations

import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2] / "module2-backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.redis import get_redis  # noqa: E402
from app.middleware import rate_limit as rate_limit_mod  # noqa: E402

PASSWORD = "testpassword123"
NTU_LAT, NTU_LNG = 1.3483, 103.6831


def _email(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}@test.com"


def _register_login(client, role: str = "student") -> dict:
    email = _email(role)
    register = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": role.title(), "role": role},
    )
    assert register.status_code == 201, register.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {
        "id": register.json()["id"],
        "email": email,
        "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
    }


def _enroll(client, admin_headers: dict, student_id: str, course_id: str) -> None:
    response = client.post(
        "/api/v1/admin/enrollments/",
        headers=admin_headers,
        json={"student_id": student_id, "course_id": course_id},
    )
    assert response.status_code in (200, 201), response.text


def _checkin(client, headers: dict, session_id: str, **extra):
    body = {
        "session_id": session_id,
        "latitude": extra.pop("latitude", NTU_LAT),
        "longitude": extra.pop("longitude", NTU_LNG),
        "location_accuracy_meters": extra.pop("location_accuracy_meters", 10.0),
        "device_fingerprint": extra.pop("device_fingerprint", f"fp_{uuid.uuid4().hex[:10]}"),
    }
    body.update(extra)
    return client.post("/api/v1/checkins/", headers=headers, json=body)


def _set_session_qr(session_id: str, secret: str) -> None:
    import psycopg2

    dsn = os.environ.get("DATABASE_URL")
    if not dsn or "/saiv_m2_hidden_verify" not in dsn:
        pytest.skip("QR fixture requires isolated DATABASE_URL=.../saiv_m2_hidden_verify")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sessions SET qr_code_secret = %s WHERE id = %s",
                (secret, session_id),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# GPS spoofing / geofence / QR replay
# ---------------------------------------------------------------------------


class TestGpsGeofenceAndQr:
    def test_gps_beyond_two_geofences_is_rejected(
        self, client, test_session, test_course, auth_headers_admin
    ):
        student = _register_login(client, "student")
        _enroll(client, auth_headers_admin, student["id"], test_course["id"])
        # ~1.1 km north of NTU, still inside the Singapore bounding box.
        response = _checkin(
            client,
            student["headers"],
            test_session["id"],
            latitude=1.3583,
            longitude=NTU_LNG,
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["status"] == "rejected"
        assert data["distance_from_venue_meters"] > 200

    def test_gps_between_one_and_two_radii_stays_under_default_threshold(
        self, client, test_session, test_course, auth_headers_admin
    ):
        student = _register_login(client, "student")
        _enroll(client, auth_headers_admin, student["id"], test_course["id"])
        # ~155 m east of the 100 m geofence: SECURITY lists this as high geo
        # risk, but the stored score is 0.15 * 0.7 plus unknown-device 0.03,
        # which is below the default 0.5 flag threshold.
        response = _checkin(
            client,
            student["headers"],
            test_session["id"],
            latitude=NTU_LAT,
            longitude=103.6845,
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert 100 < (data["distance_from_venue_meters"] or 0) < 200
        assert data["status"] == "approved"
        assert data["risk_score"] < 0.5

    def test_claimed_high_accuracy_does_not_override_geofence(
        self, client, test_session, test_course, auth_headers_admin
    ):
        student = _register_login(client, "student")
        _enroll(client, auth_headers_admin, student["id"], test_course["id"])
        response = _checkin(
            client,
            student["headers"],
            test_session["id"],
            latitude=1.3583,
            longitude=NTU_LNG,
            location_accuracy_meters=1.0,
        )
        assert response.status_code == 201, response.text
        assert response.json()["status"] == "rejected"

    def test_qr_required_wrong_missing_replay_and_second_student(
        self, client, test_session, test_course, auth_headers_admin
    ):
        secret = f"qr_{uuid.uuid4().hex}"
        _set_session_qr(test_session["id"], secret)

        first = _register_login(client, "student")
        second = _register_login(client, "student")
        _enroll(client, auth_headers_admin, first["id"], test_course["id"])
        _enroll(client, auth_headers_admin, second["id"], test_course["id"])

        missing = _checkin(client, first["headers"], test_session["id"])
        assert missing.status_code == 400, missing.text

        wrong = _checkin(client, first["headers"], test_session["id"], qr_code="not-the-secret")
        assert wrong.status_code == 400, wrong.text

        ok = _checkin(client, first["headers"], test_session["id"], qr_code=secret)
        assert ok.status_code == 201, ok.text

        replay = _checkin(client, first["headers"], test_session["id"], qr_code=secret)
        assert replay.status_code == 400, replay.text
        assert "already" in replay.json()["detail"].lower()

        other = _checkin(client, second["headers"], test_session["id"], qr_code=secret)
        assert other.status_code == 201, other.text


# ---------------------------------------------------------------------------
# Cross-course authorization and TA access
# ---------------------------------------------------------------------------


class TestCrossCourseAndTa:
    def test_instructor_cannot_read_other_course_session_checkins(
        self, client, test_session, auth_headers_admin
    ):
        outsider = _register_login(client, "instructor")
        denied = client.get(
            f"/api/v1/checkins/session/{test_session['id']}",
            headers=outsider["headers"],
        )
        assert denied.status_code == 403, denied.text

    def test_ta_can_read_session_checkins_without_assignment(
        self, client, test_session
    ):
        ta = _register_login(client, "ta")
        allowed = client.get(
            f"/api/v1/checkins/session/{test_session['id']}",
            headers=ta["headers"],
        )
        assert allowed.status_code == 200, allowed.text

    def test_instructor_cannot_enroll_into_unassigned_course(
        self, client, test_course, auth_headers_admin
    ):
        instructor = _register_login(client, "instructor")
        student = _register_login(client, "student")
        denied = client.post(
            "/api/v1/enrollments/",
            headers=instructor["headers"],
            json={"student_id": student["id"], "course_id": test_course["id"]},
        )
        assert denied.status_code == 403, denied.text

    def test_ta_cannot_drop_enrollment(
        self, client, test_enrollment, test_course, auth_headers_admin
    ):
        ta = _register_login(client, "ta")
        denied = client.delete(
            f"/api/v1/enrollments/{test_enrollment['id']}",
            headers=ta["headers"],
        )
        assert denied.status_code == 403, denied.text


# ---------------------------------------------------------------------------
# Biometric minimization, consent, audit
# ---------------------------------------------------------------------------


class TestBiometricPrivacyAndAudit:
    def test_face_enroll_requires_consent(self, client):
        student = _register_login(client, "student")
        denied = client.post(
            "/api/v1/users/me/face/enroll",
            headers=student["headers"],
            json={"image": "AAAA"},
        )
        assert denied.status_code == 400, denied.text
        assert "consent" in denied.json()["detail"].lower()

    def test_user_me_does_not_expose_template_or_password(self, client, auth_headers_student):
        response = client.get("/api/v1/users/me", headers=auth_headers_student)
        assert response.status_code == 200, response.text
        data = response.json()
        for banned in (
            "password",
            "hashed_password",
            "face_embedding_hash",
            "face_image",
            "image_data",
            "photo",
        ):
            assert banned not in data

    def test_checkin_and_login_write_audit_rows(
        self, client, test_session, test_course, auth_headers_admin
    ):
        student = _register_login(client, "student")
        _enroll(client, auth_headers_admin, student["id"], test_course["id"])
        checkin = _checkin(client, student["headers"], test_session["id"])
        assert checkin.status_code == 201, checkin.text

        logs = client.get(
            "/api/v1/audit/",
            headers=auth_headers_admin,
            params={"user_id": student["id"], "limit": 50},
        )
        assert logs.status_code == 200, logs.text
        body = logs.json()
        items = body["items"] if isinstance(body, dict) and "items" in body else body
        actions = {row.get("action") for row in items}
        assert "login_success" in actions or "user_created" in actions
        assert any("checkin" in (row.get("action") or "") for row in items)

    def test_audit_logs_reject_mutation(self, client, auth_headers_admin):
        listed = client.get("/api/v1/audit/", headers=auth_headers_admin, params={"limit": 1})
        assert listed.status_code == 200, listed.text
        mutated = client.delete("/api/v1/audit/", headers=auth_headers_admin)
        assert mutated.status_code in (404, 405, 403)


# ---------------------------------------------------------------------------
# Redis fallback and malformed / oversized requests
# ---------------------------------------------------------------------------


class TestRedisFallbackAndMalformed:
    def test_rate_limit_falls_back_to_memory_when_redis_missing(self, monkeypatch):
        monkeypatch.setattr(rate_limit_mod, "get_redis", lambda: None)
        key = f"mem:{uuid.uuid4().hex}"
        assert rate_limit_mod.check_rate_limit(key, 1, 60) is True
        assert rate_limit_mod.check_rate_limit(key, 1, 60) is False

    def test_get_redis_survives_connection_errors(self, monkeypatch):
        import app.core.redis as redis_mod

        redis_mod._client = None

        class Boom:
            def ping(self):
                raise ConnectionError("down")

        monkeypatch.setattr(
            redis_mod.redis.Redis,
            "from_url",
            lambda *args, **kwargs: Boom(),
        )
        assert get_redis() is None
        redis_mod._client = None

    def test_malformed_checkin_bodies(self, client, auth_headers_student, test_session):
        missing = client.post("/api/v1/checkins/", headers=auth_headers_student, json={})
        assert missing.status_code == 422

        raw_headers = dict(auth_headers_student)
        raw_headers["Content-Type"] = "application/json"
        bad_json = client.post("/api/v1/checkins/", headers=raw_headers, content=b"not-json")
        assert bad_json.status_code in (400, 422)

        invalid_coords = _checkin(
            client,
            auth_headers_student,
            test_session["id"],
            latitude=91,
            longitude=103.68,
        )
        assert invalid_coords.status_code == 422

    def test_oversized_enroll_image_does_not_500(self, client):
        student = _register_login(client, "student")
        client.put(
            "/api/v1/users/me",
            headers=student["headers"],
            json={"camera_consent": True},
        )
        huge = "A" * (2 * 1024 * 1024)
        response = client.post(
            "/api/v1/users/me/face/enroll",
            headers=student["headers"],
            json={"image": huge},
            timeout=30.0,
        )
        assert response.status_code == 413, response.text


# ---------------------------------------------------------------------------
# Concurrent and duplicate check-ins
# ---------------------------------------------------------------------------


class TestConcurrentAndDuplicate:
    def test_duplicate_same_student_same_session(
        self, client, test_session, test_course, auth_headers_admin
    ):
        student = _register_login(client, "student")
        _enroll(client, auth_headers_admin, student["id"], test_course["id"])
        first = _checkin(client, student["headers"], test_session["id"])
        assert first.status_code == 201, first.text
        second = _checkin(client, student["headers"], test_session["id"])
        assert second.status_code == 400, second.text

    def test_one_hundred_students_concurrent_checkin(
        self, client, test_session, test_course, auth_headers_admin
    ):
        students = []
        for _ in range(100):
            user = _register_login(client, "student")
            _enroll(client, auth_headers_admin, user["id"], test_course["id"])
            students.append(user)

        def submit(user):
            response = _checkin(client, user["headers"], test_session["id"])
            return response.status_code

        with ThreadPoolExecutor(max_workers=20) as pool:
            codes = list(pool.map(submit, students))

        created = codes.count(201)
        duplicates = codes.count(400)
        assert created == 100, f"expected 100 created, got {created}; codes={set(codes)}"
        assert duplicates == 0

        listed = client.get(
            f"/api/v1/checkins/session/{test_session['id']}",
            headers=auth_headers_admin,
        )
        assert listed.status_code == 200, listed.text
        rows = listed.json()
        items = rows if isinstance(rows, list) else rows.get("items", rows)
        student_ids = {user["id"] for user in students}
        persisted = {row["student_id"] for row in items if row["student_id"] in student_ids}
        assert len(persisted) == 100
