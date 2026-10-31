"""GET /checkins/ is instructor/admin only (API spec). TAs are not allowed."""
import uuid

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
    return {"headers": {"Authorization": f"Bearer {login.json()['access_token']}"}}


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
