"""Idempotency-Key handling for guard actions.

A guard's phone may retry a check-in after a timeout, or replay it from the offline
queue hours later. The first response for a key is stored for 24 hours and returned
again for every retry, so a retried request never acts twice and the client always
gets the same answer.
"""

import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request

from app.core.errors import AppError
from app.core.redis import get_redis

TTL = 24 * 3600


async def run(
    request: Request, scope: str, fn: Callable[[], Awaitable[dict[str, Any]]]
) -> dict[str, Any]:
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key or len(key) > 100:
        raise AppError(400, "idempotency_key_required", "Idempotency-Key header is required")
    r = get_redis()
    k = f"idem:{scope}:{request.url.path}:{key}"
    cached = await r.get(k)
    if cached:
        return json.loads(cached)
    if not await r.set(f"{k}:lock", 1, nx=True, ex=30):
        raise AppError(409, "in_progress", "This request is already being processed")
    try:
        result = await fn()
        await r.set(k, json.dumps(result, default=str), ex=TTL)
        return result
    finally:
        await r.delete(f"{k}:lock")
