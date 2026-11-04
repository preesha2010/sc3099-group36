from typing import Optional

import redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.core.config import get_settings

settings = get_settings()

_client: Optional[redis.Redis] = None

REDIS_TRANSIENT_ERRORS = (RedisConnectionError, RedisTimeoutError, OSError, TimeoutError)


def invalidate_redis() -> None:
    """Drop a cached client so the next get_redis() can reconnect."""
    global _client
    previous = _client
    _client = None
    if previous is None:
        return
    try:
        previous.close()
    except Exception:
        pass


def get_redis() -> Optional[redis.Redis]:
    global _client
    if _client is not None:
        return _client
    try:
        _client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_timeout=1,
            socket_connect_timeout=1,
        )
        _client.ping()
        return _client
    except Exception:
        invalidate_redis()
        return None
