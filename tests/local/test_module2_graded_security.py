"""Local regression tests for graded Module 2 security clarifications.

HTTP cases hit the running backend. Rate-limit enforcement uses isolated
limiter calls and a tiny ASGI app so the suite does not send 100000 requests.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

_BACKEND = Path(__file__).resolve().parents[2] / "module2-backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.redis import get_redis  # noqa: E402
from app.core.utils import client_ip, singapore_checkin_allowed  # noqa: E402
from app.middleware import rate_limit as rate_limit_mod  # noqa: E402
from app.middleware.rate_limit import (  # noqa: E402
    RateLimitMiddleware,
    enforce_ip_limit,
    enforce_user_limit,
    rate_limit_api_user,
    rate_limit_checkin,
)

PASSWORD = "testpassword123"


def _email(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}@test.com"


def _register(client, role: str = "student", email: str | None = None) -> dict:
    email = email or _email(role)
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": role.title(), "role": role},
    )
    assert response.status_code == 201, response.text
    return {"id": response.json()["id"], "email": email, "password": PASSWORD}


def _login(client, email: str, password: str = PASSWORD, headers: dict | None = None):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers=headers or {},
    )


def _unique_test_net_ip() -> str:
    suffix = int(uuid.uuid4().hex[:4], 16) % 250 + 1
    return f"203.0.113.{suffix}"


def _require_redis():
    client = get_redis()
    if client is None:
        pytest.skip("Redis is required for rate-limit key assertions")
    return client


# ---------------------------------------------------------------------------
# Account lockout
# ---------------------------------------------------------------------------


class TestAccountLockout:
    def test_ninth_tenth_eleventh_failures_and_locked_refresh(self, client):
        user = _register(client, "student")
        ok = _login(client, user["email"])
        assert ok.status_code == 200, ok.text
        refresh_token = ok.json()["refresh_token"]

        statuses = []
        for _ in range(11):
            statuses.append(_login(client, user["email"], "wrongpassword").status_code)

        assert statuses[:9] == [401] * 9
        assert statuses[9] == 429
        assert statuses[10] == 429

        correct = _login(client, user["email"], PASSWORD)
        assert correct.status_code == 429
        assert correct.json()["detail"] == "Account locked"

        refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert refreshed.status_code == 429, refreshed.text
        assert refreshed.json()["detail"] == "Account locked"
        assert "access_token" not in (refreshed.json() or {})

    def test_successful_login_resets_failure_counter(self, client):
        user = _register(client, "student")
        for _ in range(5):
            failed = _login(client, user["email"], "wrongpassword")
            assert failed.status_code == 401

        reset = _login(client, user["email"], PASSWORD)
        assert reset.status_code == 200, reset.text

        post_reset = [_login(client, user["email"], "wrongpassword").status_code for _ in range(9)]
        assert post_reset == [401] * 9

        still_unlocked = _login(client, user["email"], PASSWORD)
        assert still_unlocked.status_code == 200, still_unlocked.text

    def test_refresh_still_works_for_unlocked_account(self, client):
        user = _register(client, "student")
        ok = _login(client, user["email"])
        assert ok.status_code == 200, ok.text
        refreshed = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": ok.json()["refresh_token"]}
        )
        assert refreshed.status_code == 200, refreshed.text
        body = refreshed.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["token_type"] == "bearer"

    def test_refresh_invalid_token_still_401(self, client):
        response = client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-jwt"})
        assert response.status_code == 401

    def test_refresh_inactive_account_still_401(self, client, auth_headers_admin):
        user = _register(client, "student")
        ok = _login(client, user["email"])
        assert ok.status_code == 200, ok.text
        refresh_token = ok.json()["refresh_token"]
        deactivated = client.patch(
            f"/api/v1/admin/users/{user['id']}/deactivate",
            headers=auth_headers_admin,
        )
        assert deactivated.status_code in (200, 204), deactivated.text
        refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert refreshed.status_code == 401


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def _mini_auth_app() -> TestClient:
    app = FastAPI()

    @app.post("/api/v1/auth/login")
    def login():
        return {"ok": True}

    @app.post("/api/v1/auth/register")
    def register():
        return {"ok": True}

    app.add_middleware(RateLimitMiddleware)
    return TestClient(app)


class TestRateLimiting:
    def test_enforce_ip_limit_uses_expected_redis_key(self):
        redis_client = _require_redis()
        ip = _unique_test_net_ip()
        key = f"rl:login:{ip}"
        assert enforce_ip_limit("login", ip, 2, 60) is True
        assert enforce_ip_limit("login", ip, 2, 60) is True
        assert enforce_ip_limit("login", ip, 2, 60) is False
        assert redis_client.get(key) == "3"

    def test_enforce_register_ip_limit_isolated_from_login_key(self):
        redis_client = _require_redis()
        ip = _unique_test_net_ip()
        assert enforce_ip_limit("register", ip, 1, 60) is True
        assert enforce_ip_limit("register", ip, 1, 60) is False
        assert redis_client.get(f"rl:register:{ip}") == "2"
        assert redis_client.get(f"rl:login:{ip}") is None

    def test_per_user_api_and_checkin_limits(self, monkeypatch):
        redis_client = _require_redis()
        user_id = str(uuid.uuid4())
        monkeypatch.setattr(rate_limit_mod.settings, "API_RATE_LIMIT", 2)
        monkeypatch.setattr(rate_limit_mod.settings, "CHECKIN_RATE_LIMIT", 1)

        rate_limit_api_user(user_id)
        rate_limit_api_user(user_id)
        with pytest.raises(HTTPException) as api_exc:
            rate_limit_api_user(user_id)
        assert api_exc.value.status_code == 429
        assert api_exc.value.detail == "Rate limit exceeded"
        assert redis_client.get(f"rl:api:{user_id}") == "3"

        rate_limit_checkin(user_id)
        with pytest.raises(HTTPException) as checkin_exc:
            rate_limit_checkin(user_id)
        assert checkin_exc.value.status_code == 429
        assert redis_client.get(f"rl:checkin:{user_id}") == "2"

    def test_middleware_enforces_per_ip_login_and_register(self, monkeypatch):
        redis_client = _require_redis()
        monkeypatch.setattr(rate_limit_mod.settings, "LOGIN_RATE_LIMIT", 2)
        monkeypatch.setattr(rate_limit_mod.settings, "REGISTER_RATE_LIMIT", 1)
        client = _mini_auth_app()

        login_ip = _unique_test_net_ip()
        login_headers = {"X-Forwarded-For": login_ip}
        assert client.post("/api/v1/auth/login", headers=login_headers).status_code == 200
        assert client.post("/api/v1/auth/login", headers=login_headers).status_code == 200
        limited = client.post("/api/v1/auth/login", headers=login_headers)
        assert limited.status_code == 429
        assert limited.json()["detail"] == "Rate limit exceeded"
        assert redis_client.get(f"rl:login:{login_ip}") == "3"

        register_ip = _unique_test_net_ip()
        register_headers = {"X-Forwarded-For": register_ip}
        assert client.post("/api/v1/auth/register", headers=register_headers).status_code == 200
        limited_reg = client.post("/api/v1/auth/register", headers=register_headers)
        assert limited_reg.status_code == 429
        assert redis_client.get(f"rl:register:{register_ip}") == "2"

    def test_live_login_increments_xff_keyed_redis_counter(self, client):
        redis_client = _require_redis()
        ip = _unique_test_net_ip()
        key = f"rl:login:{ip}"
        before = int(redis_client.get(key) or 0)
        response = _login(client, _email("nomatch"), "wrongpassword", headers={"X-Forwarded-For": ip})
        assert response.status_code == 401
        assert int(redis_client.get(key) or 0) == before + 1

    def test_direct_user_limit_helper_still_counts(self):
        user_id = str(uuid.uuid4())
        assert enforce_user_limit("api", user_id, 2, 60) is True
        assert enforce_user_limit("api", user_id, 2, 60) is True
        assert enforce_user_limit("api", user_id, 2, 60) is False


# ---------------------------------------------------------------------------
# Singapore-only check-ins
# ---------------------------------------------------------------------------


def _enroll_student(client, admin_headers: dict, course_id: str) -> dict:
    user = _register(client, "student")
    login = _login(client, user["email"])
    assert login.status_code == 200, login.text
    enrolled = client.post(
        "/api/v1/admin/enrollments/",
        headers=admin_headers,
        json={"student_id": user["id"], "course_id": course_id},
    )
    assert enrolled.status_code in (200, 201), enrolled.text
    return {
        **user,
        "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
    }


def _submit_checkin(client, session_id: str, student_headers: dict, extra_headers=None, lat=1.3483, lng=103.6831):
    headers = dict(student_headers)
    if extra_headers:
        headers.update(extra_headers)
    body = {"session_id": session_id, "device_fingerprint": f"fp_{uuid.uuid4().hex[:10]}"}
    if lat is not None:
        body["latitude"] = lat
    if lng is not None:
        body["longitude"] = lng
    return client.post("/api/v1/checkins/", headers=headers, json=body)


def _request_with_xff(xff: str | None, host: str = "127.0.0.1"):
    request = Mock()
    request.headers = {}
    if xff is not None:
        request.headers["x-forwarded-for"] = xff
    request.client = Mock(host=host)
    return request


class TestSingaporeCheckins:
    def test_private_and_singapore_ips_allowed_foreign_denied(
        self, client, test_session, test_course, auth_headers_admin
    ):
        session_id = test_session["id"]
        course_id = test_course["id"]

        private_student = _enroll_student(client, auth_headers_admin, course_id)
        private = _submit_checkin(
            client, session_id, private_student["headers"], extra_headers={"X-Forwarded-For": "192.168.10.4"}
        )
        assert private.status_code == 201, private.text

        loopback_student = _enroll_student(client, auth_headers_admin, course_id)
        loopback = _submit_checkin(
            client, session_id, loopback_student["headers"], extra_headers={"X-Forwarded-For": "127.0.0.1"}
        )
        assert loopback.status_code == 201, loopback.text

        sg_student = _enroll_student(client, auth_headers_admin, course_id)
        sg = _submit_checkin(
            client, session_id, sg_student["headers"], extra_headers={"X-Forwarded-For": "155.69.1.10"}
        )
        assert sg.status_code == 201, sg.text

        foreign_student = _enroll_student(client, auth_headers_admin, course_id)
        foreign = _submit_checkin(
            client, session_id, foreign_student["headers"], extra_headers={"X-Forwarded-For": "8.8.8.8"}
        )
        assert foreign.status_code == 403, foreign.text
        assert foreign.json()["detail"] == "Check-in not allowed from this location"

    def test_xff_first_hop_precedence(self, client, test_session, test_course, auth_headers_admin):
        session_id = test_session["id"]
        course_id = test_course["id"]

        foreign_first = _enroll_student(client, auth_headers_admin, course_id)
        denied = _submit_checkin(
            client,
            session_id,
            foreign_first["headers"],
            extra_headers={"X-Forwarded-For": "8.8.8.8, 155.69.1.10"},
        )
        assert denied.status_code == 403, denied.text

        private_first = _enroll_student(client, auth_headers_admin, course_id)
        allowed = _submit_checkin(
            client,
            session_id,
            private_first["headers"],
            extra_headers={"X-Forwarded-For": "10.0.0.8, 8.8.8.8"},
        )
        assert allowed.status_code == 201, allowed.text

    def test_gps_inside_and_outside_singapore(self, client, test_session, test_course, auth_headers_admin):
        session_id = test_session["id"]
        course_id = test_course["id"]

        inside = _enroll_student(client, auth_headers_admin, course_id)
        ok = _submit_checkin(
            client,
            session_id,
            inside["headers"],
            extra_headers={"X-Forwarded-For": "155.69.1.10"},
            lat=1.3483,
            lng=103.6831,
        )
        assert ok.status_code == 201, ok.text

        outside = _enroll_student(client, auth_headers_admin, course_id)
        denied = _submit_checkin(
            client,
            session_id,
            outside["headers"],
            extra_headers={"X-Forwarded-For": "155.69.1.10"},
            lat=40.7,
            lng=-74.0,
        )
        assert denied.status_code == 403, denied.text
        assert denied.json()["detail"] == "Check-in not allowed from this location"

        private_outside = _enroll_student(client, auth_headers_admin, course_id)
        private_denied = _submit_checkin(
            client,
            session_id,
            private_outside["headers"],
            extra_headers={"X-Forwarded-For": "192.168.0.9"},
            lat=40.7,
            lng=-74.0,
        )
        assert private_denied.status_code == 403, private_denied.text

    def test_client_ip_uses_first_forwarded_hop(self):
        assert client_ip(_request_with_xff("8.8.8.8, 155.69.1.10")) == "8.8.8.8"
        assert client_ip(_request_with_xff("10.0.0.1, 8.8.8.8")) == "10.0.0.1"
        assert client_ip(_request_with_xff(None, host="192.168.0.4")) == "192.168.0.4"
        assert client_ip(_request_with_xff("not-an-ip", host="10.0.0.9")) == "10.0.0.9"

    def test_singapore_helper_matrix_matches_current_policy(self):
        assert singapore_checkin_allowed("127.0.0.1", 1.3483, 103.6831) is True
        assert singapore_checkin_allowed("192.168.1.1", 1.3483, 103.6831) is True
        assert singapore_checkin_allowed("155.69.1.10", 1.3483, 103.6831) is True
        assert singapore_checkin_allowed("8.8.8.8", 1.3483, 103.6831) is False
        assert singapore_checkin_allowed("155.69.1.10", 40.7, -74.0) is False
        assert singapore_checkin_allowed("8.8.8.8", None, None) is False
        assert singapore_checkin_allowed("155.69.1.10", None, None) is True
