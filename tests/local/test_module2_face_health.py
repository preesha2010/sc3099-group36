"""Module 2 GET /health face-service probe: timeout, validation, cache, FaceClient isolation."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

_BACKEND = Path(__file__).resolve().parents[2] / "module2-backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.integrations.face_client import FaceClient  # noqa: E402
from app.main import (  # noqa: E402
    HEALTH_CHECK_DEADLINE,
    HEALTH_TTL_SECONDS,
    _check_face_service,
    _face_health,
    _face_lock,
    _face_status_from_health,
    _health_cache,
    _health_lock,
    _run_face_probe,
    _schedule_face_probe,
    health_check,
)


def _reset_health_state() -> None:
    with _health_lock:
        _health_cache.update(at=0.0, body=None)
    with _face_lock:
        _face_health.update(value="unavailable", at=0.0, inflight=False)


def _healthy_response(payload=None, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json = Mock(return_value=payload if payload is not None else {
        "status": "healthy",
        "service": "face-recognition",
    })
    return response


@pytest.fixture(autouse=True)
def _isolate_health(monkeypatch):
    _reset_health_state()
    monkeypatch.setattr("app.main._check_database", lambda: "connected")
    monkeypatch.setattr("app.main._check_redis", lambda: "connected")
    monkeypatch.setattr(
        httpx,
        "get",
        Mock(side_effect=httpx.ConnectError("unit-test isolation")),
    )
    yield
    _reset_health_state()


def test_face_health_timeout_is_configurable_and_separate_from_checkin_client():
    settings = get_settings()
    assert settings.FACE_HEALTH_TIMEOUT == 3.0
    assert HEALTH_CHECK_DEADLINE == 0.35
    client = FaceClient()
    assert client.timeout == 5.0
    assert client.timeout != settings.FACE_HEALTH_TIMEOUT


def test_slow_healthy_m3_within_face_timeout_is_connected(monkeypatch):
    def fake_get(url, timeout=None):
        assert timeout == 3.0
        assert url.endswith("/health")
        time.sleep(0.40)
        return _healthy_response()

    monkeypatch.setattr(httpx, "get", fake_get)
    started = time.perf_counter()
    assert _check_face_service() == "connected"
    elapsed = time.perf_counter() - started
    assert elapsed >= 0.40
    assert elapsed < 3.0


def test_unreachable_m3_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "get",
        Mock(side_effect=httpx.ConnectError("refused")),
    )
    assert _check_face_service() == "unavailable"


def test_timeout_m3_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "get",
        Mock(side_effect=httpx.TimeoutException("slow")),
    )
    assert _check_face_service() == "unavailable"


@pytest.mark.parametrize(
    "status_code,payload",
    [
        (503, {"status": "healthy"}),
        (200, {"status": "degraded"}),
        (200, {"ok": True}),
        (200, ["healthy"]),
        (200, None),
    ],
)
def test_unhealthy_or_malformed_m3_is_unavailable(monkeypatch, status_code, payload):
    response = _healthy_response(payload=payload, status_code=status_code)
    if payload is None:
        response.json = Mock(side_effect=ValueError("not json"))
    monkeypatch.setattr(httpx, "get", Mock(return_value=response))
    assert _check_face_service() == "unavailable"
    assert _face_status_from_health(200, {"status": "healthy"}) == "connected"


def test_health_response_shape_and_http_200():
    body = health_check()
    assert body["status"] == "healthy"
    assert body["api"] == "ok"
    assert body["database"] == "connected"
    assert body["redis"] == "connected"
    assert body["face_service"] in {"connected", "unavailable"}
    assert set(body) == {"status", "api", "database", "redis", "face_service"}


def test_health_http_does_not_wait_for_slow_face_probe(monkeypatch):
    release = threading.Event()

    def slow_face():
        release.wait(timeout=2.0)
        return "connected"

    monkeypatch.setattr("app.main._check_face_service", slow_face)
    started = time.perf_counter()
    body = health_check()
    elapsed = time.perf_counter() - started
    release.set()
    assert elapsed < 0.5
    assert body["status"] == "healthy"
    assert body["face_service"] == "unavailable"


def test_background_probe_updates_last_known_face_status(monkeypatch):
    monkeypatch.setattr("app.main._check_face_service", lambda: "connected")
    _run_face_probe()
    body = health_check()
    assert body["face_service"] == "connected"
    assert body["status"] == "healthy"


def test_repeated_health_uses_cache_and_does_not_reprobe_face(monkeypatch):
    calls = {"n": 0}

    def counting_get(url, timeout=None):
        calls["n"] += 1
        return _healthy_response()

    monkeypatch.setattr(httpx, "get", counting_get)
    _run_face_probe()
    assert calls["n"] == 1
    _schedule_face_probe()
    _schedule_face_probe()
    time.sleep(0.05)
    assert calls["n"] == 1
    first = health_check()
    second = health_check()
    assert first["face_service"] == "connected"
    assert second["face_service"] == "connected"
    assert calls["n"] == 1
    assert HEALTH_TTL_SECONDS >= 1.0


def test_face_health_timeout_setting_does_not_change_face_client(monkeypatch):
    monkeypatch.setattr(get_settings(), "FACE_HEALTH_TIMEOUT", 3.0)
    assert FaceClient().timeout == 5.0
    assert FaceClient(timeout=5.0).timeout == 5.0
