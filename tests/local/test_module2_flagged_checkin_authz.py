"""HTTP: instructor GET /checkins/flagged is course_instructors-scoped.

M4 Review calls this endpoint with no course_id for "All courses", and with
course_id when a course is selected. The page envelope and item fields below
are the contract that view already consumes. student_email is not returned.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

PASSWORD = "testpassword123"
NTU_LAT, NTU_LNG = 1.3483, 103.6831
M4_FLAGGED_ITEM_FIELDS = (
    "id",
    "session_id",
    "session_name",
    "student_id",
    "student_name",
    "status",
    "checked_in_at",
    "risk_score",
    "risk_factors",
    "appeal_reason",
    "appealed_at",
)


def _register_and_login(client, role: str, full_name: str | None = None) -> dict:
    email = f"{role}_{uuid.uuid4().hex[:10]}@test.com"
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


def _assign(client, admin_headers, course_id, instructor_id):
    response = client.post(
        f"/api/v1/admin/courses/{course_id}/instructors",
        headers=admin_headers,
        json={"instructor_id": instructor_id},
    )
    assert response.status_code in (200, 201), response.text


def _flagged_on_course(client, admin, instructor, student):
    course = client.post(
        "/api/v1/courses/",
        headers=admin["headers"],
        json={
            "code": f"F{uuid.uuid4().hex[:5].upper()}",
            "name": "Flagged scope",
            "semester": "AY2025-26 Sem 1",
            "venue_latitude": NTU_LAT,
            "venue_longitude": NTU_LNG,
            "geofence_radius_meters": 100.0,
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
            "name": f"flag {uuid.uuid4().hex[:6]}",
            "session_type": "lecture",
            "scheduled_start": (now + timedelta(minutes=5)).isoformat(),
            "scheduled_end": (now + timedelta(hours=2)).isoformat(),
            "checkin_opens_at": (now - timedelta(minutes=5)).isoformat(),
            "checkin_closes_at": (now + timedelta(hours=1)).isoformat(),
            "venue_latitude": NTU_LAT,
            "venue_longitude": NTU_LNG,
            "geofence_radius_meters": 100,
            "risk_threshold": 0.1,
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
        json={
            "session_id": sid,
            "latitude": 1.3497,
            "longitude": NTU_LNG,
            "location_accuracy_meters": 10.0,
            "device_fingerprint": f"fp_{uuid.uuid4().hex[:10]}",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "flagged", created.text
    return course, session.json() | {"id": sid}, created.json()


def _flagged(client, headers, **params):
    return client.get("/api/v1/checkins/flagged", headers=headers, params=params or {"limit": 50})


@pytest.mark.points(0, category="spec_authz")
def test_assigned_instructor_sees_own_course_flagged_not_others(client):
    admin = _register_and_login(client, "admin")
    instr_a = _register_and_login(client, "instructor")
    instr_b = _register_and_login(client, "instructor")
    student_a = _register_and_login(client, "student", full_name=f"Alice {uuid.uuid4().hex[:6]}")
    student_b = _register_and_login(client, "student", full_name=f"Bob {uuid.uuid4().hex[:6]}")
    course_a, session_a, checkin_a = _flagged_on_course(client, admin, instr_a, student_a)
    _course_b, _session_b, checkin_b = _flagged_on_course(client, admin, instr_b, student_b)

    listed_a = _flagged(client, instr_a["headers"], limit=100)
    assert listed_a.status_code == 200, listed_a.text
    body = listed_a.json()
    assert set(body) >= {"items", "total", "limit", "offset"}
    ids_a = {row["id"] for row in body["items"]}
    assert checkin_a["id"] in ids_a
    assert checkin_b["id"] not in ids_a
    for row in body["items"]:
        assert "student_email" not in row
        assert student_b["email"] not in listed_a.text
        for field in M4_FLAGGED_ITEM_FIELDS:
            assert field in row
        assert row["status"] in {"flagged", "appealed"}

    listed_b = _flagged(client, instr_b["headers"], limit=100)
    ids_b = {row["id"] for row in listed_b.json()["items"]}
    assert checkin_b["id"] in ids_b
    assert checkin_a["id"] not in ids_b

    filtered = _flagged(client, instr_a["headers"], course_id=course_a["id"], limit=50)
    filtered_ids = {row["id"] for row in filtered.json()["items"]}
    assert checkin_a["id"] in filtered_ids
    assert checkin_b["id"] not in filtered_ids

    by_session = _flagged(client, instr_a["headers"], session_id=session_a["id"])
    session_ids = {row["id"] for row in by_session.json()["items"]}
    assert checkin_a["id"] in session_ids
    assert checkin_b["id"] not in session_ids

    admin_listed = _flagged(client, admin["headers"], limit=100)
    assert admin_listed.status_code == 200
    admin_ids = {row["id"] for row in admin_listed.json()["items"]}
    assert checkin_a["id"] in admin_ids
    assert checkin_b["id"] in admin_ids

    unused = _register_and_login(client, "instructor")
    empty = _flagged(client, unused["headers"], limit=10)
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert empty.json()["total"] == 0
    assert student_a["email"] not in empty.text
    assert student_b["email"] not in empty.text


@pytest.mark.points(0, category="spec_authz")
def test_instructor_assigned_to_two_courses_sees_both_flagged(client):
    admin = _register_and_login(client, "admin")
    instr = _register_and_login(client, "instructor")
    other = _register_and_login(client, "instructor")
    student_a = _register_and_login(client, "student")
    student_b = _register_and_login(client, "student")
    student_c = _register_and_login(client, "student")
    course_a, _session_a, checkin_a = _flagged_on_course(client, admin, instr, student_a)
    _course_b, _session_b, checkin_b = _flagged_on_course(client, admin, instr, student_b)
    course_c, session_c, checkin_c = _flagged_on_course(client, admin, other, student_c)
    _assign(client, admin["headers"], course_a["id"], instr["id"])
    _assign(client, admin["headers"], _course_b["id"], instr["id"])

    listed = _flagged(client, instr["headers"], limit=100)
    assert listed.status_code == 200
    ids = {row["id"] for row in listed.json()["items"]}
    assert checkin_a["id"] in ids
    assert checkin_b["id"] in ids
    assert checkin_c["id"] not in ids

    foreign_course = _flagged(client, instr["headers"], course_id=course_c["id"])
    assert foreign_course.json()["items"] == []
    assert foreign_course.json()["total"] == 0

    foreign_session = _flagged(client, instr["headers"], session_id=session_c["id"])
    assert foreign_session.json()["items"] == []
    assert foreign_session.json()["total"] == 0


@pytest.mark.points(0, category="spec_authz")
def test_flagged_ordering_is_checked_in_at_desc(client):
    admin = _register_and_login(client, "admin")
    instr = _register_and_login(client, "instructor")
    first_student = _register_and_login(client, "student")
    second_student = _register_and_login(client, "student")
    course, session, first = _flagged_on_course(client, admin, instr, first_student)
    enrolled = client.post(
        "/api/v1/enrollments/",
        headers=admin["headers"],
        json={"student_id": second_student["id"], "course_id": course["id"]},
    )
    assert enrolled.status_code in (200, 201), enrolled.text
    second = client.post(
        "/api/v1/checkins/",
        headers=second_student["headers"],
        json={
            "session_id": session["id"],
            "latitude": 1.3497,
            "longitude": NTU_LNG,
            "location_accuracy_meters": 10.0,
            "device_fingerprint": f"fp_{uuid.uuid4().hex[:10]}",
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["status"] == "flagged", second.text

    listed = _flagged(client, instr["headers"], session_id=session["id"], limit=50)
    ids = [row["id"] for row in listed.json()["items"]]
    assert second.json()["id"] in ids
    assert first["id"] in ids
    assert ids.index(second.json()["id"]) < ids.index(first["id"])


@pytest.mark.points(0, category="spec_authz")
def test_unassigned_instructor_cannot_retrieve_or_review_foreign_flagged(client):
    """Existing get/review gates; not changed in this slice. Documented for Phase 2."""
    admin = _register_and_login(client, "admin")
    owner = _register_and_login(client, "instructor")
    outsider = _register_and_login(client, "instructor")
    student = _register_and_login(client, "student")
    _course, _session, checkin = _flagged_on_course(client, admin, owner, student)

    detail = client.get(f"/api/v1/checkins/{checkin['id']}", headers=outsider["headers"])
    assert detail.status_code == 403, detail.text
    assert student["email"] not in detail.text

    review = client.post(
        f"/api/v1/checkins/{checkin['id']}/review",
        headers=outsider["headers"],
        json={"status": "approved", "review_notes": "nope"},
    )
    assert review.status_code == 403, review.text

    owner_detail = client.get(f"/api/v1/checkins/{checkin['id']}", headers=owner["headers"])
    assert owner_detail.status_code == 200, owner_detail.text
