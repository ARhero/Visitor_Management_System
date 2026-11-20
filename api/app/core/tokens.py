"""Short-lived signed tokens for people without a staff account.

| typ       | who holds it                 | grants                                   |
|-----------|------------------------------|------------------------------------------|
| visitor   | visitor, after phone OTP     | fill in and submit one check-in          |
| visit     | visitor, after submitting    | read / cancel that one visit             |
| respond   | host, inside WhatsApp link   | see and answer that one visit            |
| upload    | visitor, after photo upload  | attach that file to their own visit      |
| media     | anyone with a signed URL     | read one stored file for a few minutes   |
| login     | staff, inside WhatsApp link  | sign in once (magic link)                |
| evac      | safety contacts (WhatsApp)   | read one site's evacuation list, 6 hours |
| privacy   | visitor, after phone OTP     | see / download / ask to erase own data   |
| pass      | visitor (QR on the pass)     | Ed25519-signed; see app.services.passes  |

All but ``pass`` are HS256 with JWT_SECRET and carry ``typ`` so one kind can never be
used as another.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.core.config import get_settings
from app.core.errors import AppError


def sign(typ: str, claims: dict[str, Any], expires: datetime | timedelta) -> str:
    exp = datetime.now(UTC) + expires if isinstance(expires, timedelta) else expires
    payload = {**claims, "typ": typ, "exp": int(exp.timestamp())}
    s = get_settings()
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def verify(typ: str, token: str, *, message: str = "This link has expired") -> dict[str, Any]:
    s = get_settings()
    try:
        claims = jwt.decode(token, s.jwt_secret, algorithms=["HS256"], options={"require": ["exp"]})
    except jwt.ExpiredSignatureError as exc:
        raise AppError(401, "expired", message) from exc
    except jwt.PyJWTError as exc:
        raise AppError(401, "invalid_token", "This link is not valid") from exc
    if claims.get("typ") != typ:
        raise AppError(401, "invalid_token", "This link is not valid")
    return claims
