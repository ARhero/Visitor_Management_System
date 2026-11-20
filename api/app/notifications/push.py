"""Web push: alerts on staff phones and computers without WhatsApp.

A host opens the host app once and allows notifications; the browser gives us an
endpoint, which is stored in ``push_subscriptions``. When a message for that person is
delivered (see ``dispatcher.deliver``), a push goes to each of their browsers as well,
whether or not WhatsApp is on. The service worker (``web/public/sw.js``) shows it, with
Approve / Decline buttons for visit requests.

Push needs no account with anyone: browsers' push services accept any sender that signs
its requests with a VAPID key pair, which this module creates (dev) or reads from
``VAPID_PRIVATE_KEY`` (production).
"""

import asyncio
import base64
import json
import logging
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import PushSubscription
from app.notifications.templates import pick

log = logging.getLogger(__name__)

# What each message looks like as a notification. Only these are pushed.
PUSH: dict[str, dict[str, dict[str, str]]] = {
    "visit_request": {
        "title": {"en": "Visitor for you: {visitor}", "hi": "आपसे मिलने आए हैं: {visitor}"},
        "body": {"en": "{purpose_line}At {site} {gate}", "hi": "{purpose_line}{site} {gate} पर"},
    },
    "visit_escalated": {
        "title": {
            "en": "Can you take {visitor}?",
            "hi": "क्या आप {visitor} से मिल सकते हैं?",
        },
        "body": {
            "en": "{host} has not responded. {purpose_line}At {site} {gate}",
            "hi": "{host} ने जवाब नहीं दिया। {purpose_line}{site} {gate} पर",
        },
    },
    "visit_reminder": {
        "title": {"en": "Still waiting: {visitor}", "hi": "अभी भी इंतज़ार: {visitor}"},
        "body": {"en": "At the gate at {site}", "hi": "{site} के गेट पर"},
    },
    "visitor_arrived": {
        "title": {"en": "{visitor} has checked in", "hi": "{visitor} अंदर आ गए हैं"},
        "body": {"en": "At {site}{gate}.{note}", "hi": "{site}{gate} पर।{note}"},
    },
}
ACTIONS = {
    "approve": {"en": "Approve", "hi": "स्वीकृत करें"},
    "reject": {"en": "Decline", "hi": "मना करें"},
}
# Shown by the service worker after a button on the notification was used.
DONE = {
    "approve": {"en": "Approved: {visitor}", "hi": "स्वीकृत: {visitor}"},
    "reject": {"en": "Declined: {visitor}", "hi": "अस्वीकृत: {visitor}"},
    "failed": {"en": "Couldn't answer. Open the app.", "hi": "जवाब नहीं जा सका। ऐप खोलें।"},
}
TTL_SECONDS = 15 * 60  # a visitor at the gate: an alert older than this is useless


@lru_cache
def _vapid() -> Vapid:
    s = get_settings()
    pem = s.vapid_private_key.replace("\\n", "\n").strip()
    if pem:
        return Vapid.from_pem(pem.encode())
    if s.env == "prod":
        raise RuntimeError("VAPID_PRIVATE_KEY must be set in production (web push)")
    if s.env == "test":
        v = Vapid()
        v.generate_keys()
        return v
    path = Path(s.vapid_key_file)
    if not path.exists():
        v = Vapid()
        v.generate_keys()
        v.save_key(str(path))
    return Vapid.from_file(str(path))


def public_key() -> str:
    """The application server key browsers need to subscribe (base64url, no padding)."""
    raw = _vapid().public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class Gone(Exception):
    """The browser unsubscribed or the subscription expired: forget it."""


def _send_sync(sub: dict[str, Any], data: str) -> None:
    try:
        webpush(
            subscription_info=sub,
            data=data,
            vapid_private_key=_vapid(),
            vapid_claims={"sub": get_settings().vapid_subject},
            ttl=TTL_SECONDS,
            headers={"Urgency": "high"},
            timeout=10,
        )
    except WebPushException as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (404, 410):
            raise Gone() from exc
        raise


async def send_raw(sub: dict[str, Any], data: str) -> None:
    """One push. Replaced in tests. Raises ``Gone`` for dead subscriptions."""
    await asyncio.to_thread(_send_sync, sub, data)


def payload(template: str, locale: str, params: dict[str, str], respond_link: str | None) -> dict:
    spec = PUSH[template]
    p = dict(params)
    p["purpose_line"] = f"{p['purpose']}. " if p.get("purpose") else ""
    if p.get("gate"):
        p["gate"] = f"({p['gate']})" if template != "visitor_arrived" else f", {p['gate']}"
    fmt = _Default(p)
    out: dict[str, Any] = {
        "title": pick(spec["title"], locale).format_map(fmt),
        "body": " ".join(pick(spec["body"], locale).format_map(fmt).split()),
        "url": respond_link or "/host",
        "tag": template,
    }
    if respond_link and template in ("visit_request", "visit_escalated", "visit_reminder"):
        out["respond_token"] = respond_link.rstrip("/").rsplit("/", 1)[-1]
        out["actions"] = [{"action": a, "title": pick(t, locale)} for a, t in ACTIONS.items()]
        out["done"] = {k: pick(v, locale).format_map(fmt) for k, v in DONE.items()}
        out["tag"] = f"visit-{out['respond_token'][-12:]}"
    return out


async def to_user(db: AsyncSession, user_id: UUID, data: dict[str, Any]) -> int:
    """Push to every browser the user subscribed. Returns how many accepted it.
    ``db`` must be a system session (the caller commits)."""
    subs = (
        (await db.execute(select(PushSubscription).where(PushSubscription.user_id == user_id)))
        .scalars()
        .all()
    )
    body = json.dumps(data, ensure_ascii=False)
    ok = 0
    for s in subs:
        try:
            await send_raw(
                {"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}}, body
            )
            s.last_sent_at = datetime.now(UTC)
            ok += 1
        except Gone:
            await db.execute(delete(PushSubscription).where(PushSubscription.id == s.id))
        except Exception as exc:  # noqa: BLE001
            log.warning("web push failed for %s: %s", s.id, exc)
    return ok


class _Default(dict):
    def __missing__(self, key: str) -> str:
        return ""
