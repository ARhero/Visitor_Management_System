"""Phone OTP for visitors (sent as a WhatsApp authentication message).

Redis only: ``otp:{org}:{phone}`` holds an HMAC of the code (never the code itself),
the wrong-attempt count and a 5-minute TTL. Sending is rate limited per phone, per IP
and per gate, with a short resend cooldown.
"""

import hashlib
import hmac
import secrets
from uuid import UUID

from app.core import rate_limit
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.redis import get_redis

TEN_MIN = 600


def _key(org_id: UUID, phone: str, purpose: str) -> str:
    return f"otp:{org_id}:{phone}" if purpose == "visit" else f"otp-{purpose}:{org_id}:{phone}"


def _digest(org_id: UUID, phone: str, code: str, purpose: str) -> str:
    secret = get_settings().jwt_secret.encode()
    msg = f"{purpose}:{org_id}:{phone}:{code}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


async def issue(org_id: UUID, gate_id: UUID, phone: str, ip: str, purpose: str = "visit") -> str:
    """Create a code after the rate-limit checks and return it (the caller sends it).

    ``purpose`` keeps codes apart: a check-in code can't open the privacy page and the
    other way round, and each has its own resend cooldown."""
    s = get_settings()
    r = get_redis()
    cooldown = f"otp-cd:{org_id}:{phone}" + ("" if purpose == "visit" else f":{purpose}")
    ttl = await r.ttl(cooldown)
    if ttl and ttl > 0:
        raise AppError(
            429,
            "otp_cooldown",
            f"Please wait {ttl} seconds before asking for another code",
            {"retry_after": ttl},
            headers={"Retry-After": str(ttl)},
        )
    await rate_limit.hit(f"otp-phone:{phone}", limit=s.otp_per_phone_limit, window_seconds=TEN_MIN)
    await rate_limit.hit(f"otp-ip:{ip}", limit=s.otp_per_ip_limit, window_seconds=TEN_MIN)
    await rate_limit.hit(f"otp-gate:{gate_id}", limit=s.otp_per_gate_limit, window_seconds=TEN_MIN)

    code = f"{secrets.randbelow(10**6):06d}"
    key = _key(org_id, phone, purpose)
    await r.delete(key)
    await r.hset(key, mapping={"h": _digest(org_id, phone, code, purpose), "a": 0})
    await r.expire(key, s.otp_ttl_seconds)
    await r.set(cooldown, 1, ex=s.otp_resend_seconds)
    return code


async def check(org_id: UUID, phone: str, code: str, purpose: str = "visit") -> None:
    """Raise unless ``code`` is right. A code works once; too many wrong tries kill it."""
    s = get_settings()
    r = get_redis()
    key = _key(org_id, phone, purpose)
    stored = await r.hgetall(key)
    if not stored:
        raise AppError(400, "otp_expired", "This code has expired. Please ask for a new one.")
    if hmac.compare_digest(stored["h"], _digest(org_id, phone, code, purpose)):
        await r.delete(key)
        return
    attempts = await r.hincrby(key, "a", 1)
    if attempts >= s.otp_max_attempts:
        await r.delete(key)
        raise AppError(429, "otp_locked", "Too many wrong codes. Please ask for a new code.")
    raise AppError(
        400,
        "otp_invalid",
        "That code is not right",
        {"attempts_left": s.otp_max_attempts - attempts},
    )
