from typing import Optional

import redis

from app.core.config import get_settings

settings = get_settings()

_client: Optional[redis.Redis] = None


def get_redis() -> Optional[redis.Redis]:
    global _client
    if _client is not None:
        return _client
    try:
        _client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_timeout=1)
        _client.ping()
        return _client
    except Exception:
        _client = None
        return None
