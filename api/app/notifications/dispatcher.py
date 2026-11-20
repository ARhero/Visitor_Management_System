"""Outbox for WhatsApp/SMS messages.

1. ``queue()`` adds a ``notification_logs`` row in the caller's transaction, so a message
   exists if and only if the change that caused it was committed.
2. After commit the caller calls ``dispatch(ids)``: delivery happens right away in
   process (no worker) or through the ARQ worker.
3. ``deliver_due()`` runs from the sweeper and retries anything still queued: failed sends
   with backoff, or rows whose immediate delivery never happened (e.g. a crash).

Rows are claimed with ``FOR UPDATE SKIP LOCKED``, so the immediate path and the sweeper
never send the same message twice.

Before sending, WhatsApp's rules are applied (whatever the provider, so dev behaves like
production): nothing goes to a phone that sent STOP, and free-form text (replies to a
host's tap) only goes out inside the 24-hour window. Those rows end as ``skipped``.

Messages for staff (visit requests, reminders, arrivals) also go out as web push to
every browser they enabled alerts on, once, whatever happens on WhatsApp. With
WHATSAPP_PROVIDER=off that is the only way they arrive: such a row ends ``sent`` if a
push got through and ``skipped`` if not.
"""

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import system_session
from app.models import NotificationLog
from app.notifications import contacts, push
from app.notifications.meta import SESSION_ONLY
from app.notifications.providers import Outbound, SendError, get_provider
from app.notifications.templates import BUTTONS, pick, render

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
GRACE = timedelta(seconds=20)  # the sweeper leaves fresh rows to the immediate path


def queue(
    db: AsyncSession,
    *,
    org_id: UUID,
    to: str,
    template: str,
    locale: str,
    params: dict[str, Any],
    visit_id: UUID | None = None,
    user_id: UUID | None = None,
    actions: Iterable[str] = (),
    button_ref: str | None = None,
) -> NotificationLog:
    """``actions`` become quick-reply buttons whose id is ``v1|<button_ref>|<action>``."""
    params = {k: "" if v is None else str(v) for k, v in params.items()}
    buttons = [{"id": f"v1|{button_ref}|{a}", "title": pick(BUTTONS[a], locale)} for a in actions]
    row = NotificationLog(
        org_id=org_id,
        visit_id=visit_id,
        recipient_phone=to,
        recipient_user_id=user_id,
        template_key=template,
        locale=locale,
        provider=get_provider().name,
        status="queued",
        payload={"params": params, "buttons": buttons, "text": render(template, locale, params)},
        next_attempt_at=datetime.now(UTC) + GRACE,
    )
    db.add(row)
    return row


async def dispatch(ids: list[UUID]) -> None:
    """Call after commit. Failures are left for the sweeper; this never raises."""
    if not ids:
        return
    try:
        if get_settings().run_jobs_in_process:
            await deliver(ids)
        else:
            from app.workers.queue import enqueue

            await enqueue("deliver_notifications", [str(i) for i in ids])
    except Exception:  # noqa: BLE001
        log.exception("notification dispatch failed; the sweeper will retry")


async def deliver(ids: list[UUID] | None = None, limit: int = 100) -> int:
    """Send queued messages (the given ids, or everything due). Returns how many sent."""
    sent = 0
    provider = get_provider()
    async with system_session() as db:
        q = select(NotificationLog).where(NotificationLog.status == "queued")
        if ids is not None:
            q = q.where(NotificationLog.id.in_(ids))
        else:
            q = q.where(NotificationLog.next_attempt_at <= datetime.now(UTC))
        q = q.order_by(NotificationLog.created_at).limit(limit).with_for_update(skip_locked=True)
        rows = (await db.execute(q)).scalars().all()
        known = await contacts.lookup(db, [r.recipient_phone for r in rows])
        for row in rows:
            pushed = await _push(db, row)
            c = known.get(row.recipient_phone)
            if skip := _skip_reason(row, c):
                if pushed:
                    row.status, row.sent_at, row.error = "sent", datetime.now(UTC), None
                    sent += 1
                else:
                    row.status, row.error = "skipped", skip
                continue
            row.attempts += 1
            p = row.payload or {}
            try:
                row.provider_message_id = await provider.send(
                    Outbound(
                        to=row.recipient_phone,
                        template=row.template_key,
                        locale=row.locale,
                        params=p.get("params", {}),
                        text=p.get("text", ""),
                        buttons=p.get("buttons", []),
                    )
                )
                row.status, row.sent_at, row.error = "sent", datetime.now(UTC), None
                if row.template_key == "otp" and get_settings().env == "prod":
                    # Codes are kept only until sent (the dev inbox needs them, prod doesn't).
                    row.payload = {**p, "params": {}, "text": "[verification code]"}
                sent += 1
            except Exception as exc:  # noqa: BLE001
                row.error = f"{type(exc).__name__}: {exc}"[:1000]
                if row.attempts >= MAX_ATTEMPTS or (isinstance(exc, SendError) and not exc.retry):
                    row.status = "failed"
                else:
                    row.next_attempt_at = datetime.now(UTC) + timedelta(
                        seconds=30 * 2 ** (row.attempts - 1)
                    )
                log.warning("send failed (%s attempt %s): %s", row.id, row.attempts, row.error)
        await db.commit()
    return sent


async def _push(db: AsyncSession, row: NotificationLog) -> int:
    """Web push for staff messages, at most once per row. Returns browsers reached."""
    p = row.payload or {}
    if row.recipient_user_id is None or row.template_key not in push.PUSH:
        return 0
    if "pushed" in p:
        return int(p["pushed"])
    params = p.get("params", {})
    n = await push.to_user(
        db,
        row.recipient_user_id,
        push.payload(row.template_key, row.locale, params, params.get("link") or None),
    )
    row.payload = {**p, "pushed": n}
    return n


def _skip_reason(row: NotificationLog, c: contacts.WhatsAppContact | None) -> str | None:
    if not get_settings().whatsapp_enabled:
        return "WhatsApp is off"
    if not row.recipient_phone:
        return "no phone number"
    if c is not None and c.opted_out_at is not None:
        return "recipient opted out (STOP)"
    if row.template_key in SESSION_ONLY and not contacts.window_open(c):
        return "outside the 24-hour window"
    return None


async def deliver_due() -> int:
    return await deliver(None)
