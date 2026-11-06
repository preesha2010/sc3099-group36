"""Trusted-proxy X-Forwarded-For handling for Singapore checks and IP rate limits.

Unit cases do not need a running API. Mini-app cases use TestClient with a
synthetic connecting peer. Live HTTP cases (if a backend is up) only assert
that an untrusted client cannot spoof XFF.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Receive, Scope, Send

_BACKEND = Path(__file__).resolve().parents[2] / "module2-backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.core.utils import client_ip, singapore_checkin_allowed  # noqa: E402
from app.middleware import rate_limit as rate_limit_mod  # noqa: E402
from app.middleware.rate_limit import RateLimitMiddleware  # noqa: E402

TRUSTED_PROXY = "10.0.0.1"
TRUSTED_PROXY_CIDR = "10.0.0.0/8"
UNTRUSTED_PEER = "203.0.113.50"
NTU_IP = "155.69.1.10"
FOREIGN_IP = "8.8.8.8"
PRIVATE_IP = "192.168.10.4"


def _request(*, host: str | None, xff: str | None = None):
    request = Mock()
    request.headers = {}
    if xff is not None:
        request.headers["x-forwarded-for"] = xff
    request.client = Mock(host=host) if host is not None else None
    return request


def _trust(monkeypatch, value: str) -> None:
    monkeypatch.setattr(get_settings(), "TRUSTED_PROXY_IPS", value)


class _SetPeer:
    """ASGI wrapper so TestClient can present a chosen connecting IP."""

    def __init__(self, app: ASGIApp, host: str):
        self.app = app
        self.host = host

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            scope = dict(scope)
            scope["client"] = (self.host, 50000)
        await self.app(scope, receive, send)


def _mini_login_app(peer: str) -> TestClient:
    inner = FastAPI()

    @inner.post("/api/v1/auth/login")
    def login():
        return {"ok": True}

    @inner.post("/api/v1/auth/register")
    def register():
        return {"ok": True}

    inner.add_middleware(RateLimitMiddleware)
    return TestClient(_SetPeer(inner, peer))


# ---------------------------------------------------------------------------
# client_ip resolution
# ---------------------------------------------------------------------------


class TestClientIpTrust:
    def test_untrusted_peer_xff_is_ignored_by_default(self):
        assert get_settings().TRUSTED_PROXY_IPS == ""
        assert client_ip(_request(host=UNTRUSTED_PEER, xff=NTU_IP)) == UNTRUSTED_PEER
        assert client_ip(_request(host=PRIVATE_IP, xff=FOREIGN_IP)) == PRIVATE_IP
        assert client_ip(_request(host="127.0.0.1", xff=FOREIGN_IP)) == "127.0.0.1"

    def test_empty_trusted_list_never_reads_xff(self, monkeypatch):
        _trust(monkeypatch, "   ,  ")
        assert client_ip(_request(host=TRUSTED_PROXY, xff=FOREIGN_IP)) == TRUSTED_PROXY

    def test_invalid_trusted_entries_are_skipped(self, monkeypatch):
        _trust(monkeypatch, "not-a-cidr, also bad")
        assert client_ip(_request(host=TRUSTED_PROXY, xff=FOREIGN_IP)) == TRUSTED_PROXY

    def test_boolean_flag_cannot_enable_trust(self, monkeypatch):
        _trust(monkeypatch, "true")
        assert client_ip(_request(host=UNTRUSTED_PEER, xff=NTU_IP)) == UNTRUSTED_PEER
        assert client_ip(_request(host="127.0.0.1", xff=FOREIGN_IP)) == "127.0.0.1"

    def test_trusted_proxy_uses_rightmost_untrusted_hop(self, monkeypatch):
        _trust(monkeypatch, TRUSTED_PROXY)
        assert client_ip(_request(host=TRUSTED_PROXY, xff=FOREIGN_IP)) == FOREIGN_IP
        assert client_ip(_request(host=TRUSTED_PROXY, xff=f"{FOREIGN_IP}, {NTU_IP}")) == NTU_IP
        assert client_ip(_request(host=TRUSTED_PROXY, xff=f"{NTU_IP}, {FOREIGN_IP}")) == FOREIGN_IP

    def test_trusted_proxy_skips_trusted_hops_from_the_right(self, monkeypatch):
        _trust(monkeypatch, f"{TRUSTED_PROXY}, {TRUSTED_PROXY_CIDR}")
        assert (
            client_ip(_request(host=TRUSTED_PROXY, xff=f"{FOREIGN_IP}, 10.0.0.8"))
            == FOREIGN_IP
        )

    def test_trusted_proxy_malformed_chain_falls_back_to_peer(self, monkeypatch):
        _trust(monkeypatch, TRUSTED_PROXY)
        assert client_ip(_request(host=TRUSTED_PROXY, xff="not-an-ip")) == TRUSTED_PROXY
        assert client_ip(_request(host=TRUSTED_PROXY, xff="not-an-ip, also-bad")) == TRUSTED_PROXY
        assert client_ip(_request(host=TRUSTED_PROXY, xff="")) == TRUSTED_PROXY
        assert client_ip(_request(host=TRUSTED_PROXY, xff=None)) == TRUSTED_PROXY

    def test_malformed_hop_cannot_hide_a_spoofed_left_address(self, monkeypatch):
        _trust(monkeypatch, TRUSTED_PROXY)
        assert (
            client_ip(_request(host=TRUSTED_PROXY, xff=f"{FOREIGN_IP}, not-an-ip, {NTU_IP}"))
            == NTU_IP
        )

    def test_untrusted_peer_cannot_use_trusted_proxy_config(self, monkeypatch):
        _trust(monkeypatch, TRUSTED_PROXY)
        assert client_ip(_request(host=UNTRUSTED_PEER, xff=NTU_IP)) == UNTRUSTED_PEER
        assert client_ip(_request(host=UNTRUSTED_PEER, xff=f"{NTU_IP}, {TRUSTED_PROXY}")) == UNTRUSTED_PEER

    def test_loopback_and_missing_peer_stay_compatible(self):
        assert client_ip(_request(host="127.0.0.1")) == "127.0.0.1"
        assert client_ip(_request(host="192.168.0.4")) == "192.168.0.4"
        assert client_ip(_request(host="testclient")) == "127.0.0.1"
        assert client_ip(_request(host=None)) == "127.0.0.1"

    def test_cidr_match_for_docker_bridge_proxy(self, monkeypatch):
        _trust(monkeypatch, "172.16.0.0/12")
        assert client_ip(_request(host="172.18.0.2", xff=FOREIGN_IP)) == FOREIGN_IP
        assert client_ip(_request(host="192.168.1.9", xff=FOREIGN_IP)) == "192.168.1.9"


class TestSingaporeUsesResolvedIp:
    def test_spoofed_foreign_xff_does_not_deny_private_peer(self):
        ip = client_ip(_request(host="127.0.0.1", xff=FOREIGN_IP))
        assert ip == "127.0.0.1"
        assert singapore_checkin_allowed(ip, 1.3483, 103.6831) is True

    def test_trusted_proxy_foreign_client_is_denied(self, monkeypatch):
        _trust(monkeypatch, TRUSTED_PROXY)
        ip = client_ip(_request(host=TRUSTED_PROXY, xff=FOREIGN_IP))
        assert ip == FOREIGN_IP
        assert singapore_checkin_allowed(ip, 1.3483, 103.6831) is False
        assert singapore_checkin_allowed(ip, None, None) is False

    def test_trusted_proxy_ntu_client_is_allowed(self, monkeypatch):
        _trust(monkeypatch, TRUSTED_PROXY)
        ip = client_ip(_request(host=TRUSTED_PROXY, xff=NTU_IP))
        assert singapore_checkin_allowed(ip, 1.3483, 103.6831) is True
        assert singapore_checkin_allowed(ip, None, None) is True

    def test_gps_still_denies_outside_singapore(self):
        assert singapore_checkin_allowed("127.0.0.1", 40.7, -74.0) is False
        assert singapore_checkin_allowed(NTU_IP, 40.7, -74.0) is False


# ---------------------------------------------------------------------------
# IP-based rate limiting uses the resolved client IP
# ---------------------------------------------------------------------------


class TestRateLimitUsesResolvedIp:
    def test_untrusted_xff_does_not_key_the_spoofed_address(self, monkeypatch):
        from app.core.redis import get_redis

        redis_client = get_redis()
        if redis_client is None:
            pytest.skip("Redis is required for rate-limit key assertions")

        spoofed = f"203.0.113.{(int(uuid.uuid4().hex[:2], 16) % 200) + 1}"
        peer = f"198.51.100.{(int(uuid.uuid4().hex[:2], 16) % 200) + 1}"
        monkeypatch.setattr(rate_limit_mod.settings, "LOGIN_RATE_LIMIT", 100000)
        client = _mini_login_app(peer)
        response = client.post("/api/v1/auth/login", headers={"X-Forwarded-For": spoofed})
        assert response.status_code == 200, response.text
        assert redis_client.get(f"rl:login:{spoofed}") is None
        assert redis_client.get(f"rl:login:{peer}") == "1"

    def test_trusted_proxy_keys_the_forwarded_client(self, monkeypatch):
        from app.core.redis import get_redis

        redis_client = get_redis()
        if redis_client is None:
            pytest.skip("Redis is required for rate-limit key assertions")

        forwarded = f"203.0.113.{(int(uuid.uuid4().hex[:2], 16) % 200) + 1}"
        _trust(monkeypatch, TRUSTED_PROXY)
        monkeypatch.setattr(rate_limit_mod.settings, "LOGIN_RATE_LIMIT", 100000)
        client = _mini_login_app(TRUSTED_PROXY)
        response = client.post("/api/v1/auth/login", headers={"X-Forwarded-For": forwarded})
        assert response.status_code == 200, response.text
        assert redis_client.get(f"rl:login:{forwarded}") == "1"
        assert redis_client.get(f"rl:login:{TRUSTED_PROXY}") is None

    def test_untrusted_xff_cannot_bypass_per_ip_login_limit(self, monkeypatch):
        from app.core.redis import get_redis

        redis_client = get_redis()
        if redis_client is None:
            pytest.skip("Redis is required for rate-limit key assertions")

        peer = f"198.51.100.{(int(uuid.uuid4().hex[:2], 16) % 200) + 1}"
        monkeypatch.setattr(rate_limit_mod.settings, "LOGIN_RATE_LIMIT", 2)
        client = _mini_login_app(peer)
        assert client.post("/api/v1/auth/login", headers={"X-Forwarded-For": "203.0.113.1"}).status_code == 200
        assert client.post("/api/v1/auth/login", headers={"X-Forwarded-For": "203.0.113.2"}).status_code == 200
        limited = client.post("/api/v1/auth/login", headers={"X-Forwarded-For": "203.0.113.3"})
        assert limited.status_code == 429
        assert limited.json()["detail"] == "Rate limit exceeded"
        assert redis_client.get(f"rl:login:{peer}") == "3"

    def test_trusted_proxy_enforces_limit_on_forwarded_ip(self, monkeypatch):
        from app.core.redis import get_redis

        redis_client = get_redis()
        if redis_client is None:
            pytest.skip("Redis is required for rate-limit key assertions")

        forwarded = f"203.0.113.{(int(uuid.uuid4().hex[:2], 16) % 200) + 1}"
        other = f"203.0.113.{(int(uuid.uuid4().hex[:2], 16) % 200) + 1}"
        if other == forwarded:
            other = "203.0.113.250"
        _trust(monkeypatch, TRUSTED_PROXY)
        monkeypatch.setattr(rate_limit_mod.settings, "LOGIN_RATE_LIMIT", 1)
        client = _mini_login_app(TRUSTED_PROXY)
        assert client.post("/api/v1/auth/login", headers={"X-Forwarded-For": forwarded}).status_code == 200
        limited = client.post("/api/v1/auth/login", headers={"X-Forwarded-For": forwarded})
        assert limited.status_code == 429
        other_ok = client.post("/api/v1/auth/login", headers={"X-Forwarded-For": other})
        assert other_ok.status_code == 200, other_ok.text


# ---------------------------------------------------------------------------
# Live HTTP: default Compose/M1 path (no trusted proxy)
# ---------------------------------------------------------------------------


class TestLiveUntrustedXffIgnored:
    """Requires the isolated API to run with Uvicorn --no-proxy-headers."""

    def test_spoofed_foreign_xff_does_not_block_singapore_gps(
        self, client, test_session, test_course, auth_headers_admin
    ):
        email = f"xff_{uuid.uuid4().hex[:10]}@test.com"
        registered = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "testpassword123",
                "full_name": "Xff Student",
                "role": "student",
            },
        )
        assert registered.status_code == 201, registered.text
        student_id = registered.json()["id"]
        login = client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpassword123"}
        )
        assert login.status_code == 200, login.text
        enrolled = client.post(
            "/api/v1/admin/enrollments/",
            headers=auth_headers_admin,
            json={"student_id": student_id, "course_id": test_course["id"]},
        )
        assert enrolled.status_code in (200, 201), enrolled.text
        headers = {
            "Authorization": f"Bearer {login.json()['access_token']}",
            "X-Forwarded-For": FOREIGN_IP,
        }
        response = client.post(
            "/api/v1/checkins/",
            headers=headers,
            json={
                "session_id": test_session["id"],
                "latitude": 1.3483,
                "longitude": 103.6831,
                "device_fingerprint": f"fp_{uuid.uuid4().hex[:10]}",
            },
        )
        assert response.status_code == 201, response.text

    def test_live_login_does_not_key_spoofed_xff(self, client):
        from app.core.redis import get_redis

        redis_client = get_redis()
        if redis_client is None:
            pytest.skip("Redis is required for rate-limit key assertions")
        spoofed = f"203.0.113.{(int(uuid.uuid4().hex[:2], 16) % 200) + 1}"
        before = int(redis_client.get(f"rl:login:{spoofed}") or 0)
        response = client.post(
            "/api/v1/auth/login",
            json={"email": f"nomatch_{uuid.uuid4().hex[:8]}@test.com", "password": "wrongpassword"},
            headers={"X-Forwarded-For": spoofed},
        )
        assert response.status_code == 401
        assert int(redis_client.get(f"rl:login:{spoofed}") or 0) == before
