import time

from app.core.errors import AppError
from app.core.redis import get_redis


async def hit(bucket: str, *, limit: int, window_seconds: int) -> None:
    """Fixed-window counter. Raises 429 once ``limit`` is exceeded within the window."""
    r = get_redis()
    window = int(time.time()) // window_seconds
    key = f"rl:{bucket}:{window}"
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, window_seconds)
    if count > limit:
        raise AppError(
            429,
            "rate_limited",
            "Too many attempts. Please wait and try again.",
            headers={"Retry-After": str(window_seconds - int(time.time()) % window_seconds)},
        )


async def reset(bucket: str, *, window_seconds: int) -> None:
    window = int(time.time()) // window_seconds
    await get_redis().delete(f"rl:{bucket}:{window}")
