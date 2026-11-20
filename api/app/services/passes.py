"""Visitor passes: a compact Ed25519-signed JWT shown as a QR code.

The token carries only a random ``jti`` and an expiry, never names or IDs, so a
photographed QR leaks nothing. The guard scanner (Phase 3) verifies the signature
offline-capable and then checks the ``jti`` server-side for revocation / single use.
"""

import base64
import secrets
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import jwt
import segno
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.config import get_settings
from app.core.errors import AppError

ALG = "EdDSA"


@lru_cache
def _private_key() -> Ed25519PrivateKey:
    s = get_settings()
    pem = s.pass_signing_key.replace("\\n", "\n").strip()
    if not pem:
        if s.env == "prod":
            raise RuntimeError("PASS_SIGNING_KEY must be set in production")
        if s.env == "test":
            return Ed25519PrivateKey.generate()
        path = Path(s.pass_key_file)
        if not path.exists():
            key = Ed25519PrivateKey.generate()
            path.write_bytes(
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
        pem = path.read_text()
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise RuntimeError("PASS_SIGNING_KEY must be an Ed25519 private key")
    return key


def public_key_pem() -> str:
    """Published to guard devices so they can verify passes offline."""
    return (
        _private_key()
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )


def public_jwk() -> dict[str, str]:
    """The same key as a JWK (raw 32 bytes, base64url), the form browsers import."""
    raw = (
        _private_key()
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    return {
        "kty": "OKP",
        "crv": "Ed25519",
        "alg": "EdDSA",
        "x": base64.urlsafe_b64encode(raw).rstrip(b"=").decode(),
    }


def new_jti() -> str:
    return secrets.token_urlsafe(12)


def issue(jti: str, expires_at: datetime) -> str:
    return jwt.encode({"jti": jti, "exp": int(expires_at.timestamp())}, _private_key(), ALG)


def read(token: str) -> dict[str, Any]:
    """Verify the signature. An expired pass still decodes (``expired`` flag) so the
    pass page can say "expired" instead of "invalid"."""
    pub = _private_key().public_key()
    try:
        claims = jwt.decode(token, pub, algorithms=[ALG], options={"require": ["jti", "exp"]})
        claims["expired"] = False
    except jwt.ExpiredSignatureError:
        claims = jwt.decode(token, pub, algorithms=[ALG], options={"verify_exp": False})
        claims["expired"] = True
    except jwt.PyJWTError as exc:
        raise AppError(404, "invalid_pass", "This pass is not valid") from exc
    return claims


def qr_svg(token: str) -> str:
    """The QR holds only the token (not the page URL): fewer modules, so it scans
    quickly off a phone screen. Screens don't get dirty, so low error correction is fine."""
    # omitsize: a viewBox instead of a fixed width/height, so it scales to its box
    # (a fixed 294px image was cut off on narrow phones).
    return segno.make(token, error="l", micro=False).svg_inline(scale=6, border=2, omitsize=True)


def pass_url(token: str) -> str:
    return f"{get_settings().public_web_url.rstrip('/')}/p/{token}"
