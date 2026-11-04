"""Admin-managed instructor–course assignments (Module 2)."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest


def _email(role: str) -> str:
    return f"{role}_{uuid.uuid4().hex[:10]}@test.com"


def _register_login(client, role: str) -> dict:
    email = _email(role)
    password = "testpassword123"
    register = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": role.title(), "role": role},
    )
    assert register.status_code == 201, register.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {
        "id": register.json()["id"],
        "email": email,
        "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
    }


def _assign(client, course_id: str, instructor_id: str, admin_headers: dict):
    response = client.post(
        f"/api/v1/admin/courses/{course_id}/instructors",
        headers=admin_headers,
        json={"instructor_id": instructor_id},
    )
    assert response.status_code in (200, 201), response.text
    return response


def _create_course(client, admin_headers: dict) -> dict:
    created = client.post(
        "/api/v1/courses/",
        headers=admin_headers,
        json={
            "code": f"CI{uuid.uuid4().hex[:4].upper()}",
            "name": "Assignment Course",
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
            "name": f"Assign {uuid.uuid4().hex[:6]}",
            "session_type": "lecture",
            "scheduled_start": (now + timedelta(hours=1)).isoformat(),
            "scheduled_end": (now + timedelta(hours=2)).isoformat(),
        },
    )
    assert created.status_code in (200, 201), created.text
    return created.json()


@pytest.mark.points(0, category="course_instructors")
def test_admin_assign_revoke_list_and_self_assign_denied(
    client, test_course, test_instructor, auth_headers_admin, auth_headers_instructor
):
    assigned = _assign(client, test_course["id"], test_instructor["id"], auth_headers_admin)
    body = assigned.json()
    assert body["course_id"] == test_course["id"]
    assert body["instructor_id"] == test_instructor["id"]
    assert body["is_active"] is True

    listed = client.get(
        f"/api/v1/admin/courses/{test_course['id']}/instructors",
        headers=auth_headers_admin,
    )
    assert listed.status_code == 200, listed.text
    instructors = listed.json()["instructors"]
    assert any(
        row["instructor_id"] == test_instructor["id"] and row["is_active"] is True
        for row in instructors
    )

    again = _assign(client, test_course["id"], test_instructor["id"], auth_headers_admin)
    assert again.json()["is_active"] is True

    self_assign = client.post(
        f"/api/v1/admin/courses/{test_course['id']}/instructors",
        headers=auth_headers_instructor,
        json={"instructor_id": test_instructor["id"]},
    )
    assert self_assign.status_code == 403

    student = _register_login(client, "student")
    not_instructor = client.post(
        f"/api/v1/admin/courses/{test_course['id']}/instructors",
        headers=auth_headers_admin,
        json={"instructor_id": student["id"]},
    )
    assert not_instructor.status_code == 400

    missing_course = client.post(
        "/api/v1/admin/courses/00000000-0000-0000-0000-000000000000/instructors",
        headers=auth_headers_admin,
        json={"instructor_id": test_instructor["id"]},
    )
    assert missing_course.status_code == 404

    revoked = client.delete(
        f"/api/v1/admin/courses/{test_course['id']}/instructors/{test_instructor['id']}",
        headers=auth_headers_admin,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["is_active"] is False

    instructor_revoke = client.delete(
        f"/api/v1/admin/courses/{test_course['id']}/instructors/{test_instructor['id']}",
        headers=auth_headers_instructor,
    )
    assert instructor_revoke.status_code == 403


@pytest.mark.points(0, category="course_instructors")
def test_assigned_instructor_can_access_roster_and_stats_before_sessions(
    client, test_course, test_instructor, test_enrollment, auth_headers_admin, auth_headers_instructor
):
    denied = client.get(
        f"/api/v1/enrollments/course/{test_course['id']}",
        headers=auth_headers_instructor,
    )
    assert denied.status_code == 403, denied.text

    _assign(client, test_course["id"], test_instructor["id"], auth_headers_admin)

    roster = client.get(
        f"/api/v1/enrollments/course/{test_course['id']}",
        headers=auth_headers_instructor,
    )
    assert roster.status_code == 200, roster.text
    assert roster.json()["course_id"] == test_course["id"]

    stats = client.get(
        f"/api/v1/stats/courses/{test_course['id']}",
        headers=auth_headers_instructor,
    )
    assert stats.status_code == 200, stats.text
    assert stats.json()["total_sessions"] == 0

    overview = client.get(
        "/api/v1/stats/overview",
        headers=auth_headers_instructor,
        params={"course_id": test_course["id"]},
    )
    assert overview.status_code == 200, overview.text


@pytest.mark.points(0, category="course_instructors")
def test_multiple_instructors_and_unrelated_403(
    client, test_course, test_enrollment, auth_headers_admin, auth_headers_student
):
    first = _register_login(client, "instructor")
    second = _register_login(client, "instructor")
    outsider = _register_login(client, "instructor")
    _assign(client, test_course["id"], first["id"], auth_headers_admin)
    _assign(client, test_course["id"], second["id"], auth_headers_admin)

    for teacher in (first, second):
        roster = client.get(
            f"/api/v1/enrollments/course/{test_course['id']}",
            headers=teacher["headers"],
        )
        assert roster.status_code == 200, roster.text
        stats = client.get(
            f"/api/v1/stats/courses/{test_course['id']}",
            headers=teacher["headers"],
        )
        assert stats.status_code == 200, stats.text

    denied = client.get(
        f"/api/v1/enrollments/course/{test_course['id']}",
        headers=outsider["headers"],
    )
    assert denied.status_code == 403
    denied_stats = client.get(
        f"/api/v1/stats/courses/{test_course['id']}",
        headers=outsider["headers"],
    )
    assert denied_stats.status_code == 403
    denied_student = client.get(
        f"/api/v1/stats/students/{test_enrollment['student_id']}",
        headers=outsider["headers"],
    )
    assert denied_student.status_code == 403
    denied_export = client.get(
        f"/api/v1/export/attendance/{test_course['id']}",
        headers=outsider["headers"],
        params={"format": "json"},
    )
    assert denied_export.status_code == 403
    student_denied = client.get(
        f"/api/v1/enrollments/course/{test_course['id']}",
        headers=auth_headers_student,
    )
    assert student_denied.status_code in (401, 403)


@pytest.mark.points(0, category="course_instructors")
def test_session_create_does_not_assign_and_ownership_stays_separate(
    client, test_course, test_instructor, auth_headers_admin, auth_headers_instructor
):
    session = _create_session(client, test_course["id"], auth_headers_instructor)
    assert session["instructor_id"] == test_instructor["id"]

    listed = client.get(
        f"/api/v1/admin/courses/{test_course['id']}/instructors",
        headers=auth_headers_admin,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["instructors"] == []

    roster = client.get(
        f"/api/v1/enrollments/course/{test_course['id']}",
        headers=auth_headers_instructor,
    )
    assert roster.status_code == 403

    owner_patch = client.patch(
        f"/api/v1/sessions/{session['id']}",
        headers=auth_headers_instructor,
        json={"name": "Still owned"},
    )
    assert owner_patch.status_code == 200, owner_patch.text

    other = _register_login(client, "instructor")
    _assign(client, test_course["id"], other["id"], auth_headers_admin)
    hijack = client.patch(
        f"/api/v1/sessions/{session['id']}",
        headers=other["headers"],
        json={"name": "Hijacked"},
    )
    assert hijack.status_code == 403

    other_stats = client.get(
        f"/api/v1/stats/sessions/{session['id']}",
        headers=other["headers"],
    )
    assert other_stats.status_code == 200, other_stats.text


@pytest.mark.points(0, category="course_instructors")
def test_revoke_removes_course_access_but_keeps_session_ownership(
    client, test_course, test_instructor, test_enrollment, auth_headers_admin, auth_headers_instructor
):
    _assign(client, test_course["id"], test_instructor["id"], auth_headers_admin)
    session = _create_session(client, test_course["id"], auth_headers_instructor)

    revoked = client.delete(
        f"/api/v1/admin/courses/{test_course['id']}/instructors/{test_instructor['id']}",
        headers=auth_headers_admin,
    )
    assert revoked.status_code == 200, revoked.text

    roster = client.get(
        f"/api/v1/enrollments/course/{test_course['id']}",
        headers=auth_headers_instructor,
    )
    assert roster.status_code == 403
    course_stats = client.get(
        f"/api/v1/stats/courses/{test_course['id']}",
        headers=auth_headers_instructor,
    )
    assert course_stats.status_code == 403
    student_stats = client.get(
        f"/api/v1/stats/students/{test_enrollment['student_id']}",
        headers=auth_headers_instructor,
    )
    assert student_stats.status_code == 403

    owner_stats = client.get(
        f"/api/v1/stats/sessions/{session['id']}",
        headers=auth_headers_instructor,
    )
    assert owner_stats.status_code == 200, owner_stats.text
    owner_export = client.get(
        f"/api/v1/export/session/{session['id']}",
        headers=auth_headers_instructor,
        params={"format": "json"},
    )
    assert owner_export.status_code == 200, owner_export.text
