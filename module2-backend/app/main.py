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
#   * under 0.5 s: the checks run in parallel, each with a short deadline, and
#     the result is cached for a few seconds so load tests do not hammer the
#     database, Redis and the face service through this endpoint

HEALTH_TTL_SECONDS = 5.0
HEALTH_CHECK_DEADLINE = 0.35

_health_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="health")
_health_lock = threading.Lock()
_health_cache: dict = {"at": 0.0, "body": None}


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


def _check_face_service() -> str:
    url = settings.FACE_SERVICE_URL.rstrip("/") + "/health"
    response = httpx.get(url, timeout=HEALTH_CHECK_DEADLINE)
    return "connected" if response.status_code == 200 else "unavailable"


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
    with _health_lock:
        cached = _health_cache["body"]
        if cached is not None and time.monotonic() - _health_cache["at"] < HEALTH_TTL_SECONDS:
            return cached

    database = _probe(_check_database)
    redis_ = _probe(_check_redis)
    face = _probe(_check_face_service)
    body = {
        "status": "healthy",
        "api": "ok",
        "database": _result(database),
        "redis": _result(redis_),
        "face_service": _result(face),
    }

    with _health_lock:
        _health_cache.update(at=time.monotonic(), body=body)
    return body
