"""M2 image-size rejection and Redis rate-limit resilience.

Unit cases do not need a running API. HTTP cases use the isolated backend
fixture from tests/conftest.py and must not target the shared `saiv` database.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

_BACKEND = Path(__file__).resolve().parents[2] / "module2-backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import redis as redis_lib  # noqa: E402

from app.core.image_limits import (  # noqa: E402
    ensure_face_image_within_limit,
    face_image_max_chars,
)
from app.integrations.face_client import FaceCall  # noqa: E402
from app.core.redis import get_redis  # noqa: E402
from app.middleware import rate_limit as rate_limit_mod  # noqa: E402
from app.middleware.rate_limit import RateLimitMiddleware, check_rate_limit  # noqa: E402
from app.modules.checkins.schemas import CheckinCreate  # noqa: E402
from app.modules.checkins.service import _face_signals, submit_checkin  # noqa: E402
from app.modules.users.schemas import FaceEnrollRequest  # noqa: E402
from app.modules.users.service import enroll_face  # noqa: E402

PASSWORD = "testpassword123"
NTU_LAT, NTU_LNG = 1.3483, 103.6831


def _email(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}@test.com"


def _oversized_image() -> str:
    return "A" * (face_image_max_chars() + 1)


def _normal_image() -> str:
    return "AAAA"


@pytest.fixture
def redis_state():
    import app.core.redis as redis_mod

    previous = redis_mod._client
    yield redis_mod
    redis_mod._client = previous


class FakePipe:
    def __init__(self, store: dict[str, int]):
        self.store = store
        self.ops: list[tuple] = []

    def incr(self, key: str):
        self.ops.append(("incr", key))
        return self

    def expire(self, key: str, window: int):
        self.ops.append(("expire", key, window))
        return self

    def execute(self):
        results = []
        for op in self.ops:
            if op[0] == "incr":
                key = op[1]
                self.store[key] = self.store.get(key, 0) + 1
                results.append(self.store[key])
            else:
                results.append(True)
        return results


class FakeRedis:
    def __init__(self):
        self.store: dict[str, int] = {}
        self.pings = 0

    def ping(self):
        self.pings += 1
        return True

    def pipeline(self):
        return FakePipe(self.store)

    def close(self):
        return None


class DeadRedis:
    def pipeline(self):
        raise redis_lib.ConnectionError("lost")

    def ping(self):
        raise redis_lib.ConnectionError("lost")

    def close(self):
        return None


# ---------------------------------------------------------------------------
# Image size
# ---------------------------------------------------------------------------


class TestImageSizeHelper:
    def test_none_and_normal_images_pass(self):
        ensure_face_image_within_limit(None)
        ensure_face_image_within_limit("")
        ensure_face_image_within_limit(_normal_image())
        ensure_face_image_within_limit("data:image/jpeg;base64," + _normal_image())

    def test_oversized_image_is_413(self):
        with pytest.raises(HTTPException) as exc:
            ensure_face_image_within_limit(_oversized_image())
        assert exc.value.status_code == 413
        assert exc.value.detail == "Image payload too large"

    def test_data_url_prefix_does_not_inflate_limit(self):
        payload = "A" * face_image_max_chars()
        ensure_face_image_within_limit("data:image/png;base64," + payload)
        with pytest.raises(HTTPException) as exc:
            ensure_face_image_within_limit("data:image/png;base64," + payload + "A")
        assert exc.value.status_code == 413


class TestEnrollImageLimit:
    def test_oversized_enroll_does_not_call_m3_or_persist(self):
        user = Mock(id="user-1", camera_consent=True, face_enrolled=False, face_embedding_hash=None)
        db = Mock()
        request = Mock()
        payload = FaceEnrollRequest(image=_oversized_image())
        with patch("app.modules.users.service.face_client") as face:
            with patch("app.modules.users.service.users_repo") as users_repo:
                with pytest.raises(HTTPException) as exc:
                    enroll_face(db, user, payload, request)
        assert exc.value.status_code == 413
        face.enroll.assert_not_called()
        users_repo.save.assert_not_called()
        db.commit.assert_not_called()
        assert user.face_enrolled is False

    def test_normal_enroll_still_calls_m3(self):
        user = Mock(id="user-1", camera_consent=True, face_enrolled=False, face_embedding_hash=None)
        db = Mock()
        request = Mock()
        payload = FaceEnrollRequest(image=_normal_image())
        with patch("app.modules.users.service.face_client") as face:
            face.enroll.return_value = Mock(
                kind="ok",
                data={"enrollment_successful": True, "face_template_hash": "a" * 64, "quality_score": 0.9},
            )
            with patch("app.modules.users.service.users_repo"):
                with patch("app.modules.users.service.append_audit"):
                    result = enroll_face(db, user, payload, request)
        face.enroll.assert_called_once()
        assert result["face_enrolled"] is True
        db.commit.assert_called_once()


class TestCheckinImageLimit:
    def test_oversized_face_signals_does_not_call_m3(self):
        payload = CheckinCreate(
            session_id="sess-1",
            liveness_challenge_response=_oversized_image(),
        )
        with patch("app.modules.checkins.service.face_client") as face:
            with pytest.raises(HTTPException) as exc:
                _face_signals(payload, Mock(face_embedding_hash=None))
        assert exc.value.status_code == 413
        face.liveness.assert_not_called()
        face.verify.assert_not_called()

    def test_normal_face_signals_still_calls_m3(self):
        payload = CheckinCreate(
            session_id="sess-1",
            liveness_challenge_response=_normal_image(),
        )
        with patch("app.modules.checkins.service.face_client") as face:
            face.liveness.return_value = FaceCall(
                kind="ok",
                status=200,
                data={"liveness_passed": True, "liveness_score": 0.9, "face_embedding_hash": None},
            )
            signals = _face_signals(payload, Mock(face_embedding_hash=None))
        face.liveness.assert_called_once_with(_normal_image())
        assert signals["liveness_passed"] is True

    def test_oversized_submit_creates_no_row(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        session = Mock(
            id="sess-1",
            course_id="course-1",
            status="active",
            qr_code_secret=None,
            checkin_opens_at=now - timedelta(minutes=10),
            checkin_closes_at=now + timedelta(minutes=20),
            venue_latitude=NTU_LAT,
            venue_longitude=NTU_LNG,
            geofence_radius_meters=100,
            risk_threshold=0.5,
            require_liveness_check=False,
            require_face_match=False,
            course=None,
        )
        payload = CheckinCreate(
            session_id="sess-1",
            latitude=NTU_LAT,
            longitude=NTU_LNG,
            liveness_challenge_response=_oversized_image(),
        )
        user = Mock(id="student-1", face_embedding_hash=None)
        request = Mock()
        request.headers = {}
        request.client = Mock(host="127.0.0.1")
        created = []
        db = Mock()
        with (
            patch("app.modules.checkins.service.sessions_repo") as sessions_repo,
            patch("app.modules.checkins.service.enrollments_repo"),
            patch("app.modules.checkins.service.checkins_repo") as checkins_repo,
            patch("app.modules.checkins.service.devices_repo"),
            patch("app.modules.checkins.service.face_client") as face,
        ):
            sessions_repo.get_by_id.return_value = session
            checkins_repo.create.side_effect = lambda _db, row: created.append(row) or row
            with pytest.raises(HTTPException) as exc:
                submit_checkin(db, payload, user, request)
        assert exc.value.status_code == 413
        assert created == []
        checkins_repo.create.assert_not_called()
        face.liveness.assert_not_called()
        db.commit.assert_called()


class TestImageSizeHttp:
    def test_oversized_enroll_returns_413(self, client):
        email = _email("student")
        register = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": PASSWORD, "full_name": "Student", "role": "student"},
        )
        assert register.status_code == 201, register.text
        login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        client.put("/api/v1/users/me", headers=headers, json={"camera_consent": True})
        response = client.post(
            "/api/v1/users/me/face/enroll",
            headers=headers,
            json={"image": _oversized_image()},
            timeout=30.0,
        )
        assert response.status_code == 413, response.text
        assert response.json()["detail"] == "Image payload too large"
        me = client.get("/api/v1/users/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["face_enrolled"] is False

    def test_normal_enroll_is_not_413(self, client):
        email = _email("student")
        register = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": PASSWORD, "full_name": "Student", "role": "student"},
        )
        assert register.status_code == 201, register.text
        login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        client.put("/api/v1/users/me", headers=headers, json={"camera_consent": True})
        response = client.post(
            "/api/v1/users/me/face/enroll",
            headers=headers,
            json={"image": _normal_image()},
            timeout=30.0,
        )
        assert response.status_code != 413, response.text
        assert response.status_code != 500

    def test_oversized_checkin_returns_413_and_persists_nothing(
        self, client, test_session, test_course, auth_headers_admin
    ):
        email = _email("student")
        register = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": PASSWORD, "full_name": "Student", "role": "student"},
        )
        student_id = register.json()["id"]
        login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        enrolled = client.post(
            "/api/v1/admin/enrollments/",
            headers=auth_headers_admin,
            json={"student_id": student_id, "course_id": test_course["id"]},
        )
        assert enrolled.status_code in (200, 201), enrolled.text
        response = client.post(
            "/api/v1/checkins/",
            headers=headers,
            json={
                "session_id": test_session["id"],
                "latitude": NTU_LAT,
                "longitude": NTU_LNG,
                "liveness_challenge_response": _oversized_image(),
            },
            timeout=30.0,
        )
        assert response.status_code == 413, response.text
        listed = client.get(
            f"/api/v1/checkins/session/{test_session['id']}",
            headers=auth_headers_admin,
        )
        assert listed.status_code == 200, listed.text
        rows = listed.json()
        items = rows if isinstance(rows, list) else rows.get("items", rows)
        assert student_id not in {row.get("student_id") for row in items}


# ---------------------------------------------------------------------------
# Redis resilience
# ---------------------------------------------------------------------------


class TestRedisResilience:
    def test_initial_connection_failure_returns_none(self, monkeypatch, redis_state):
        redis_state._client = None

        class Boom:
            def ping(self):
                raise redis_lib.ConnectionError("down")

            def close(self):
                return None

        monkeypatch.setattr(
            redis_state.redis.Redis,
            "from_url",
            lambda *args, **kwargs: Boom(),
        )
        assert get_redis() is None
        assert redis_state._client is None

    def test_cached_client_failure_falls_back_to_memory(self, monkeypatch, redis_state):
        redis_state._client = DeadRedis()

        def still_down(*args, **kwargs):
            raise redis_lib.ConnectionError("still down")

        monkeypatch.setattr(redis_state.redis.Redis, "from_url", still_down)
        key = f"mem-dead:{uuid.uuid4().hex}"
        assert check_rate_limit(key, 1, 60) is True
        assert check_rate_limit(key, 1, 60) is False
        assert redis_state._client is None

    def test_cached_timeout_falls_back_to_memory(self, redis_state):
        class SlowRedis:
            def pipeline(self):
                raise redis_lib.TimeoutError("timed out")

            def close(self):
                return None

        redis_state._client = SlowRedis()
        key = f"mem-timeout:{uuid.uuid4().hex}"
        assert check_rate_limit(key, 2, 60) is True
        assert redis_state._client is None

    def test_reconnects_after_invalidate(self, monkeypatch, redis_state):
        alive = FakeRedis()
        redis_state._client = DeadRedis()
        key_memory = f"mem-recover:{uuid.uuid4().hex}"
        assert check_rate_limit(key_memory, 1, 60) is True
        assert redis_state._client is None

        monkeypatch.setattr(
            redis_state.redis.Redis,
            "from_url",
            lambda *args, **kwargs: alive,
        )
        assert get_redis() is alive
        key_redis = f"rl-recover:{uuid.uuid4().hex}"
        assert check_rate_limit(key_redis, 1, 60) is True
        assert check_rate_limit(key_redis, 1, 60) is False
        assert alive.store[key_redis] == 2

    def test_middleware_does_not_500_when_cached_redis_dies(self, monkeypatch, redis_state):
        redis_state._client = DeadRedis()
        app = FastAPI()

        @app.post("/api/v1/auth/login")
        def login():
            return {"ok": True}

        app.add_middleware(RateLimitMiddleware)
        client = TestClient(app)
        ip = f"203.0.113.{(int(uuid.uuid4().hex[:2], 16) % 200) + 1}"
        monkeypatch.setattr(rate_limit_mod.settings, "LOGIN_RATE_LIMIT", 100000)
        response = client.post("/api/v1/auth/login", headers={"X-Forwarded-For": ip})
        assert response.status_code == 200, response.text
        assert redis_state._client is None

    def test_invalidate_then_memory_still_enforces_limit(self, monkeypatch, redis_state):
        monkeypatch.setattr(rate_limit_mod, "get_redis", lambda: None)
        key = f"mem-only:{uuid.uuid4().hex}"
        assert check_rate_limit(key, 1, 60) is True
        assert check_rate_limit(key, 1, 60) is False
