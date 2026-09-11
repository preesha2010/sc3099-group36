from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.core.redis import get_redis
from app.core.utils import client_ip

settings = get_settings()

_memory_counters: dict[str, tuple[int, float]] = {}


def _incr(key: str, window: int) -> int:
    r = get_redis()
    if r is not None:
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, window)
        current, _ = pipe.execute()
        return int(current)

    import time

    now = time.time()
    count, expires = _memory_counters.get(key, (0, now + window))
    if now > expires:
        count, expires = 0, now + window
    count += 1
    _memory_counters[key] = (count, expires)
    return count


def check_rate_limit(key: str, limit: int, window: int) -> bool:
    return _incr(key, window) <= limit


def enforce_ip_limit(prefix: str, ip: str, limit: int, window: int) -> bool:
    return check_rate_limit(f"rl:{prefix}:{ip}", limit, window)


def enforce_user_limit(prefix: str, user_id: str, limit: int, window: int) -> bool:
    return check_rate_limit(f"rl:{prefix}:{user_id}", limit, window)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in {"/health", "/metrics", "/docs", "/openapi.json", "/redoc"}:
            return await call_next(request)

        ip = client_ip(request)
        if path.endswith("/auth/login") and request.method == "POST":
            if not enforce_ip_limit("login", ip, settings.LOGIN_RATE_LIMIT, settings.LOGIN_RATE_WINDOW):
                return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
        elif path.endswith("/auth/register") and request.method == "POST":
            if not enforce_ip_limit("register", ip, settings.REGISTER_RATE_LIMIT, settings.REGISTER_RATE_WINDOW):
                return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})

        response = await call_next(request)
        return response


def rate_limit_api_user(user_id: str) -> None:
    from fastapi import HTTPException

    if not enforce_user_limit("api", user_id, settings.API_RATE_LIMIT, settings.API_RATE_WINDOW):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


def rate_limit_checkin(user_id: str) -> None:
    from fastapi import HTTPException

    if not enforce_user_limit(
        "checkin", user_id, settings.CHECKIN_RATE_LIMIT, settings.CHECKIN_RATE_WINDOW
    ):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
