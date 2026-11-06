"""GET /checkins/ is instructor/admin only (API spec). TAs are not allowed.

Instructors are scoped to course_instructors in SQL. Unassigned instructors
get an empty page rather than other courses' student emails.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest


def _register_and_login(client, role: str) -> dict:
    email = f"{role}_{uuid.uuid4().hex[:10]}@test.com"
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


def _list_checkins(client, headers=None, **params):
    return client.get("/api/v1/checkins/", headers=headers or {}, params=params or {"limit": 10})


@pytest.mark.points(0, category="spec_authz")
def test_instructor_can_list_all_checkins(client):
    instructor = _register_and_login(client, "instructor")
    response = _list_checkins(client, instructor["headers"], limit=10, offset=0)
    assert response.status_code == 200, response.text
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert "limit" in data
    assert "offset" in data
    assert isinstance(data["items"], list)
    assert data["limit"] == 10
    assert data["offset"] == 0


@pytest.mark.points(0, category="spec_authz")
def test_admin_can_list_all_checkins(client):
    admin = _register_and_login(client, "admin")
    response = _list_checkins(client, admin["headers"], status="approved", limit=5)
    assert response.status_code == 200, response.text
    data = response.json()
    assert isinstance(data["items"], list)
    assert data["limit"] == 5
    for item in data["items"]:
        assert item["status"] == "approved"


@pytest.mark.points(0, category="spec_authz")
def test_ta_cannot_list_all_checkins(client):
    ta = _register_and_login(client, "ta")
    denied = _list_checkins(client, ta["headers"])
    assert denied.status_code == 403, denied.text

    flagged = client.get("/api/v1/checkins/flagged", headers=ta["headers"])
    assert flagged.status_code == 200, flagged.text
    payload = flagged.json()
    assert "items" in payload
    assert "total" in payload
    assert payload["items"] == []
    assert payload["total"] == 0


@pytest.mark.points(0, category="spec_authz")
def test_student_cannot_list_all_checkins(client):
    student = _register_and_login(client, "student")
    response = _list_checkins(client, student["headers"])
    assert response.status_code == 403, response.text


@pytest.mark.points(0, category="spec_authz")
def test_unauthenticated_cannot_list_all_checkins(client):
    response = _list_checkins(client)
    assert response.status_code == 401, response.text


def _assign(client, admin_headers, course_id, instructor_id):
    response = client.post(
        f"/api/v1/admin/courses/{course_id}/instructors",
        headers=admin_headers,
        json={"instructor_id": instructor_id},
    )
    assert response.status_code in (200, 201), response.text


def _course_session_checkin(client, admin, instructor, student):
    course = client.post(
        "/api/v1/courses/",
        headers=admin["headers"],
        json={
            "code": f"L{uuid.uuid4().hex[:5].upper()}",
            "name": "List scope",
            "semester": "AY2025-26 Sem 1",
        },
    )
    assert course.status_code == 201, course.text
    course = course.json()
    _assign(client, admin["headers"], course["id"], instructor["id"])
    enrolled = client.post(
        "/api/v1/enrollments/",
        headers=admin["headers"],
        json={"student_id": student["id"], "course_id": course["id"]},
    )
    assert enrolled.status_code in (200, 201), enrolled.text
    now = datetime.now(timezone.utc)
    session = client.post(
        "/api/v1/sessions/",
        headers=instructor["headers"],
        json={
            "course_id": course["id"],
            "name": f"scope {uuid.uuid4().hex[:6]}",
            "session_type": "lecture",
            "scheduled_start": (now + timedelta(minutes=5)).isoformat(),
            "scheduled_end": (now + timedelta(hours=2)).isoformat(),
            "checkin_opens_at": (now - timedelta(minutes=5)).isoformat(),
            "checkin_closes_at": (now + timedelta(hours=1)).isoformat(),
            "venue_latitude": 1.3483,
            "venue_longitude": 103.6831,
            "geofence_radius_meters": 200,
        },
    )
    assert session.status_code == 201, session.text
    sid = session.json()["id"]
    activated = client.patch(
        f"/api/v1/admin/sessions/{sid}/status",
        headers=admin["headers"],
        json={"status": "active"},
    )
    assert activated.status_code == 200, activated.text
    created = client.post(
        "/api/v1/checkins/",
        headers=student["headers"],
        json={"session_id": sid, "latitude": 1.3483, "longitude": 103.6831},
    )
    assert created.status_code == 201, created.text
    return course, created.json()


def _actor(client, role: str) -> dict:
    account = _register_and_login(client, role)
    me = client.get("/api/v1/users/me", headers=account["headers"])
    assert me.status_code == 200, me.text
    account["id"] = me.json()["id"]
    return account


@pytest.mark.points(0, category="spec_authz")
def test_assigned_instructor_sees_own_course_not_others(client):
    admin = _actor(client, "admin")
    instr_a = _actor(client, "instructor")
    instr_b = _actor(client, "instructor")
    student_a = _actor(client, "student")
    student_b = _actor(client, "student")
    _course_a, checkin_a = _course_session_checkin(client, admin, instr_a, student_a)
    _course_b, checkin_b = _course_session_checkin(client, admin, instr_b, student_b)

    listed_a = _list_checkins(client, instr_a["headers"], limit=100)
    assert listed_a.status_code == 200, listed_a.text
    ids_a = {row["id"] for row in listed_a.json()["items"]}
    emails_a = {row.get("student_email") for row in listed_a.json()["items"]}
    assert checkin_a["id"] in ids_a
    assert checkin_b["id"] not in ids_a
    assert student_b["email"] not in emails_a

    listed_b = _list_checkins(client, instr_b["headers"], limit=100)
    ids_b = {row["id"] for row in listed_b.json()["items"]}
    assert checkin_b["id"] in ids_b
    assert checkin_a["id"] not in ids_b

    admin_listed = _list_checkins(client, admin["headers"], limit=100)
    assert admin_listed.status_code == 200
    admin_ids = {row["id"] for row in admin_listed.json()["items"]}
    assert checkin_a["id"] in admin_ids
    assert checkin_b["id"] in admin_ids


@pytest.mark.points(0, category="spec_authz")
def test_instructor_assigned_to_two_courses_sees_both(client):
    admin = _actor(client, "admin")
    instr = _actor(client, "instructor")
    other = _actor(client, "instructor")
    student_a = _actor(client, "student")
    student_b = _actor(client, "student")
    student_c = _actor(client, "student")
    course_a, checkin_a = _course_session_checkin(client, admin, instr, student_a)
    course_b, checkin_b = _course_session_checkin(client, admin, instr, student_b)
    _course_c, checkin_c = _course_session_checkin(client, admin, other, student_c)
    _assign(client, admin["headers"], course_b["id"], instr["id"])

    listed = _list_checkins(client, instr["headers"], limit=100, offset=0)
    assert listed.status_code == 200
    body = listed.json()
    assert body["limit"] == 100
    assert body["offset"] == 0
    ids = {row["id"] for row in body["items"]}
    assert checkin_a["id"] in ids
    assert checkin_b["id"] in ids
    assert checkin_c["id"] not in ids
    filtered = _list_checkins(client, instr["headers"], course_id=course_a["id"], limit=50)
    filtered_ids = {row["id"] for row in filtered.json()["items"]}
    assert checkin_a["id"] in filtered_ids
    assert checkin_b["id"] not in filtered_ids
    foreign = _list_checkins(client, instr["headers"], course_id=_course_c["id"], limit=50)
    assert foreign.json()["items"] == []
    assert foreign.json()["total"] == 0
    unused = _actor(client, "instructor")
    empty = _list_checkins(client, unused["headers"], limit=10)
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert empty.json()["total"] == 0
