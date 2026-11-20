from redis.asyncio import Redis

from app.core.config import get_settings

_client: Redis | None = None


def get_redis() -> Redis:
    """Shared Redis client. ``memory://`` uses fakeredis (tests / no-Docker dev only)."""
    global _client
    if _client is None:
        url = get_settings().redis_url
        if url.startswith("memory://"):
            from fakeredis import FakeAsyncRedis

            _client = FakeAsyncRedis(decode_responses=True)
        else:
            _client = Redis.from_url(url, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None
