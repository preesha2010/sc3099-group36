"""Course-scoped TA authorization: assigned TAs only, no instructor-only powers."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

PASSWORD = "testpassword123"
NTU_LAT, NTU_LNG = 1.3483, 103.6831


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
        "full_name": full_name or role.title(),
        "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
    }


def _assign(client, course_id: str, user_id: str, admin_headers: dict):
    response = client.post(
        f"/api/v1/admin/courses/{course_id}/instructors",
        headers=admin_headers,
        json={"instructor_id": user_id},
    )
    assert response.status_code in (200, 201), response.text
    return response


def _create_course(client, admin_headers: dict, name: str = "TA Scope Course") -> dict:
    created = client.post(
        "/api/v1/courses/",
        headers=admin_headers,
        json={
            "code": f"TA{uuid.uuid4().hex[:4].upper()}",
            "name": name,
            "semester": "AY2024-25 Sem 1",
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def _create_active_session(client, course_id: str, instructor_headers: dict, admin_headers: dict) -> dict:
    now = datetime.now(timezone.utc)
    created = client.post(
        "/api/v1/sessions/",
        headers=instructor_headers,
        json={
            "course_id": course_id,
            "name": f"TA Session {uuid.uuid4().hex[:6]}",
            "session_type": "lecture",
            "scheduled_start": (now + timedelta(minutes=5)).isoformat(),
            "scheduled_end": (now + timedelta(hours=2)).isoformat(),
            "checkin_opens_at": (now - timedelta(minutes=10)).isoformat(),
            "checkin_closes_at": (now + timedelta(minutes=30)).isoformat(),
            "venue_latitude": NTU_LAT,
            "venue_longitude": NTU_LNG,
            "geofence_radius_meters": 100.0,
            "risk_threshold": 0.1,
        },
    )
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


def _flagged_checkin(client, session_id: str, student_headers: dict):
    created = client.post(
        "/api/v1/checkins/",
        headers=student_headers,
        json={
            "session_id": session_id,
            "latitude": 1.3497,
            "longitude": NTU_LNG,
            "location_accuracy_meters": 10.0,
            "device_fingerprint": f"fp_{uuid.uuid4().hex[:10]}",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "flagged", created.json()
    return created.json()


def _assert_no_pii(response, *values: str) -> None:
    body = response.text
    for value in values:
        if value:
            assert value not in body, f"leaked {value!r} in {body}"


def _two_course_setup(client, auth_headers_admin):
    instructor_a = _register_login(client, "instructor")
    instructor_b = _register_login(client, "instructor")
    student_a = _register_login(client, "student", full_name=f"Alice {uuid.uuid4().hex[:6]}")
    student_b = _register_login(client, "student", full_name=f"Bob {uuid.uuid4().hex[:6]}")
    course_a = _create_course(client, auth_headers_admin, "Course A")
    course_b = _create_course(client, auth_headers_admin, "Course B")
    _assign(client, course_a["id"], instructor_a["id"], auth_headers_admin)
    _assign(client, course_b["id"], instructor_b["id"], auth_headers_admin)
    session_a = _create_active_session(
        client, course_a["id"], instructor_a["headers"], auth_headers_admin
    )
    session_b = _create_active_session(
        client, course_b["id"], instructor_b["headers"], auth_headers_admin
    )
    _enroll(client, course_a["id"], student_a["id"], auth_headers_admin)
    _enroll(client, course_b["id"], student_b["id"], auth_headers_admin)
    checkin_a = _flagged_checkin(client, session_a["id"], student_a["headers"])
    checkin_b = _flagged_checkin(client, session_b["id"], student_b["headers"])
    return {
        "instructor_a": instructor_a,
        "instructor_b": instructor_b,
        "student_a": student_a,
        "student_b": student_b,
        "course_a": course_a,
        "course_b": course_b,
        "session_a": session_a,
        "session_b": session_b,
        "checkin_a": checkin_a,
        "checkin_b": checkin_b,
    }


@pytest.mark.points(0, category="ta_course_scope")
def test_unassigned_ta_denied_unrelated_course_and_session(client, auth_headers_admin):
    data = _two_course_setup(client, auth_headers_admin)
    ta = _register_login(client, "ta")

    roster = client.get(
        f"/api/v1/enrollments/course/{data['course_a']['id']}",
        headers=ta["headers"],
    )
    assert roster.status_code == 403, roster.text
    _assert_no_pii(roster, data["student_a"]["email"], data["student_a"]["full_name"])

    session_list = client.get(
        f"/api/v1/checkins/session/{data['session_a']['id']}",
        headers=ta["headers"],
    )
    assert session_list.status_code == 403, session_list.text
    _assert_no_pii(session_list, data["student_a"]["email"], data["student_a"]["full_name"])

    detail = client.get(f"/api/v1/checkins/{data['checkin_a']['id']}", headers=ta["headers"])
    assert detail.status_code == 403, detail.text
    _assert_no_pii(detail, data["student_a"]["email"])

    stats = client.get(f"/api/v1/stats/sessions/{data['session_a']['id']}", headers=ta["headers"])
    assert stats.status_code == 403, stats.text

    sessions = client.get("/api/v1/sessions/", headers=ta["headers"])
    assert sessions.status_code == 403, sessions.text
    _assert_no_pii(sessions, data["student_a"]["email"], data["student_b"]["email"])


@pytest.mark.points(0, category="ta_course_scope")
def test_assigned_ta_can_access_own_course_session(client, auth_headers_admin):
    data = _two_course_setup(client, auth_headers_admin)
    ta = _register_login(client, "ta")
    _assign(client, data["course_a"]["id"], ta["id"], auth_headers_admin)

    roster = client.get(
        f"/api/v1/enrollments/course/{data['course_a']['id']}",
        headers=ta["headers"],
    )
    assert roster.status_code == 200, roster.text
    emails = {row["student_email"] for row in roster.json()["students"]}
    assert data["student_a"]["email"] in emails
    assert data["student_b"]["email"] not in emails

    session_list = client.get(
        f"/api/v1/checkins/session/{data['session_a']['id']}",
        headers=ta["headers"],
    )
    assert session_list.status_code == 200, session_list.text
    assert any(row["id"] == data["checkin_a"]["id"] for row in session_list.json())

    detail = client.get(f"/api/v1/checkins/{data['checkin_a']['id']}", headers=ta["headers"])
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == data["checkin_a"]["id"]

    stats = client.get(f"/api/v1/stats/sessions/{data['session_a']['id']}", headers=ta["headers"])
    assert stats.status_code == 200, stats.text

    flagged = client.get("/api/v1/checkins/flagged", headers=ta["headers"])
    assert flagged.status_code == 200, flagged.text
    flagged_ids = {row["id"] for row in flagged.json()["items"]}
    assert data["checkin_a"]["id"] in flagged_ids
    assert data["checkin_b"]["id"] not in flagged_ids


@pytest.mark.points(0, category="ta_course_scope")
def test_ta_cannot_see_or_review_other_course_flagged(client, auth_headers_admin):
    data = _two_course_setup(client, auth_headers_admin)
    ta = _register_login(client, "ta")
    _assign(client, data["course_a"]["id"], ta["id"], auth_headers_admin)

    other_roster = client.get(
        f"/api/v1/enrollments/course/{data['course_b']['id']}",
        headers=ta["headers"],
    )
    assert other_roster.status_code == 403, other_roster.text
    _assert_no_pii(other_roster, data["student_b"]["email"], data["student_b"]["full_name"])

    other_session = client.get(
        f"/api/v1/checkins/session/{data['session_b']['id']}",
        headers=ta["headers"],
    )
    assert other_session.status_code == 403, other_session.text
    _assert_no_pii(other_session, data["student_b"]["email"], data["student_b"]["full_name"])

    other_detail = client.get(
        f"/api/v1/checkins/{data['checkin_b']['id']}",
        headers=ta["headers"],
    )
    assert other_detail.status_code == 403, other_detail.text
    _assert_no_pii(other_detail, data["student_b"]["email"])

    other_stats = client.get(
        f"/api/v1/stats/sessions/{data['session_b']['id']}",
        headers=ta["headers"],
    )
    assert other_stats.status_code == 403, other_stats.text

    other_flagged_course = client.get(
        "/api/v1/checkins/flagged",
        headers=ta["headers"],
        params={"course_id": data["course_b"]["id"]},
    )
    assert other_flagged_course.status_code == 403, other_flagged_course.text
    _assert_no_pii(other_flagged_course, data["student_b"]["email"], data["student_b"]["full_name"])

    other_flagged_session = client.get(
        "/api/v1/checkins/flagged",
        headers=ta["headers"],
        params={"session_id": data["session_b"]["id"]},
    )
    assert other_flagged_session.status_code == 403, other_flagged_session.text
    _assert_no_pii(other_flagged_session, data["student_b"]["email"], data["student_b"]["full_name"])

    review = client.post(
        f"/api/v1/checkins/{data['checkin_b']['id']}/review",
        headers=ta["headers"],
        json={"status": "approved", "review_notes": "nope"},
    )
    assert review.status_code == 403, review.text
    still = client.get(
        f"/api/v1/checkins/{data['checkin_b']['id']}",
        headers=data["instructor_b"]["headers"],
    )
    assert still.status_code == 200, still.text
    assert still.json()["status"] == "flagged"

    own_review = client.post(
        f"/api/v1/checkins/{data['checkin_a']['id']}/review",
        headers=ta["headers"],
        json={"status": "approved", "review_notes": "ok"},
    )
    assert own_review.status_code == 200, own_review.text
    assert own_review.json()["status"] == "approved"


@pytest.mark.points(0, category="ta_course_scope")
def test_ta_cannot_perform_instructor_admin_operations(client, auth_headers_admin):
    data = _two_course_setup(client, auth_headers_admin)
    ta = _register_login(client, "ta")
    _assign(client, data["course_a"]["id"], ta["id"], auth_headers_admin)
    extra_student = _register_login(client, "student")

    enroll = client.post(
        "/api/v1/enrollments/",
        headers=ta["headers"],
        json={"student_id": extra_student["id"], "course_id": data["course_a"]["id"]},
    )
    assert enroll.status_code == 403, enroll.text

    export_course = client.get(
        f"/api/v1/export/attendance/{data['course_a']['id']}",
        headers=ta["headers"],
        params={"format": "json"},
    )
    assert export_course.status_code == 403, export_course.text

    export_session = client.get(
        f"/api/v1/export/session/{data['session_a']['id']}",
        headers=ta["headers"],
        params={"format": "json"},
    )
    assert export_session.status_code == 403, export_session.text

    course_stats = client.get(
        f"/api/v1/stats/courses/{data['course_a']['id']}",
        headers=ta["headers"],
    )
    assert course_stats.status_code == 403, course_stats.text

    overview = client.get("/api/v1/stats/overview", headers=ta["headers"])
    assert overview.status_code == 403, overview.text

    all_checkins = client.get("/api/v1/checkins/", headers=ta["headers"])
    assert all_checkins.status_code == 403, all_checkins.text

    create_session = client.post(
        "/api/v1/sessions/",
        headers=ta["headers"],
        json={
            "course_id": data["course_a"]["id"],
            "name": "TA should not create",
            "session_type": "lecture",
            "scheduled_start": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "scheduled_end": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        },
    )
    assert create_session.status_code == 403, create_session.text


@pytest.mark.points(0, category="ta_course_scope")
def test_admin_assign_and_revoke_ta(client, auth_headers_admin):
    data = _two_course_setup(client, auth_headers_admin)
    ta = _register_login(client, "ta")

    assigned = _assign(client, data["course_a"]["id"], ta["id"], auth_headers_admin)
    body = assigned.json()
    assert body["course_id"] == data["course_a"]["id"]
    assert body["instructor_id"] == ta["id"]
    assert body["is_active"] is True
    assert "instructor_email" in body
    assert "assigned_at" in body

    listed = client.get(
        f"/api/v1/admin/courses/{data['course_a']['id']}/instructors",
        headers=auth_headers_admin,
    )
    assert listed.status_code == 200, listed.text
    assert any(
        row["instructor_id"] == ta["id"] and row["is_active"] is True
        for row in listed.json()["instructors"]
    )

    roster = client.get(
        f"/api/v1/enrollments/course/{data['course_a']['id']}",
        headers=ta["headers"],
    )
    assert roster.status_code == 200, roster.text

    revoked = client.delete(
        f"/api/v1/admin/courses/{data['course_a']['id']}/instructors/{ta['id']}",
        headers=auth_headers_admin,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["is_active"] is False
    assert revoked.json()["instructor_id"] == ta["id"]

    denied = client.get(
        f"/api/v1/enrollments/course/{data['course_a']['id']}",
        headers=ta["headers"],
    )
    assert denied.status_code == 403, denied.text
    _assert_no_pii(denied, data["student_a"]["email"], data["student_a"]["full_name"])

    student = _register_login(client, "student")
    not_staff = client.post(
        f"/api/v1/admin/courses/{data['course_a']['id']}/instructors",
        headers=auth_headers_admin,
        json={"instructor_id": student["id"]},
    )
    assert not_staff.status_code == 400, not_staff.text


@pytest.mark.points(0, category="ta_course_scope")
def test_instructor_admin_behavior_unchanged(
    client, auth_headers_admin, auth_headers_instructor, test_session, test_instructor, test_course
):
    listed_instructor = client.get("/api/v1/sessions/", headers=auth_headers_instructor)
    assert listed_instructor.status_code == 200, listed_instructor.text
    assert "items" in listed_instructor.json()

    listed_admin = client.get("/api/v1/sessions/", headers=auth_headers_admin)
    assert listed_admin.status_code == 200, listed_admin.text

    owner_stats = client.get(
        f"/api/v1/stats/sessions/{test_session['id']}",
        headers=auth_headers_instructor,
    )
    assert owner_stats.status_code == 200, owner_stats.text

    admin_stats = client.get(
        f"/api/v1/stats/sessions/{test_session['id']}",
        headers=auth_headers_admin,
    )
    assert admin_stats.status_code == 200, admin_stats.text

    _assign(client, test_course["id"], test_instructor["id"], auth_headers_admin)
    instructor_roster = client.get(
        f"/api/v1/enrollments/course/{test_course['id']}",
        headers=auth_headers_instructor,
    )
    assert instructor_roster.status_code == 200, instructor_roster.text

    instructor_flagged = client.get("/api/v1/checkins/flagged", headers=auth_headers_instructor)
    assert instructor_flagged.status_code == 200, instructor_flagged.text
    assert "items" in instructor_flagged.json()
