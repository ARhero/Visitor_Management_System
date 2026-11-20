"""WhatsApp opt-in / opt-out and the 24-hour customer-service window.

- Opt-in is recorded when a person gives us their number for this purpose: a visitor
  asking for an OTP, a host asking for a sign-in link, an admin adding staff, a host
  inviting a guest. Only the person's own actions (OTP, sign-in link, START) undo an
  earlier STOP; an admin adding them again does not.
- STOP (and a few synonyms, in English and Hindi) opts out. Every later message to that
  phone is recorded as ``skipped`` instead of being sent.
- ``last_inbound_at`` is when the person last messaged us (any button tap or text).
  Free-form text may only be sent within 24 hours of it.
"""

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import system_session
from app.models import WhatsAppContact

WINDOW = timedelta(hours=24)
STOP_WORDS = {"stop", "unsubscribe", "stop all", "रोकें", "बंद", "बंद करें"}
START_WORDS = {"start", "subscribe", "शुरू", "शुरू करें"}
# Sources that come from the person themself (and so cancel an earlier STOP).
EXPLICIT = {"visitor_otp", "login_link", "start_keyword", "privacy_otp", "setup_test"}


def _now() -> datetime:
    return datetime.now(UTC)


async def opt_in(phone: str | None, source: str) -> None:
    """Best effort: never fails the caller."""
    if not phone:
        return
    t = _now()
    values = {"phone": phone, "opted_in_at": t, "opt_in_source": source}
    update = {"opted_in_at": t, "opt_in_source": source, "updated_at": t}
    if source in EXPLICIT:
        update["opted_out_at"] = None
    async with system_session() as db:
        stmt = insert(WhatsAppContact).values(**values)
        if source in EXPLICIT:
            stmt = stmt.on_conflict_do_update(index_elements=["phone"], set_=update)
        else:  # keep an existing opt-in and any STOP as they are
            stmt = stmt.on_conflict_do_nothing(index_elements=["phone"])
        await db.execute(stmt)
        await db.commit()


async def opt_in_many(phones: Iterable[str | None], source: str) -> None:
    for p in {p for p in phones if p}:
        await opt_in(p, source)


async def inbound(phone: str, text: str | None = None) -> str | None:
    """Record a message from ``phone``. Returns "stop"/"start" if it was a keyword."""
    t = _now()
    word = (text or "").strip().lower().strip(".!")
    kind = "stop" if word in STOP_WORDS else "start" if word in START_WORDS else None
    values: dict[str, object] = {"phone": phone, "last_inbound_at": t}
    update: dict[str, object] = {"last_inbound_at": t, "updated_at": t}
    if kind == "stop":
        values["opted_out_at"] = update["opted_out_at"] = t
    elif kind == "start":
        values |= {"opted_in_at": t, "opt_in_source": "start_keyword"}
        update |= {"opted_in_at": t, "opt_in_source": "start_keyword", "opted_out_at": None}
    async with system_session() as db:
        await db.execute(
            insert(WhatsAppContact)
            .values(**values)
            .on_conflict_do_update(index_elements=["phone"], set_=update)
        )
        await db.commit()
    return kind


async def lookup(db: AsyncSession, phones: Iterable[str]) -> dict[str, WhatsAppContact]:
    phones = list(set(phones))
    if not phones:
        return {}
    rows = (
        (await db.execute(select(WhatsAppContact).where(WhatsAppContact.phone.in_(phones))))
        .scalars()
        .all()
    )
    return {c.phone: c for c in rows}


def window_open(c: WhatsAppContact | None, at: datetime | None = None) -> bool:
    return bool(c and c.last_inbound_at and (at or _now()) - c.last_inbound_at < WINDOW)
