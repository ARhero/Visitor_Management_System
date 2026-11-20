"""Pre-approved invites (VIP passes): creating them, sending passes, and letting a
guest in at the gate.

A guest's pass is an Ed25519 token over the guest's own ``pass_jti``. When it is
scanned (or the guard picks the guest from "expected today"), an ``approved`` visit
is created for today, which the guard then checks in like any other visit. Single
and group invites allow one entry per guest; multi-day invites one entry per day.
"""

from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import (
    Invite,
    InviteGuest,
    Organization,
    Site,
    User,
    Visit,
    VisitEvent,
    Visitor,
)
from app.notifications import contacts, dispatcher
from app.notifications.templates import render
from app.services import blacklist, passes
from app.services.visit_state import transition
from app.services.visits import IST, AfterCommit, day_end, now

EARLY = timedelta(minutes=30)  # guests may arrive a little before their slot
MAX_GUESTS = 200


def today_start(at: datetime) -> datetime:
    return datetime.combine(at.astimezone(IST).date(), time(0), IST).astimezone(UTC)


def pass_token(invite: Invite, guest: InviteGuest) -> str:
    return passes.issue(guest.pass_jti, invite.valid_until)


def when_text(invite: Invite, locale: str) -> str:
    a = invite.valid_from.astimezone(IST)
    b = invite.valid_until.astimezone(IST)
    fmt = "%d %b"
    if invite.kind == "multi_day":
        span = f"{a:{fmt}} – {b:{fmt}}"
        if invite.daily_start_time and invite.daily_end_time:
            span += f", {invite.daily_start_time:%H:%M}–{invite.daily_end_time:%H:%M}"
    else:
        span = f"{a:{fmt}}, {a:%H:%M}–{b:%H:%M}"
    return f" ({span})" if locale == "hi" else f" on {span}"


async def upsert_visitor(
    db: AsyncSession, org_id: UUID, name: str, phone: str, company: str | None
) -> Visitor:
    v = (await db.execute(select(Visitor).where(Visitor.phone == phone))).scalar_one_or_none()
    if v is None:
        v = Visitor(
            org_id=org_id,
            phone=phone,
            full_name=name,
            company=company,
            first_seen_at=now(),
            visit_count=0,
        )
        db.add(v)
        await db.flush()
    elif not v.full_name:
        v.full_name = name
    return v


async def add_guests(
    db: AsyncSession, invite: Invite, guests: list[dict[str, Any]]
) -> list[InviteGuest]:
    existing = {
        g.phone
        for g in (
            await db.execute(select(InviteGuest).where(InviteGuest.invite_id == invite.id))
        ).scalars()
    }
    if invite.kind == "single" and len(existing) + len(guests) > 1:
        raise AppError(422, "single_guest", "A single invite has exactly one guest")
    if len(existing) + len(guests) > MAX_GUESTS:
        raise AppError(422, "too_many_guests", f"An invite can have at most {MAX_GUESTS} guests")
    out = []
    for g in guests:
        if g["phone"] in existing:
            continue  # same person twice: keep the first
        existing.add(g["phone"])
        visitor = await upsert_visitor(db, invite.org_id, g["name"], g["phone"], g.get("company"))
        row = InviteGuest(
            org_id=invite.org_id,
            invite_id=invite.id,
            visitor_id=visitor.id,
            name=g["name"],
            phone=g["phone"],
            company=g.get("company"),
            pass_jti=passes.new_jti(),
            max_uses=None if invite.kind == "multi_day" else 1,
            status="active",
        )
        db.add(row)
        out.append(row)
    await db.flush()
    return out


def invite_params(
    org_name: str, host_name: str, site_name: str, invite: Invite, guest: InviteGuest, locale: str
) -> dict[str, str]:
    return {
        "host": host_name,
        "org": org_name,
        "site": site_name,
        "when": when_text(invite, locale),
        "title": f" {invite.title}." if invite.title else "",
        "pass_url": passes.pass_url(pass_token(invite, guest)),
    }


def share_text(
    org_name: str, host_name: str, site_name: str, invite: Invite, guest: InviteGuest, locale: str
) -> str:
    """The invitation as text, for the host to send from their own WhatsApp."""
    return render(
        "invite", locale, invite_params(org_name, host_name, site_name, invite, guest, locale)
    )


async def send_pass(
    db: AsyncSession, org: Organization, invite: Invite, guest: InviteGuest, after: AfterCommit
) -> None:
    """Send the pass on WhatsApp. With WhatsApp off nothing is sent (``sent_at`` stays
    empty) and the host shares it themselves (``share_text``)."""
    if not get_settings().whatsapp_enabled:
        return
    site = await db.get(Site, invite.site_id)
    host = await db.get(User, invite.host_id)
    assert site and host
    visitor = await db.get(Visitor, guest.visitor_id) if guest.visitor_id else None
    locale = visitor.preferred_locale if visitor else org.default_locale
    after.notes.append(
        dispatcher.queue(
            db,
            org_id=org.id,
            to=guest.phone,
            template="invite",
            locale=locale,
            params=invite_params(org.name, host.full_name, site.name, invite, guest, locale),
        )
    )
    guest.sent_at = now()
    await contacts.opt_in(guest.phone, "invited_by_host")


async def tell_cancelled(
    db: AsyncSession, invite: Invite, guest: InviteGuest, after: AfterCommit
) -> None:
    if not guest.sent_at:
        return
    site = await db.get(Site, invite.site_id)
    host = await db.get(User, invite.host_id)
    assert site and host
    after.notes.append(
        dispatcher.queue(
            db,
            org_id=invite.org_id,
            to=guest.phone,
            template="invite_cancelled",
            locale="en",
            params={"host": host.full_name, "site": site.name},
        )
    )


async def cancel_open_visits(
    db: AsyncSession, guest_ids: list[UUID], actor_id: UUID, after: AfterCommit
) -> None:
    """A revoked pass must not still work through a visit created by an earlier scan."""
    if not guest_ids:
        return
    open_ids = (
        await db.execute(
            select(Visit.id).where(Visit.invite_guest_id.in_(guest_ids), Visit.status == "approved")
        )
    ).scalars()
    for vid in list(open_ids):
        v = await transition(
            db,
            vid,
            "cancelled",
            actor_type="host",
            actor_id=actor_id,
            channel="web",
            meta={"reason": "invite_revoked"},
        )
        after.visits.append(v)


# ---------- At the gate ----------


def problem(invite: Invite, guest: InviteGuest, site_id: UUID, at: datetime) -> str | None:
    """Why this guest can't come in right now, or None."""
    if guest.status == "revoked" or invite.status == "revoked":
        return "revoked"
    if invite.site_id != site_id:
        return "wrong_site"
    if invite.status == "expired" or at > invite.valid_until:
        return "expired"
    if at < invite.valid_from - EARLY:
        return "not_yet"
    if invite.kind == "multi_day" and invite.daily_start_time and invite.daily_end_time:
        local = at.astimezone(IST)
        start = datetime.combine(local.date(), invite.daily_start_time, IST) - EARLY
        end = datetime.combine(local.date(), invite.daily_end_time, IST)
        if not (start <= local <= end):
            return "outside_hours"
    if guest.max_uses is not None and guest.use_count >= guest.max_uses:
        return "used"
    return None


async def todays_visit(db: AsyncSession, guest: InviteGuest, at: datetime) -> Visit | None:
    return (
        await db.execute(
            select(Visit)
            .where(
                Visit.invite_guest_id == guest.id,
                Visit.requested_at >= today_start(at),
                Visit.status.in_(("approved", "checked_in", "checked_out")),
            )
            .order_by(Visit.requested_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def arrive(
    db: AsyncSession,
    org: Organization,
    invite: Invite,
    guest: InviteGuest,
    site_id: UUID,
    guard_id: UUID,
    at: datetime | None = None,
) -> tuple[str | None, Visit | None, AfterCommit]:
    """The guest is at the gate. Returns (problem, visit, after). With no problem the
    visit is ``approved`` (new, or today's existing one) or already ``checked_in``.
    ``at``: when the guard scanned, for a check-in replayed after being offline."""
    t = now()
    at = at or t
    after = AfterCommit()
    existing = await todays_visit(db, guest, at)
    if existing and existing.status in ("approved", "checked_in"):
        return None, existing, after
    if existing and existing.status == "checked_out":
        return ("left" if invite.kind == "multi_day" else "used"), existing, after
    p = problem(invite, guest, site_id, at)
    if p:
        return p, None, after

    hit = await blacklist.match(db, guest.phone, site_id)
    visitor = await upsert_visitor(db, org.id, guest.name, guest.phone, guest.company)
    visitor.visit_count += 1
    visitor.last_visit_at = t
    status = "rejected" if hit and hit.action == "block" else "approved"
    v = Visit(
        org_id=org.id,
        site_id=site_id,
        host_id=invite.host_id,
        visitor_id=visitor.id,
        invite_guest_id=guest.id,
        source="invite",
        status=status,
        locale=visitor.preferred_locale,
        visitor_name=guest.name,
        visitor_company=guest.company,
        visitor_phone=guest.phone,
        purpose_id=invite.purpose_id,
        purpose_note=invite.title,
        photo_key=visitor.last_photo_key,
        requested_at=t,
        approved_at=t if status == "approved" else None,
        valid_until=day_end(org.settings or {}, t),
        blacklist_hit_id=hit.id if hit else None,
        notified_approver_ids=[],
    )
    db.add(v)
    await db.flush()
    db.add(
        VisitEvent(
            org_id=org.id,
            visit_id=v.id,
            from_status=None,
            to_status=status,
            actor_type="guard" if status == "approved" else "system",
            actor_id=guard_id if status == "approved" else None,
            channel="web",
            meta={"invite_id": str(invite.id)}
            | ({"reason": "blacklist", "entry": str(hit.id)} if status == "rejected" else {}),
        )
    )
    after.visits.append(v)
    if status == "rejected":
        return "blocked", v, after
    return None, v, after


async def lock_guest(db: AsyncSession, guest_id: UUID) -> tuple[InviteGuest, Invite]:
    guest = (
        await db.execute(
            select(InviteGuest)
            .where(InviteGuest.id == guest_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    invite = await db.get(Invite, guest.invite_id)
    assert invite is not None
    return guest, invite


async def expire_due() -> int:
    from sqlalchemy import update

    from app.core.db import system_session

    async with system_session() as db:
        r = await db.execute(
            update(Invite)
            .where(Invite.status == "active", Invite.valid_until <= now())
            .values(status="expired")
        )
        await db.commit()
        return r.rowcount or 0
