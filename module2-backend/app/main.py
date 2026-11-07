"""
SAIV Backend API - Module 2

See docs/API-SPECIFICATION.md for endpoint contracts.
Routers are mounted at /api/v1; /health stays unprefixed.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api_router import api_router
from app.core.config import get_settings
from app.core.redis import get_redis, invalidate_redis
from app.db.session import engine, init_db
from app.middleware.rate_limit import RateLimitMiddleware

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    _schedule_face_probe()
    yield


app = FastAPI(
    title="SAIV Backend API",
    description="Secure Attendance & Identity Verification System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


# --- Health -----------------------------------------------------------------
# The spec's contract is {"status": "healthy"}; the extra fields report each
# dependency for the instructor dashboard's service-health panel. Two rules
# from the public tests shape this:
#   * always 200: the test fixtures skip the whole suite if /health is not 200,
#     so a dependency being down is reported in the body, not the status code
#   * under 0.5 s: database and Redis are probed in parallel with a short
#     deadline, and the assembled body is cached. Module 3 /health can take
#     ~1s, so that probe uses FACE_HEALTH_TIMEOUT in the background and
#     /health returns the last known face_service value without waiting.

HEALTH_TTL_SECONDS = 5.0
HEALTH_CHECK_DEADLINE = 0.35

_health_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="health")
_health_lock = threading.Lock()
_health_cache: dict = {"at": 0.0, "body": None}
_face_lock = threading.Lock()
_face_health: dict = {"value": "unavailable", "at": 0.0, "inflight": False}


def _check_database() -> str:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return "connected"


def _check_redis() -> str:
    client = get_redis()
    if client is None:
        return "unavailable"
    try:
        client.ping()
        return "connected"
    except Exception:
        invalidate_redis()
        return "unavailable"


def _face_status_from_health(status_code: int, payload: object) -> str:
    """Map Module 3 GET /health to the dashboard's connected/unavailable field.

    Connection success is not enough: the body must be the documented
    {"status": "healthy", ...} object. Non-200, malformed, or any other
    status string stays unavailable.
    """
    if status_code != 200:
        return "unavailable"
    if not isinstance(payload, dict) or payload.get("status") != "healthy":
        return "unavailable"
    return "connected"


def _check_face_service() -> str:
    cfg = get_settings()
    url = cfg.FACE_SERVICE_URL.rstrip("/") + "/health"
    try:
        response = httpx.get(url, timeout=cfg.FACE_HEALTH_TIMEOUT)
        try:
            payload = response.json()
        except Exception:
            payload = None
        return _face_status_from_health(response.status_code, payload)
    except Exception:
        return "unavailable"


def _face_value() -> str:
    with _face_lock:
        return str(_face_health["value"])


def _run_face_probe() -> None:
    try:
        value = _check_face_service()
    except Exception:
        value = "unavailable"
    with _face_lock:
        _face_health["value"] = value
        _face_health["at"] = time.monotonic()
        _face_health["inflight"] = False


def _schedule_face_probe() -> None:
    """Start a background M3 /health probe unless one is fresh or in flight."""
    with _face_lock:
        if _face_health["inflight"]:
            return
        last = _face_health["at"]
        if last and time.monotonic() - last < HEALTH_TTL_SECONDS:
            return
        _face_health["inflight"] = True
    _health_pool.submit(_run_face_probe)


def _probe(check):
    return _health_pool.submit(check)


def _result(future) -> str:
    try:
        return future.result(timeout=HEALTH_CHECK_DEADLINE)
    except FutureTimeout:
        return "unavailable"
    except Exception:
        return "unavailable"


@app.get("/health")
def health_check():
    """API status plus database, Redis and face-service reachability."""
    _schedule_face_probe()
    with _health_lock:
        cached = _health_cache["body"]
        if cached is not None and time.monotonic() - _health_cache["at"] < HEALTH_TTL_SECONDS:
            body = dict(cached)
            body["face_service"] = _face_value()
            return body

    database = _probe(_check_database)
    redis_ = _probe(_check_redis)
    body = {
        "status": "healthy",
        "api": "ok",
        "database": _result(database),
        "redis": _result(redis_),
        "face_service": _face_value(),
    }

    with _health_lock:
        _health_cache.update(at=time.monotonic(), body=body)
    return body
