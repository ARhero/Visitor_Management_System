"""Inbound WhatsApp processing (Meta webhook format).

Both the real webhook and the dev inbox's simulated button taps call
``process_payload``, so the dev loop exercises the production code path.

Idempotency: every inbound message / status has a provider id; it is inserted into
``webhook_events`` first, and a duplicate delivery is skipped. On top of that, visit
transitions lock the row and check the current status, so even two *different*
taps (Approve and Reject) cannot both apply.
"""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.db import system_session, tenant_session
from app.core.errors import AppError
from app.core.phone import normalize_phone
from app.models import NotificationLog, Organization, User, Visit, WebhookEvent
from app.notifications import contacts
from app.notifications.providers import Outbound, get_provider
from app.notifications.templates import render
from app.services import visits as visit_svc
from app.services.visit_state import InvalidTransition

log = logging.getLogger(__name__)
PROVIDER = "whatsapp"
STATUS_MAP = {"sent": "sent", "delivered": "delivered", "read": "read", "failed": "failed"}


async def _claim(external_id: str, payload: dict[str, Any]) -> UUID | None:
    """Record the event; None if we've seen this id before."""
    async with system_session() as db:
        res = await db.execute(
            insert(WebhookEvent)
            .values(provider=PROVIDER, external_id=external_id, payload=payload)
            .on_conflict_do_nothing(index_elements=["provider", "external_id"])
            .returning(WebhookEvent.id)
        )
        event_id = res.scalar_one_or_none()
        await db.commit()
    return event_id


async def _finish(event_id: UUID, status: str, result: str) -> None:
    async with system_session() as db:
        ev = await db.get(WebhookEvent, event_id)
        if ev:
            ev.status, ev.result, ev.processed_at = status, result[:200], datetime.now(UTC)
            await db.commit()


def _button_id(msg: dict[str, Any]) -> str | None:
    if msg.get("type") == "button":
        return (msg.get("button") or {}).get("payload")
    if msg.get("type") == "interactive":
        return ((msg.get("interactive") or {}).get("button_reply") or {}).get("id")
    return None


async def process_payload(payload: dict[str, Any]) -> list[str]:
    """Returns one short result string per message/status, for logs and tests."""
    results: list[str] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for st in value.get("statuses", []):
                results.append(await _status(st))
            for msg in value.get("messages", []):
                results.append(await _message(msg))
    return results


async def _status(st: dict[str, Any]) -> str:
    ext = f"status:{st.get('id')}:{st.get('status')}"
    if await _claim(ext, st) is None:
        return "duplicate"
    async with system_session() as db:
        row = (
            await db.execute(
                select(NotificationLog).where(NotificationLog.provider_message_id == st.get("id"))
            )
        ).scalar_one_or_none()
        new = STATUS_MAP.get(st.get("status", ""))
        if row and new:
            row.status = new
            if new == "failed":
                row.error = str(st.get("errors"))[:1000]
            await db.commit()
            return f"status:{new}"
    return "status:unknown"


async def _message(msg: dict[str, Any]) -> str:
    event_id = await _claim(f"msg:{msg.get('id')}", msg)
    if event_id is None:
        return "duplicate"
    try:
        result = await _keyword(msg) or await _handle_button(msg)
        await _finish(event_id, "processed", result)
        return result
    except Exception as exc:
        await _finish(event_id, "error", f"{type(exc).__name__}: {exc}")
        log.exception("webhook message failed")
        return "error"


async def _keyword(msg: dict[str, Any]) -> str | None:
    """Every inbound message opens the 24-hour window; STOP / START change the opt-in."""
    try:
        phone = normalize_phone("+" + str(msg.get("from", "")).lstrip("+"))
    except ValueError:
        return "ignored:bad_sender"
    text = (msg.get("text") or {}).get("body") if msg.get("type") == "text" else None
    kind = await contacts.inbound(phone, text)
    if kind is None:
        return None
    try:  # a confirmation; there is no org (shared number), so it bypasses the outbox
        locale = "hi" if any("ऀ" <= ch <= "ॿ" for ch in text or "") else "en"
        key = f"opt{'out' if kind == 'stop' else 'in'}_ack"
        await get_provider().send(
            Outbound(to=phone, template=key, locale=locale, params={}, text=render(key, locale, {}))
        )
    except Exception:  # noqa: BLE001
        log.warning("could not confirm %s to %s", kind, phone[-4:])
    return f"keyword:{kind}"


async def _handle_button(msg: dict[str, Any]) -> str:
    button = _button_id(msg)
    if not button or not button.startswith("v1|"):
        return "ignored:not_a_button"
    try:
        _, ref, action = button.split("|")
        visit_id = UUID(ref)
        phone = normalize_phone("+" + str(msg.get("from", "")).lstrip("+"))
    except ValueError:
        return "ignored:bad_payload"
    if action not in visit_svc.ACTION_TO_STATUS:
        return "ignored:bad_action"

    # Find the org from the visit (owner role), then do everything else in that org's
    # tenant session, as the person whose phone sent the tap.
    async with system_session() as db:
        org_id = (await db.execute(select(Visit.org_id).where(Visit.id == visit_id))).scalar()
    if org_id is None:
        return "ignored:unknown_visit"

    async with tenant_session(org_id) as db:
        org = await db.get(Organization, org_id)
        user = (
            await db.execute(select(User).where(User.phone == phone, User.is_active.is_(True)))
        ).scalar_one_or_none()
        db.add(
            NotificationLog(
                org_id=org_id,
                visit_id=visit_id,
                recipient_phone=phone,
                recipient_user_id=user.id if user else None,
                direction="in",
                template_key="button_reply",
                provider=PROVIDER,
                provider_message_id=str(msg.get("id")),
                status="received",
                payload={"button": button, "text": (msg.get("button") or {}).get("text", action)},
            )
        )
        await db.commit()  # keep the inbound record whatever happens next
        if user is None or org is None:
            return "ignored:unknown_sender"
        try:
            v, after = await visit_svc.respond(db, org, visit_id, user, action, None, "whatsapp")
        except InvalidTransition as exc:
            # Raised after the status check, before any write: nothing to undo.
            v = await db.get(Visit, visit_id)
            assert v is not None
            note = visit_svc.too_late_note(db, org, v, user, exc.current)
            await db.commit()
            await visit_svc.AfterCommit(notes=[note]).run()
            return f"too_late:{exc.current}"
        except AppError as exc:  # not this person's visit
            await db.rollback()
            return f"ignored:{exc.code}"
        await db.commit()
    await after.run()
    return f"{action}:{v.status}"
