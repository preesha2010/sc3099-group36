"""Spec-gap checks for Module 2 that the public suite does not cover."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest


def _unique_email(role: str) -> str:
    return f"{role}_{uuid.uuid4().hex[:8]}@test.com"


def _register_and_login(client, role: str) -> dict:
    email = _unique_email(role)
    password = "testpassword123"
    register = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": role.title(), "role": role},
    )
    assert register.status_code == 201, register.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {"id": register.json()["id"], "headers": {"Authorization": f"Bearer {token}"}}


def _assign_instructor(client, course_id: str, instructor_id: str, admin_headers: dict) -> None:
    assigned = client.post(
        f"/api/v1/admin/courses/{course_id}/instructors",
        headers=admin_headers,
        json={"instructor_id": instructor_id},
    )
    assert assigned.status_code in (200, 201), assigned.text


@pytest.mark.points(0, category="spec_authz")
def test_session_get_requires_auth(client, test_session):
    response = client.get(f"/api/v1/sessions/{test_session['id']}")
    assert response.status_code == 401


@pytest.mark.points(0, category="spec_authz")
def test_courses_list_requires_auth(client):
    response = client.get("/api/v1/courses/")
    assert response.status_code == 401


@pytest.mark.points(0, category="spec_authz")
def test_instructor_cannot_patch_others_session(client, test_session):
    other = _register_and_login(client, "instructor")
    response = client.patch(
        f"/api/v1/sessions/{test_session['id']}",
        headers=other["headers"],
        json={"name": "Hijacked"},
    )
    assert response.status_code == 403


@pytest.mark.points(0, category="spec_authz")
def test_owner_can_patch_own_session(client, test_session, auth_headers_instructor):
    name = f"Owned {uuid.uuid4().hex[:6]}"
    response = client.patch(
        f"/api/v1/sessions/{test_session['id']}",
        headers=auth_headers_instructor,
        json={"name": name},
    )
    assert response.status_code == 200
    assert response.json()["name"] == name


@pytest.mark.points(0, category="spec_authz")
def test_instructor_cannot_staff_others_session(
    client, test_session, test_enrollment, auth_headers_student
):
    created = client.post(
        "/api/v1/checkins/",
        headers=auth_headers_student,
        json={
            "session_id": test_session["id"],
            "latitude": 1.3483,
            "longitude": 103.6831,
            "device_fingerprint": f"fp_{uuid.uuid4().hex[:8]}",
        },
    )
    assert created.status_code == 201, created.text
    other = _register_and_login(client, "instructor")
    listed = client.get(
        f"/api/v1/checkins/session/{test_session['id']}",
        headers=other["headers"],
    )
    assert listed.status_code == 403
    detail = client.get(
        f"/api/v1/checkins/{created.json()['id']}",
        headers=other["headers"],
    )
    assert detail.status_code == 403
    review = client.post(
        f"/api/v1/checkins/{created.json()['id']}/review",
        headers=other["headers"],
        json={"status": "approved", "review_notes": "nope"},
    )
    assert review.status_code == 403


@pytest.mark.points(0, category="spec_authz")
def test_my_sessions_accepts_query_params(client, auth_headers_student):
    response = client.get(
        "/api/v1/sessions/my-sessions",
        headers=auth_headers_student,
        params={"upcoming": True, "limit": 5},
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.points(0, category="spec_authz")
def test_session_list_includes_spec_fields(client, test_session, auth_headers_instructor):
    response = client.get("/api/v1/sessions/", headers=auth_headers_instructor, params={"limit": 10})
    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    row = next((item for item in items if item["id"] == test_session["id"]), items[0])
    for key in ("course_code", "course_name", "total_enrolled", "checked_in_count", "qr_code_enabled"):
        assert key in row


@pytest.mark.points(0, category="spec_authz")
def test_create_session_rejects_past_start(client, test_course, auth_headers_instructor):
    now = datetime.now(timezone.utc)
    response = client.post(
        "/api/v1/sessions/",
        headers=auth_headers_instructor,
        json={
            "course_id": test_course["id"],
            "name": "Past",
            "session_type": "lecture",
            "scheduled_start": (now - timedelta(hours=1)).isoformat(),
            "scheduled_end": (now + timedelta(hours=1)).isoformat(),
        },
    )
    assert response.status_code == 400


def _create_course(client, admin_headers: dict) -> dict:
    created = client.post(
        "/api/v1/courses/",
        headers=admin_headers,
        json={
            "code": f"ST{uuid.uuid4().hex[:4].upper()}",
            "name": "Stats Auth Course",
            "semester": "AY2024-25 Sem 1",
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def _create_session(client, course_id: str, instructor_headers: dict) -> dict:
    now = datetime.now(timezone.utc)
    created = client.post(
        "/api/v1/sessions/",
        headers=instructor_headers,
        json={
            "course_id": course_id,
            "name": f"Stats {uuid.uuid4().hex[:6]}",
            "session_type": "lecture",
            "scheduled_start": (now + timedelta(hours=1)).isoformat(),
            "scheduled_end": (now + timedelta(hours=2)).isoformat(),
        },
    )
    assert created.status_code in (200, 201), created.text
    return created.json()


def _create_active_session(client, course_id: str, instructor_headers: dict, admin_headers: dict) -> dict:
    now = datetime.now(timezone.utc)
    created = client.post(
        "/api/v1/sessions/",
        headers=instructor_headers,
        json={
            "course_id": course_id,
            "name": f"Stats Active {uuid.uuid4().hex[:6]}",
            "session_type": "lecture",
            "scheduled_start": (now + timedelta(minutes=5)).isoformat(),
            "scheduled_end": (now + timedelta(hours=2)).isoformat(),
            "checkin_opens_at": (now - timedelta(minutes=10)).isoformat(),
            "checkin_closes_at": (now + timedelta(minutes=30)).isoformat(),
            "venue_latitude": 1.3483,
            "venue_longitude": 103.6831,
            "geofence_radius_meters": 100.0,
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


def _checkin(client, session_id: str, student_headers: dict):
    return client.post(
        "/api/v1/checkins/",
        headers=student_headers,
        json={
            "session_id": session_id,
            "latitude": 1.3483,
            "longitude": 103.6831,
            "location_accuracy_meters": 10.0,
            "device_fingerprint": f"fp_{uuid.uuid4().hex[:10]}",
        },
    )


@pytest.mark.points(0, category="spec_authz")
def test_session_stats_owner_admin_ta_and_unrelated(
    client, test_session, auth_headers_instructor, auth_headers_admin, auth_headers_student
):
    owner = client.get(
        f"/api/v1/stats/sessions/{test_session['id']}",
        headers=auth_headers_instructor,
    )
    assert owner.status_code == 200, owner.text

    admin_ok = client.get(
        f"/api/v1/stats/sessions/{test_session['id']}",
        headers=auth_headers_admin,
    )
    assert admin_ok.status_code == 200, admin_ok.text

    ta = _register_and_login(client, "ta")
    ta_ok = client.get(
        f"/api/v1/stats/sessions/{test_session['id']}",
        headers=ta["headers"],
    )
    assert ta_ok.status_code == 200, ta_ok.text

    outsider = _register_and_login(client, "instructor")
    denied = client.get(
        f"/api/v1/stats/sessions/{test_session['id']}",
        headers=outsider["headers"],
    )
    assert denied.status_code == 403, denied.text

    student_denied = client.get(
        f"/api/v1/stats/sessions/{test_session['id']}",
        headers=auth_headers_student,
    )
    assert student_denied.status_code in (401, 403)

    missing = client.get(
        "/api/v1/stats/sessions/00000000-0000-0000-0000-000000000000",
        headers=auth_headers_admin,
    )
    assert missing.status_code == 404

    co_teacher = _register_and_login(client, "instructor")
    _assign_instructor(client, test_session["course_id"], co_teacher["id"], auth_headers_admin)
    co_teacher_ok = client.get(
        f"/api/v1/stats/sessions/{test_session['id']}",
        headers=co_teacher["headers"],
    )
    assert co_teacher_ok.status_code == 200, co_teacher_ok.text


@pytest.mark.points(0, category="spec_authz")
def test_course_stats_teaching_instructor_admin_and_unrelated(
    client,
    test_course,
    test_instructor,
    test_session,
    auth_headers_instructor,
    auth_headers_admin,
    auth_headers_student,
):
    _assign_instructor(client, test_course["id"], test_instructor["id"], auth_headers_admin)
    owner = client.get(
        f"/api/v1/stats/courses/{test_course['id']}",
        headers=auth_headers_instructor,
    )
    assert owner.status_code == 200, owner.text

    admin_ok = client.get(
        f"/api/v1/stats/courses/{test_course['id']}",
        headers=auth_headers_admin,
    )
    assert admin_ok.status_code == 200, admin_ok.text

    ta = _register_and_login(client, "ta")
    ta_denied = client.get(
        f"/api/v1/stats/courses/{test_course['id']}",
        headers=ta["headers"],
    )
    assert ta_denied.status_code in (401, 403)

    outsider = _register_and_login(client, "instructor")
    denied = client.get(
        f"/api/v1/stats/courses/{test_course['id']}",
        headers=outsider["headers"],
    )
    assert denied.status_code == 403, denied.text

    student_denied = client.get(
        f"/api/v1/stats/courses/{test_course['id']}",
        headers=auth_headers_student,
    )
    assert student_denied.status_code in (401, 403)

    missing = client.get(
        "/api/v1/stats/courses/00000000-0000-0000-0000-000000000000",
        headers=auth_headers_admin,
    )
    assert missing.status_code == 404


@pytest.mark.points(0, category="spec_authz")
def test_course_stats_requires_assignment(
    client, test_course, auth_headers_instructor
):
    denied = client.get(
        f"/api/v1/stats/courses/{test_course['id']}",
        headers=auth_headers_instructor,
    )
    assert denied.status_code == 403, denied.text


@pytest.mark.points(0, category="spec_authz")
def test_student_stats_teaching_instructor_admin_and_unrelated(
    client,
    test_course,
    test_instructor,
    test_student,
    test_enrollment,
    test_session,
    auth_headers_instructor,
    auth_headers_admin,
    auth_headers_student,
):
    _assign_instructor(client, test_course["id"], test_instructor["id"], auth_headers_admin)
    owner = client.get(
        f"/api/v1/stats/students/{test_student['id']}",
        headers=auth_headers_instructor,
    )
    assert owner.status_code == 200, owner.text

    admin_ok = client.get(
        f"/api/v1/stats/students/{test_student['id']}",
        headers=auth_headers_admin,
    )
    assert admin_ok.status_code == 200, admin_ok.text

    outsider = _register_and_login(client, "instructor")
    denied = client.get(
        f"/api/v1/stats/students/{test_student['id']}",
        headers=outsider["headers"],
    )
    assert denied.status_code == 403, denied.text

    other_instructor = _register_and_login(client, "instructor")
    other_course = _create_course(client, auth_headers_admin)
    _create_session(client, other_course["id"], other_instructor["headers"])
    _assign_instructor(client, other_course["id"], other_instructor["id"], auth_headers_admin)
    other_course_denied = client.get(
        f"/api/v1/stats/students/{test_student['id']}",
        headers=other_instructor["headers"],
    )
    assert other_course_denied.status_code == 403, other_course_denied.text

    ta = _register_and_login(client, "ta")
    ta_denied = client.get(
        f"/api/v1/stats/students/{test_student['id']}",
        headers=ta["headers"],
    )
    assert ta_denied.status_code in (401, 403)

    self_denied = client.get(
        f"/api/v1/stats/students/{test_student['id']}",
        headers=auth_headers_student,
    )
    assert self_denied.status_code in (401, 403)

    missing = client.get(
        "/api/v1/stats/students/00000000-0000-0000-0000-000000000000",
        headers=auth_headers_admin,
    )
    assert missing.status_code == 404


@pytest.mark.points(0, category="spec_authz")
def test_student_stats_requires_assignment(
    client, test_student, test_enrollment, auth_headers_instructor
):
    denied = client.get(
        f"/api/v1/stats/students/{test_student['id']}",
        headers=auth_headers_instructor,
    )
    assert denied.status_code == 403, denied.text


@pytest.mark.points(0, category="spec_authz")
def test_student_stats_hides_other_instructors_courses(
    client,
    test_course,
    test_instructor,
    test_student,
    test_enrollment,
    test_session,
    auth_headers_instructor,
    auth_headers_admin,
    auth_headers_student,
):
    _assign_instructor(client, test_course["id"], test_instructor["id"], auth_headers_admin)
    other_instructor = _register_and_login(client, "instructor")
    other_course = _create_course(client, auth_headers_admin)
    _assign_instructor(client, other_course["id"], other_instructor["id"], auth_headers_admin)
    other_session = _create_active_session(
        client, other_course["id"], other_instructor["headers"], auth_headers_admin
    )
    enrolled = client.post(
        "/api/v1/enrollments/",
        headers=auth_headers_admin,
        json={"student_id": test_student["id"], "course_id": other_course["id"]},
    )
    assert enrolled.status_code == 201, enrolled.text

    own_checkin = _checkin(client, test_session["id"], auth_headers_student)
    assert own_checkin.status_code == 201, own_checkin.text
    other_checkin = _checkin(client, other_session["id"], auth_headers_student)
    assert other_checkin.status_code == 201, other_checkin.text

    instructor_view = client.get(
        f"/api/v1/stats/students/{test_student['id']}",
        headers=auth_headers_instructor,
    )
    assert instructor_view.status_code == 200, instructor_view.text
    instructor_data = instructor_view.json()
    instructor_course_ids = {row["course_id"] for row in instructor_data["courses"]}
    assert test_course["id"] in instructor_course_ids
    assert other_course["id"] not in instructor_course_ids
    assert instructor_data["total_enrolled_courses"] == 1
    assert instructor_data["total_sessions"] == 1
    assert instructor_data["attended_sessions"] == 1
    recent_codes = {
        row.get("course_code")
        for row in instructor_data["recent_checkins"] + instructor_data["recent_sessions"]
    }
    assert other_course["code"] not in recent_codes
    recent_session_ids = {
        row.get("session_id")
        for row in instructor_data["recent_checkins"] + instructor_data["recent_sessions"]
    }
    assert other_session["id"] not in recent_session_ids
    assert test_session["id"] in recent_session_ids

    other_view = client.get(
        f"/api/v1/stats/students/{test_student['id']}",
        headers=other_instructor["headers"],
    )
    assert other_view.status_code == 200, other_view.text
    other_data = other_view.json()
    other_course_ids = {row["course_id"] for row in other_data["courses"]}
    assert other_course["id"] in other_course_ids
    assert test_course["id"] not in other_course_ids
    assert other_data["total_enrolled_courses"] == 1
    assert other_data["total_sessions"] == 1
    assert other_data["attended_sessions"] == 1
    other_recent_ids = {
        row.get("session_id")
        for row in other_data["recent_checkins"] + other_data["recent_sessions"]
    }
    assert other_session["id"] in other_recent_ids
    assert test_session["id"] not in other_recent_ids

    admin_view = client.get(
        f"/api/v1/stats/students/{test_student['id']}",
        headers=auth_headers_admin,
    )
    assert admin_view.status_code == 200, admin_view.text
    admin_data = admin_view.json()
    admin_course_ids = {row["course_id"] for row in admin_data["courses"]}
    assert {test_course["id"], other_course["id"]} <= admin_course_ids
    assert admin_data["total_enrolled_courses"] >= 2
    assert admin_data["attended_sessions"] >= 2
    admin_recent_ids = {
        row.get("session_id")
        for row in admin_data["recent_checkins"] + admin_data["recent_sessions"]
    }
    assert {test_session["id"], other_session["id"]} <= admin_recent_ids

    outsider = _register_and_login(client, "instructor")
    denied = client.get(
        f"/api/v1/stats/students/{test_student['id']}",
        headers=outsider["headers"],
    )
    assert denied.status_code == 403, denied.text


@pytest.mark.points(0, category="spec_authz")
def test_stats_overview_unfiltered_and_course_scoped(
    client,
    test_course,
    test_instructor,
    test_session,
    auth_headers_instructor,
    auth_headers_admin,
    auth_headers_student,
):
    _assign_instructor(client, test_course["id"], test_instructor["id"], auth_headers_admin)
    unfiltered = client.get("/api/v1/stats/overview", headers=auth_headers_instructor)
    assert unfiltered.status_code == 200, unfiltered.text

    admin_ok = client.get("/api/v1/stats/overview", headers=auth_headers_admin)
    assert admin_ok.status_code == 200, admin_ok.text

    ta = _register_and_login(client, "ta")
    ta_denied = client.get("/api/v1/stats/overview", headers=ta["headers"])
    assert ta_denied.status_code in (401, 403)

    student_denied = client.get("/api/v1/stats/overview", headers=auth_headers_student)
    assert student_denied.status_code in (401, 403)

    scoped = client.get(
        "/api/v1/stats/overview",
        headers=auth_headers_instructor,
        params={"course_id": test_course["id"]},
    )
    assert scoped.status_code == 200, scoped.text

    admin_scoped = client.get(
        "/api/v1/stats/overview",
        headers=auth_headers_admin,
        params={"course_id": test_course["id"]},
    )
    assert admin_scoped.status_code == 200, admin_scoped.text

    outsider = _register_and_login(client, "instructor")
    denied = client.get(
        "/api/v1/stats/overview",
        headers=outsider["headers"],
        params={"course_id": test_course["id"]},
    )
    assert denied.status_code == 403, denied.text

    missing = client.get(
        "/api/v1/stats/overview",
        headers=auth_headers_admin,
        params={"course_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert missing.status_code == 404
