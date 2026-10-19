"""Targeted HTTP tests for Module 2 routes the public suite barely covers.

These hit the running backend. They do not change application code.
"""
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest


def _email(role: str) -> str:
    return f"{role}_{uuid.uuid4().hex[:10]}@test.com"


def _register_login(client, role: str, full_name: str | None = None) -> dict:
    email = _email(role)
    password = "testpassword123"
    register = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": full_name or role.title(),
            "role": role,
        },
    )
    assert register.status_code == 201, register.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {
        "id": register.json()["id"],
        "email": email,
        "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
    }


def _create_session(client, course_id: str, instructor_headers: dict, admin_headers: dict, **extra) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    payload = {
        "course_id": course_id,
        "name": f"Untested {uuid.uuid4().hex[:6]}",
        "session_type": "lecture",
        "scheduled_start": (now + timedelta(minutes=5)).isoformat() + "Z",
        "scheduled_end": (now + timedelta(hours=2)).isoformat() + "Z",
        "checkin_opens_at": (now - timedelta(minutes=10)).isoformat() + "Z",
        "checkin_closes_at": (now + timedelta(minutes=30)).isoformat() + "Z",
        "require_liveness_check": True,
        "require_face_match": False,
        "risk_threshold": 0.5,
        "geofence_radius_meters": 100.0,
        "venue_latitude": 1.3483,
        "venue_longitude": 103.6831,
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


def _checkin(client, session_id: str, student_headers: dict, lat=1.3483, lng=103.6831) -> object:
    return client.post(
        "/api/v1/checkins/",
        headers=student_headers,
        json={
            "session_id": session_id,
            "latitude": lat,
            "longitude": lng,
            "location_accuracy_meters": 10.0,
            "device_fingerprint": f"fp_{uuid.uuid4().hex[:10]}",
        },
    )


class TestCheckinGetAppealReview:
    def test_owner_can_get_checkin_details(
        self, client, test_session, test_enrollment, auth_headers_student, test_student
    ):
        created = _checkin(client, test_session["id"], auth_headers_student)
        assert created.status_code == 201, created.text
        checkin_id = created.json()["id"]

        got = client.get(f"/api/v1/checkins/{checkin_id}", headers=auth_headers_student)
        assert got.status_code == 200, got.text
        data = got.json()
        assert data["id"] == checkin_id
        assert data["student_id"] == test_student["id"]
        assert data["session_id"] == test_session["id"]
        assert "risk_signals" in data
        assert "risk_factors" in data
        assert "status" in data

        unauth = client.get(f"/api/v1/checkins/{checkin_id}")
        assert unauth.status_code in (401, 403)

        missing = client.get(
            "/api/v1/checkins/00000000-0000-0000-0000-000000000000",
            headers=auth_headers_student,
        )
        assert missing.status_code == 404

    def test_other_student_cannot_get_or_appeal(
        self, client, test_session, test_enrollment, auth_headers_student
    ):
        created = _checkin(client, test_session["id"], auth_headers_student)
        assert created.status_code == 201, created.text
        checkin_id = created.json()["id"]
        other = _register_login(client, "student")

        got = client.get(f"/api/v1/checkins/{checkin_id}", headers=other["headers"])
        assert got.status_code == 403

        appealed = client.post(
            f"/api/v1/checkins/{checkin_id}/appeal",
            headers=other["headers"],
            json={"appeal_reason": "not mine"},
        )
        assert appealed.status_code == 403

    def test_cannot_appeal_approved_checkin(
        self, client, test_session, test_enrollment, auth_headers_student
    ):
        created = _checkin(client, test_session["id"], auth_headers_student)
        assert created.status_code == 201, created.text
        assert created.json()["status"] in ("pending", "approved", "flagged")
        if created.json()["status"] not in ("rejected", "flagged"):
            appealed = client.post(
                f"/api/v1/checkins/{created.json()['id']}/appeal",
                headers=auth_headers_student,
                json={"appeal_reason": "I was there"},
            )
            assert appealed.status_code == 400

        missing_reason = client.post(
            f"/api/v1/checkins/{created.json()['id']}/appeal",
            headers=auth_headers_student,
            json={},
        )
        assert missing_reason.status_code == 422

    def test_rejected_checkin_appeal_and_owner_review(
        self,
        client,
        test_course,
        test_student,
        test_enrollment,
        auth_headers_student,
        auth_headers_instructor,
        auth_headers_admin,
    ):
        session = _create_session(
            client, test_course["id"], auth_headers_instructor, auth_headers_admin
        )
        created = _checkin(
            client, session["id"], auth_headers_student, lat=1.3510, lng=103.6831
        )
        assert created.status_code == 201, created.text
        assert created.json()["status"] == "rejected", created.json()
        checkin_id = created.json()["id"]

        appealed = client.post(
            f"/api/v1/checkins/{checkin_id}/appeal",
            headers=auth_headers_student,
            json={"appeal_reason": "GPS drifted inside the building"},
        )
        assert appealed.status_code == 200, appealed.text
        body = appealed.json()
        assert body["id"] == checkin_id
        assert body["status"] == "appealed"
        assert body["appeal_reason"]
        assert body["appealed_at"]

        again = client.post(
            f"/api/v1/checkins/{checkin_id}/appeal",
            headers=auth_headers_student,
            json={"appeal_reason": "second try"},
        )
        assert again.status_code == 400

        student_review = client.post(
            f"/api/v1/checkins/{checkin_id}/review",
            headers=auth_headers_student,
            json={"status": "approved", "review_notes": "nope"},
        )
        assert student_review.status_code in (401, 403)

        bad_status = client.post(
            f"/api/v1/checkins/{checkin_id}/review",
            headers=auth_headers_instructor,
            json={"status": "flagged", "review_notes": "wrong"},
        )
        assert bad_status.status_code == 400

        other_instructor = _register_login(client, "instructor")
        other_review = client.post(
            f"/api/v1/checkins/{checkin_id}/review",
            headers=other_instructor["headers"],
            json={"status": "approved", "review_notes": "not my course"},
        )
        assert other_review.status_code == 403

        reviewed = client.post(
            f"/api/v1/checkins/{checkin_id}/review",
            headers=auth_headers_instructor,
            json={"status": "approved", "review_notes": "Nearby WiFi confirms presence"},
        )
        assert reviewed.status_code == 200, reviewed.text
        data = reviewed.json()
        assert data["status"] == "approved"
        assert data["reviewed_by_id"]
        assert data["reviewed_at"]
        assert "GPS" in data["review_notes"] or "WiFi" in data["review_notes"]

        persisted = client.get(f"/api/v1/checkins/{checkin_id}", headers=auth_headers_student)
        assert persisted.status_code == 200
        assert persisted.json()["status"] == "approved"
        assert persisted.json()["reviewed_by_id"] == data["reviewed_by_id"]

    def test_flagged_checkin_with_low_threshold(
        self,
        client,
        test_course,
        test_enrollment,
        auth_headers_student,
        auth_headers_instructor,
        auth_headers_admin,
    ):
        session = _create_session(
            client,
            test_course["id"],
            auth_headers_instructor,
            auth_headers_admin,
            risk_threshold=0.1,
        )
        created = _checkin(
            client, session["id"], auth_headers_student, lat=1.3497, lng=103.6831
        )
        assert created.status_code == 201, created.text
        assert created.json()["status"] == "flagged", created.json()

        flagged = client.get(
            "/api/v1/checkins/flagged",
            headers=auth_headers_instructor,
            params={"session_id": session["id"]},
        )
        assert flagged.status_code == 200, flagged.text
        payload = flagged.json()
        items = payload["items"] if isinstance(payload, dict) else payload
        assert any(row["id"] == created.json()["id"] for row in items)


class TestDevicePatchDelete:
    def test_owner_patch_name_and_soft_delete(self, client, auth_headers_student):
        fingerprint = f"dev_{uuid.uuid4().hex[:12]}"
        registered = client.post(
            "/api/v1/devices/register",
            headers=auth_headers_student,
            json={
                "device_fingerprint": fingerprint,
                "device_name": "Original Phone",
                "platform": "ios",
            },
        )
        assert registered.status_code == 201, registered.text
        device_id = registered.json()["id"]
        assert registered.json()["is_trusted"] is False

        patched = client.patch(
            f"/api/v1/devices/{device_id}",
            headers=auth_headers_student,
            json={"device_name": "Primary Phone"},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["device_name"] == "Primary Phone"
        assert patched.json()["id"] == device_id

        trust_denied = client.patch(
            f"/api/v1/devices/{device_id}",
            headers=auth_headers_student,
            json={"is_trusted": True},
        )
        assert trust_denied.status_code == 403

        deleted = client.delete(f"/api/v1/devices/{device_id}", headers=auth_headers_student)
        assert deleted.status_code == 204

        listed = client.get("/api/v1/devices/my-devices", headers=auth_headers_student)
        assert listed.status_code == 200
        mine = [row for row in listed.json() if row["id"] == device_id]
        assert mine
        assert mine[0]["is_active"] is False

    def test_admin_can_trust_device_and_stranger_cannot_patch(
        self, client, auth_headers_student, auth_headers_admin
    ):
        registered = client.post(
            "/api/v1/devices/register",
            headers=auth_headers_student,
            json={
                "device_fingerprint": f"dev_{uuid.uuid4().hex[:12]}",
                "device_name": "Trust Me",
                "platform": "android",
            },
        )
        assert registered.status_code == 201, registered.text
        device_id = registered.json()["id"]

        other = _register_login(client, "student")
        denied = client.patch(
            f"/api/v1/devices/{device_id}",
            headers=other["headers"],
            json={"device_name": "Stolen"},
        )
        assert denied.status_code == 403

        delete_denied = client.delete(f"/api/v1/devices/{device_id}", headers=other["headers"])
        assert delete_denied.status_code == 403

        trusted = client.patch(
            f"/api/v1/devices/{device_id}",
            headers=auth_headers_admin,
            json={"is_trusted": True},
        )
        assert trusted.status_code == 200, trusted.text
        assert trusted.json()["is_trusted"] is True
        assert trusted.json()["trust_score"] == "high"

        missing = client.patch(
            "/api/v1/devices/00000000-0000-0000-0000-000000000000",
            headers=auth_headers_student,
            json={"device_name": "nope"},
        )
        assert missing.status_code == 404


class TestEnrollmentBulkDelete:
    def test_bulk_enroll_and_delete(
        self,
        client,
        test_course,
        test_student,
        test_enrollment,
        test_session,
        auth_headers_instructor,
        auth_headers_admin,
    ):
        other = _register_login(client, "student")
        unknown = _email("missing")
        bulk = client.post(
            "/api/v1/enrollments/bulk",
            headers=auth_headers_instructor,
            json={
                "course_id": test_course["id"],
                "student_emails": [test_student["email"], other["email"], unknown],
                "create_accounts": False,
            },
        )
        assert bulk.status_code == 200, bulk.text
        data = bulk.json()
        assert "enrolled" in data
        assert "already_enrolled" in data
        assert "not_found" in data
        assert "created" in data
        assert "details" in data
        statuses = {row["email"]: row["status"] for row in data["details"]}
        assert statuses[test_student["email"].lower()] == "already_enrolled"
        assert statuses[other["email"].lower()] == "enrolled"
        assert statuses[unknown.lower()] == "not_found"
        assert data["not_found"] >= 1
        assert data["enrolled"] >= 1

        listed = client.get(
            f"/api/v1/enrollments/course/{test_course['id']}",
            headers=auth_headers_instructor,
        )
        assert listed.status_code == 200, listed.text
        roster = listed.json()
        assert roster["course_id"] == test_course["id"]
        student_ids = {row["student_id"] for row in roster["students"]}
        assert other["id"] in student_ids
        enrollment_id = next(
            row["id"] for row in roster["students"] if row["student_id"] == other["id"]
        )

        dropped = client.delete(
            f"/api/v1/enrollments/{enrollment_id}",
            headers=auth_headers_instructor,
        )
        assert dropped.status_code == 204

        after = client.get(
            f"/api/v1/enrollments/course/{test_course['id']}",
            headers=auth_headers_instructor,
        )
        remaining = {row["student_id"] for row in after.json()["students"]}
        assert other["id"] not in remaining

        mine = client.get("/api/v1/enrollments/my-enrollments", headers=other["headers"])
        assert mine.status_code == 200
        own = [row for row in mine.json() if row["id"] == enrollment_id]
        assert own
        assert own[0]["is_active"] is False

        missing = client.delete(
            "/api/v1/enrollments/00000000-0000-0000-0000-000000000000",
            headers=auth_headers_admin,
        )
        assert missing.status_code == 404

        student_forbidden_bulk = client.post(
            "/api/v1/enrollments/bulk",
            headers=other["headers"],
            json={"course_id": test_course["id"], "student_emails": [other["email"]]},
        )
        assert student_forbidden_bulk.status_code in (401, 403)

        unknown_course = client.post(
            "/api/v1/enrollments/bulk",
            headers=auth_headers_admin,
            json={
                "course_id": "00000000-0000-0000-0000-000000000000",
                "student_emails": [other["email"]],
            },
        )
        assert unknown_course.status_code == 404

        outsider_instructor = _register_login(client, "instructor")
        outsider_bulk = client.post(
            "/api/v1/enrollments/bulk",
            headers=outsider_instructor["headers"],
            json={"course_id": test_course["id"], "student_emails": [other["email"]]},
        )
        assert outsider_bulk.status_code == 403, outsider_bulk.text

    def test_other_instructor_cannot_drop_unenrolled_course(
        self, client, test_course, test_student, test_enrollment, auth_headers_admin
    ):
        listed = client.get(
            f"/api/v1/enrollments/course/{test_course['id']}",
            headers=auth_headers_admin,
        )
        assert listed.status_code == 200
        enrollment_id = next(
            row["id"] for row in listed.json()["students"] if row["student_id"] == test_student["id"]
        )
        outsider = _register_login(client, "instructor")
        denied = client.delete(
            f"/api/v1/enrollments/{enrollment_id}",
            headers=outsider["headers"],
        )
        assert denied.status_code == 403

    def test_student_cannot_drop_own_enrollment(
        self, client, test_course, auth_headers_admin
    ):
        student = _register_login(client, "student")
        enrolled = client.post(
            "/api/v1/enrollments/",
            headers=auth_headers_admin,
            json={"student_id": student["id"], "course_id": test_course["id"]},
        )
        assert enrolled.status_code == 201, enrolled.text
        enrollment_id = enrolled.json()["id"]
        dropped = client.delete(
            f"/api/v1/enrollments/{enrollment_id}",
            headers=student["headers"],
        )
        assert dropped.status_code == 403, dropped.text
        still = client.get("/api/v1/enrollments/my-enrollments", headers=student["headers"])
        assert still.status_code == 200
        own = [row for row in still.json() if row["id"] == enrollment_id]
        assert own and own[0]["is_active"] is True


class TestEnrollmentCreateAndRosterAuthz:
    def test_teaching_instructor_and_admin_can_enroll(
        self,
        client,
        test_course,
        test_session,
        auth_headers_instructor,
        auth_headers_admin,
    ):
        student = _register_login(client, "student")
        created = client.post(
            "/api/v1/enrollments/",
            headers=auth_headers_instructor,
            json={"student_id": student["id"], "course_id": test_course["id"]},
        )
        assert created.status_code == 201, created.text
        data = created.json()
        assert data["student_id"] == student["id"]
        assert data["course_id"] == test_course["id"]
        assert data["is_active"] is True

        duplicate = client.post(
            "/api/v1/enrollments/",
            headers=auth_headers_admin,
            json={"student_id": student["id"], "course_id": test_course["id"]},
        )
        assert duplicate.status_code == 400

        missing_student = client.post(
            "/api/v1/enrollments/",
            headers=auth_headers_admin,
            json={
                "student_id": "00000000-0000-0000-0000-000000000000",
                "course_id": test_course["id"],
            },
        )
        assert missing_student.status_code == 404

        missing_course = client.post(
            "/api/v1/enrollments/",
            headers=auth_headers_admin,
            json={
                "student_id": student["id"],
                "course_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert missing_course.status_code == 404

    def test_unrelated_instructor_cannot_create_enrollment(
        self, client, test_course, auth_headers_admin
    ):
        student = _register_login(client, "student")
        outsider = _register_login(client, "instructor")
        denied = client.post(
            "/api/v1/enrollments/",
            headers=outsider["headers"],
            json={"student_id": student["id"], "course_id": test_course["id"]},
        )
        assert denied.status_code == 403, denied.text

        student_denied = client.post(
            "/api/v1/enrollments/",
            headers=student["headers"],
            json={"student_id": student["id"], "course_id": test_course["id"]},
        )
        assert student_denied.status_code in (401, 403)

        ta = _register_login(client, "ta")
        ta_denied = client.post(
            "/api/v1/enrollments/",
            headers=ta["headers"],
            json={"student_id": student["id"], "course_id": test_course["id"]},
        )
        assert ta_denied.status_code in (401, 403)

    def test_course_roster_teaching_instructor_ta_and_unrelated(
        self,
        client,
        test_course,
        test_enrollment,
        test_session,
        auth_headers_instructor,
        auth_headers_admin,
        auth_headers_student,
    ):
        owner = client.get(
            f"/api/v1/enrollments/course/{test_course['id']}",
            headers=auth_headers_instructor,
        )
        assert owner.status_code == 200, owner.text
        assert owner.json()["course_id"] == test_course["id"]

        admin_ok = client.get(
            f"/api/v1/enrollments/course/{test_course['id']}",
            headers=auth_headers_admin,
        )
        assert admin_ok.status_code == 200, admin_ok.text

        ta = _register_login(client, "ta")
        ta_ok = client.get(
            f"/api/v1/enrollments/course/{test_course['id']}",
            headers=ta["headers"],
        )
        assert ta_ok.status_code == 200, ta_ok.text

        outsider = _register_login(client, "instructor")
        denied = client.get(
            f"/api/v1/enrollments/course/{test_course['id']}",
            headers=outsider["headers"],
        )
        assert denied.status_code == 403, denied.text

        student_denied = client.get(
            f"/api/v1/enrollments/course/{test_course['id']}",
            headers=auth_headers_student,
        )
        assert student_denied.status_code in (401, 403)

        missing = client.get(
            "/api/v1/enrollments/course/00000000-0000-0000-0000-000000000000",
            headers=auth_headers_admin,
        )
        assert missing.status_code == 404

    def test_course_roster_is_active_and_search_filters(
        self,
        client,
        test_course,
        test_session,
        auth_headers_instructor,
        auth_headers_admin,
    ):
        token = uuid.uuid4().hex[:6]
        alice = _register_login(client, "student", full_name=f"Alice Filter{token}")
        bob = _register_login(client, "student", full_name=f"Bob Filter{token}")
        for student in (alice, bob):
            enrolled = client.post(
                "/api/v1/enrollments/",
                headers=auth_headers_instructor,
                json={"student_id": student["id"], "course_id": test_course["id"]},
            )
            assert enrolled.status_code == 201, enrolled.text
        roster = client.get(
            f"/api/v1/enrollments/course/{test_course['id']}",
            headers=auth_headers_instructor,
        )
        assert roster.status_code == 200, roster.text
        bob_enrollment_id = next(
            row["id"] for row in roster.json()["students"] if row["student_id"] == bob["id"]
        )
        dropped = client.delete(
            f"/api/v1/enrollments/{bob_enrollment_id}",
            headers=auth_headers_instructor,
        )
        assert dropped.status_code == 204

        active = client.get(
            f"/api/v1/enrollments/course/{test_course['id']}",
            headers=auth_headers_instructor,
        )
        assert active.status_code == 200
        active_ids = {row["student_id"] for row in active.json()["students"]}
        assert alice["id"] in active_ids
        assert bob["id"] not in active_ids
        assert all(row["is_active"] is True for row in active.json()["students"])

        inactive = client.get(
            f"/api/v1/enrollments/course/{test_course['id']}",
            headers=auth_headers_instructor,
            params={"is_active": False},
        )
        assert inactive.status_code == 200, inactive.text
        inactive_ids = {row["student_id"] for row in inactive.json()["students"]}
        assert bob["id"] in inactive_ids
        assert alice["id"] not in inactive_ids
        assert all(row["is_active"] is False for row in inactive.json()["students"])

        by_name = client.get(
            f"/api/v1/enrollments/course/{test_course['id']}",
            headers=auth_headers_instructor,
            params={"search": f"Alice Filter{token}"},
        )
        assert by_name.status_code == 200
        name_ids = {row["student_id"] for row in by_name.json()["students"]}
        assert name_ids == {alice["id"]}

        by_email = client.get(
            f"/api/v1/enrollments/course/{test_course['id']}",
            headers=auth_headers_instructor,
            params={"search": alice["email"]},
        )
        assert by_email.status_code == 200
        email_ids = {row["student_id"] for row in by_email.json()["students"]}
        assert alice["id"] in email_ids

        combined = client.get(
            f"/api/v1/enrollments/course/{test_course['id']}",
            headers=auth_headers_instructor,
            params={"is_active": False, "search": f"Bob Filter{token}"},
        )
        assert combined.status_code == 200
        combined_ids = {row["student_id"] for row in combined.json()["students"]}
        assert combined_ids == {bob["id"]}

        empty = client.get(
            f"/api/v1/enrollments/course/{test_course['id']}",
            headers=auth_headers_instructor,
            params={"search": "zzzz-no-such-student"},
        )
        assert empty.status_code == 200
        assert empty.json()["students"] == []
        assert empty.json()["total_enrolled"] == 0

        outsider = _register_login(client, "instructor")
        denied = client.get(
            f"/api/v1/enrollments/course/{test_course['id']}",
            headers=outsider["headers"],
            params={"search": "Alice"},
        )
        assert denied.status_code == 403


class TestCourseAttendanceExport:
    def test_export_json_and_csv(
        self,
        client,
        test_course,
        test_session,
        test_enrollment,
        auth_headers_student,
        auth_headers_instructor,
        auth_headers_admin,
    ):
        created = _checkin(client, test_session["id"], auth_headers_student)
        assert created.status_code == 201, created.text

        json_resp = client.get(
            f"/api/v1/export/attendance/{test_course['id']}",
            headers=auth_headers_instructor,
            params={"format": "json"},
        )
        assert json_resp.status_code == 200, json_resp.text
        rows = json_resp.json()
        assert isinstance(rows, list)
        assert rows
        sample = rows[0]
        for key in (
            "student_id",
            "student_name",
            "student_email",
            "session_date",
            "session_name",
            "status",
            "checked_in_at",
            "risk_score",
        ):
            assert key in sample

        csv_resp = client.get(
            f"/api/v1/export/attendance/{test_course['id']}",
            headers=auth_headers_instructor,
            params={"format": "csv"},
        )
        assert csv_resp.status_code == 200, csv_resp.text
        assert "text/csv" in csv_resp.headers.get("content-type", "")
        parsed = list(csv.reader(io.StringIO(csv_resp.text)))
        assert parsed[0] == [
            "student_id",
            "student_name",
            "student_email",
            "session_date",
            "session_name",
            "status",
            "checked_in_at",
            "risk_score",
        ]
        assert len(parsed) >= 2

        student_denied = client.get(
            f"/api/v1/export/attendance/{test_course['id']}",
            headers=auth_headers_student,
            params={"format": "json"},
        )
        assert student_denied.status_code in (401, 403)

        bad_format = client.get(
            f"/api/v1/export/attendance/{test_course['id']}",
            headers=auth_headers_instructor,
            params={"format": "xml"},
        )
        assert bad_format.status_code == 400

        missing = client.get(
            "/api/v1/export/attendance/00000000-0000-0000-0000-000000000000",
            headers=auth_headers_admin,
            params={"format": "json"},
        )
        assert missing.status_code == 404

        outsider = _register_login(client, "instructor")
        other_course = client.get(
            f"/api/v1/export/attendance/{test_course['id']}",
            headers=outsider["headers"],
            params={"format": "json"},
        )
        assert other_course.status_code == 403, other_course.text

        admin_ok = client.get(
            f"/api/v1/export/attendance/{test_course['id']}",
            headers=auth_headers_admin,
            params={"format": "json"},
        )
        assert admin_ok.status_code == 200, admin_ok.text


class TestOtherUntestedRoutes:
    def test_put_and_delete_course_admin_only(self, client, auth_headers_admin, auth_headers_instructor):
        created = client.post(
            "/api/v1/courses/",
            headers=auth_headers_admin,
            json={
                "code": f"UT{uuid.uuid4().hex[:4].upper()}",
                "name": "Untested Course",
                "semester": "AY2024-25 Sem 1",
            },
        )
        assert created.status_code == 201, created.text
        course_id = created.json()["id"]

        instructor_denied = client.put(
            f"/api/v1/courses/{course_id}",
            headers=auth_headers_instructor,
            json={"name": "Hijack"},
        )
        assert instructor_denied.status_code in (401, 403)

        updated = client.put(
            f"/api/v1/courses/{course_id}",
            headers=auth_headers_admin,
            json={"name": "Renamed Course"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "Renamed Course"

        deleted = client.delete(f"/api/v1/courses/{course_id}", headers=auth_headers_admin)
        assert deleted.status_code == 204

        after = client.get(f"/api/v1/courses/{course_id}", headers=auth_headers_admin)
        assert after.status_code in (200, 404)
        if after.status_code == 200:
            assert after.json().get("is_active") is False

    def test_logout_requires_auth(self, client, auth_headers_student):
        unauth = client.post("/api/v1/auth/logout")
        assert unauth.status_code in (401, 403)
        ok = client.post("/api/v1/auth/logout", headers=auth_headers_student)
        assert ok.status_code == 200

    def test_get_user_by_id_instructor_scope(
        self, client, test_student, test_enrollment, test_session, auth_headers_instructor
    ):
        allowed = client.get(
            f"/api/v1/users/{test_student['id']}",
            headers=auth_headers_instructor,
        )
        assert allowed.status_code == 200, allowed.text
        outsider = _register_login(client, "instructor")
        denied = client.get(
            f"/api/v1/users/{test_student['id']}",
            headers=outsider["headers"],
        )
        assert denied.status_code == 403


class TestSessionExportAuthz:
    def test_session_export_owner_admin_and_unrelated(
        self,
        client,
        test_session,
        test_enrollment,
        auth_headers_student,
        auth_headers_instructor,
        auth_headers_admin,
    ):
        created = _checkin(client, test_session["id"], auth_headers_student)
        assert created.status_code == 201, created.text

        owner = client.get(
            f"/api/v1/export/session/{test_session['id']}",
            headers=auth_headers_instructor,
            params={"format": "json"},
        )
        assert owner.status_code == 200, owner.text
        assert owner.json()["session_id"] == test_session["id"]

        admin_ok = client.get(
            f"/api/v1/export/session/{test_session['id']}",
            headers=auth_headers_admin,
            params={"format": "json"},
        )
        assert admin_ok.status_code == 200, admin_ok.text

        outsider = _register_login(client, "instructor")
        denied = client.get(
            f"/api/v1/export/session/{test_session['id']}",
            headers=outsider["headers"],
            params={"format": "json"},
        )
        assert denied.status_code == 403, denied.text

        ta = _register_login(client, "ta")
        ta_denied = client.get(
            f"/api/v1/export/session/{test_session['id']}",
            headers=ta["headers"],
            params={"format": "json"},
        )
        assert ta_denied.status_code == 403, ta_denied.text

        student_denied = client.get(
            f"/api/v1/export/session/{test_session['id']}",
            headers=auth_headers_student,
            params={"format": "json"},
        )
        assert student_denied.status_code in (401, 403)

        missing = client.get(
            "/api/v1/export/session/00000000-0000-0000-0000-000000000000",
            headers=auth_headers_admin,
            params={"format": "json"},
        )
        assert missing.status_code == 404
