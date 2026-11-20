"""NotificationProvider implementations.

``mock`` (default): sends nothing. The notification_logs row *is* the message, and
the /dev/whatsapp inbox reads it from there and can simulate replies.
``meta``: the WhatsApp Business Cloud API, through the platform's shared number.
Templates are defined in ``app/notifications/meta.py``.
``off``: no WhatsApp at all. The dispatcher marks such messages ``skipped`` (or ``sent``
when they reached the recipient another way, e.g. web push) and never calls ``send``.
"""

import hashlib
import hmac
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol
from uuid import uuid4

import httpx

from app.core.config import get_settings
from app.notifications import meta

log = logging.getLogger(__name__)


@dataclass
class Outbound:
    to: str  # E.164
    template: str
    locale: str
    params: dict[str, str]
    text: str
    buttons: list[dict[str, str]] = field(default_factory=list)  # [{id, title}]


class SendError(Exception):
    """A send that failed. ``retry`` False means trying again can't help (bad number,
    template not approved, recipient blocked us...), so it is marked failed at once."""

    def __init__(self, message: str, *, retry: bool, code: int | None = None) -> None:
        super().__init__(message)
        self.retry = retry
        self.code = code


class NotificationProvider(Protocol):
    name: str

    async def send(self, msg: Outbound) -> str:
        """Send and return the provider's message id. Raise on failure (it is retried
        unless the error is a SendError with retry=False)."""
        ...


class MockWhatsAppProvider:
    name = "mock"

    async def send(self, msg: Outbound) -> str:  # noqa: ARG002
        return f"mock-{uuid4().hex}"


class OffProvider:
    name = "off"

    async def send(self, msg: Outbound) -> str:  # noqa: ARG002
        raise SendError("WhatsApp is turned off", retry=False)


# Meta error codes worth retrying: rate limits, throttling, temporary outages.
# https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes
RETRYABLE_CODES = {1, 2, 4, 17, 341, 80007, 130429, 131000, 131016, 131048, 131056, 133004}


class MetaCloudProvider:
    name = "meta"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        s = get_settings()
        if not s.whatsapp_phone_number_id or not s.whatsapp_access_token:
            raise RuntimeError(
                "WHATSAPP_PROVIDER=meta needs WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN"
            )
        self._url = f"{s.whatsapp_graph_url.rstrip('/')}/{s.whatsapp_phone_number_id}/messages"
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=s.whatsapp_timeout_seconds,
            headers={"Authorization": f"Bearer {s.whatsapp_access_token}"},
        )

    async def send(self, msg: Outbound) -> str:
        try:
            body = meta.message_payload(
                msg.to, msg.template, msg.locale, msg.params, msg.text, msg.buttons
            )
        except (KeyError, ValueError) as exc:
            raise SendError(f"cannot build message: {exc}", retry=False) from exc
        try:
            r = await self._client.post(self._url, json=body)
        except httpx.HTTPError as exc:  # network, timeout: try again later
            raise SendError(f"{type(exc).__name__}: {exc}", retry=True) from exc
        data: dict[str, Any] = {}
        try:
            data = r.json()
        except ValueError:
            pass
        if r.status_code >= 400 or "error" in data:
            err = data.get("error") or {}
            code = err.get("code")
            detail = (err.get("error_data") or {}).get("details") or err.get("message") or r.text
            retry = r.status_code >= 500 or r.status_code == 429 or code in RETRYABLE_CODES
            raise SendError(f"meta {r.status_code} #{code}: {detail}"[:900], retry=retry, code=code)
        try:
            return str(data["messages"][0]["id"])
        except (KeyError, IndexError, TypeError) as exc:
            raise SendError(f"unexpected response: {r.text[:200]}", retry=True) from exc


def verify_meta_signature(body: bytes, header: str | None) -> bool:
    """X-Hub-Signature-256: sha256=<hex hmac of the raw body with the app secret>."""
    secret = get_settings().whatsapp_app_secret
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@lru_cache
def get_provider() -> NotificationProvider:
    kind = get_settings().whatsapp_provider
    if kind == "meta":
        return MetaCloudProvider()
    if kind == "off":
        return OffProvider()
    return MockWhatsAppProvider()
