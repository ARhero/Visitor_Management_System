"""The gate: what a guard sees and does.

Guards only see the sites they are assigned to (admins see all). Every status change
still goes through ``visit_state.transition``; this module adds the gate rules:
pass checks, the blacklist, single-use invites and the guard override.
"""

import hashlib
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import system_session
from app.core.deps import Principal
from app.core.errors import AppError, not_found
from app.models import (
    BlacklistEntry,
    Gate,
    GuardSiteAssignment,
    Invite,
    InviteGuest,
    Organization,
    Purpose,
    Site,
    User,
    Visit,
)
from app.notifications import dispatcher
from app.schemas.guard import (
    Alert,
    ExpectedGuest,
    GuardCard,
    GuardQueue,
    OfflineEntry,
    OfflinePack,
    ScanOut,
)
from app.services import blacklist, passes, storage
from app.services import invites as invite_svc
from app.services.visit_state import InvalidTransition, lock, transition
from app.services.visits import AfterCommit, ask_approver, now

MESSAGES = {
    "ok": "Approved. Check the photo, then check them in.",
    "inside": "Already inside. Check them out?",
    "invalid": "Not a valid pass for this organization.",
    "expired": "This pass has expired.",
    "not_yet": "This pass is not valid yet.",
    "outside_hours": "Outside the hours on this pass.",
    "used": "This pass has already been used.",
    "left": "Already visited and left today.",
    "revoked": "This pass was cancelled or the visit was declined.",
    "not_approved": "The host has not approved this visit yet.",
    "wrong_site": "This pass is for a different site.",
    "blocked": "Entry not allowed. Call your supervisor.",
}


def _last4(phone: str | None) -> str | None:
    return phone[-4:] if phone else None


# ---------- Site access ----------


async def site_ids(db: AsyncSession, p: Principal) -> list[UUID] | None:
    """None = every site (admins)."""
    if p.has("org_admin"):
        return None
    return list(
        (
            await db.execute(
                select(GuardSiteAssignment.site_id).where(GuardSiteAssignment.user_id == p.id)
            )
        ).scalars()
    )


async def require_site(db: AsyncSession, p: Principal, site_id: UUID) -> Site:
    site = (await db.execute(select(Site).where(Site.id == site_id))).scalar_one_or_none()
    allowed = await site_ids(db, p)
    if site is None or (allowed is not None and site_id not in allowed):
        raise not_found("Site")
    return site


async def require_visit(db: AsyncSession, p: Principal, visit_id: UUID) -> Visit:
    v = (await db.execute(select(Visit).where(Visit.id == visit_id))).scalar_one_or_none()
    allowed = await site_ids(db, p)
    if v is None or (allowed is not None and v.site_id not in allowed):
        raise not_found("Visit")
    return v


# ---------- Cards ----------


async def cards(db: AsyncSession, visits: list[Visit]) -> list[GuardCard]:
    if not visits:
        return []

    async def by_id(model: Any, ids: set[UUID | None]) -> dict[UUID, Any]:
        ids.discard(None)
        if not ids:
            return {}
        return {
            r.id: r for r in (await db.execute(select(model).where(model.id.in_(ids)))).scalars()
        }

    hosts = await by_id(User, {v.host_id for v in visits})
    purposes = await by_id(Purpose, {v.purpose_id for v in visits})
    gates = await by_id(Gate, {v.gate_id for v in visits})
    hits = await by_id(BlacklistEntry, {v.blacklist_hit_id for v in visits})
    guests = await by_id(InviteGuest, {v.invite_guest_id for v in visits})
    invites = await by_id(Invite, {g.invite_id for g in guests.values()})
    out = []
    for v in visits:
        p = purposes.get(v.purpose_id)
        hit = hits.get(v.blacklist_hit_id)
        g = guests.get(v.invite_guest_id)
        inv = invites.get(g.invite_id) if g else None
        out.append(
            GuardCard(
                id=v.id,
                status=v.status,
                source=v.source,
                visitor_name=v.visitor_name,
                visitor_company=v.visitor_company,
                phone_last4=_last4(v.visitor_phone),
                phone_verified=v.phone_verified,
                photo_url=await storage.signed_url(v.photo_key),
                host_name=hosts[v.host_id].full_name if v.host_id in hosts else "",
                purpose=p.label if p else None,
                purpose_i18n=p.label_i18n if p else {},
                purpose_note=v.purpose_note,
                accompanying_count=v.accompanying_count,
                vehicle_number=v.vehicle_number,
                id_type=v.id_type,
                id_last4=v.id_last4,
                gate_name=gates[v.gate_id].name if v.gate_id in gates else None,
                requested_at=v.requested_at,
                approved_at=v.approved_at,
                checked_in_at=v.checked_in_at,
                checked_out_at=v.checked_out_at,
                checkout_method=v.checkout_method,
                valid_until=v.valid_until,
                host_message=v.host_message,
                guard_note=v.guard_note,
                escalated=v.escalation_level > 0,
                invite_title=inv.title if inv else None,
                invite_notes=inv.notes if inv else None,
                alert=Alert(action=hit.action, reason=hit.reason) if hit else None,  # type: ignore[arg-type]
            )
        )
    return out


async def card(db: AsyncSession, v: Visit) -> GuardCard:
    return (await cards(db, [v]))[0]


async def expected_guest(
    db: AsyncSession, invite: Invite, guest: InviteGuest, host_name: str | None = None
) -> ExpectedGuest:
    if host_name is None:
        host = await db.get(User, invite.host_id)
        host_name = host.full_name if host else ""
    return ExpectedGuest(
        guest_id=guest.id,
        invite_id=invite.id,
        name=guest.name,
        company=guest.company,
        phone_last4=_last4(guest.phone),
        host_name=host_name,
        kind=invite.kind,
        title=invite.title,
        notes=invite.notes,
        valid_from=invite.valid_from,
        valid_until=invite.valid_until,
        daily_start_time=invite.daily_start_time,
        daily_end_time=invite.daily_end_time,
        consented=guest.consented_at is not None,
    )


# ---------- Queue ----------


async def queue(db: AsyncSession, site_id: UUID) -> GuardQueue:
    t = now()
    day = invite_svc.today_start(t)
    rows = list(
        (
            await db.execute(
                select(Visit)
                .where(
                    Visit.site_id == site_id,
                    or_(
                        and_(
                            Visit.status.in_(("pending", "waiting", "approved")),
                            Visit.valid_until > t,
                        ),
                        Visit.status == "checked_in",
                        and_(Visit.status == "checked_out", Visit.checked_out_at >= day),
                        and_(
                            Visit.status == "rejected",
                            Visit.blacklist_hit_id.is_not(None),
                            Visit.requested_at >= day,
                        ),
                    ),
                )
                .order_by(Visit.requested_at)
            )
        ).scalars()
    )
    all_cards = await cards(db, rows)
    by = {c.id: c for c in all_cards}

    def pick(*statuses: str) -> list[GuardCard]:
        return [by[v.id] for v in rows if v.status in statuses]

    left = sorted(pick("checked_out"), key=lambda c: c.checked_out_at or t, reverse=True)[:50]
    on_site = sorted(pick("checked_in"), key=lambda c: c.checked_in_at or t, reverse=True)

    # Invite guests due today who haven't arrived yet.
    arrived = {v.invite_guest_id for v in rows if v.invite_guest_id and v.requested_at >= day}
    day_end = day + timedelta(days=1)
    guest_rows = (
        await db.execute(
            select(InviteGuest, Invite, User.full_name)
            .join(Invite, Invite.id == InviteGuest.invite_id)
            .join(User, User.id == Invite.host_id)
            .where(
                Invite.site_id == site_id,
                Invite.status == "active",
                InviteGuest.status == "active",
                Invite.valid_from < day_end,
                Invite.valid_until > t,
            )
            .order_by(Invite.valid_from, InviteGuest.name)
        )
    ).all()
    invites = [
        await expected_guest(db, inv, g, host)
        for g, inv, host in guest_rows
        if g.id not in arrived and (g.max_uses is None or g.use_count < g.max_uses)
    ]
    return GuardQueue(
        site_id=site_id,
        awaiting=pick("pending", "waiting"),
        expected=pick("approved"),
        on_site=on_site,
        left=left,
        alerts=[by[v.id] for v in rows if v.status == "rejected"],
        invites=invites,
        people_on_site=sum(1 + c.accompanying_count for c in on_site),
    )


# ---------- Scan ----------


def token_from(payload: str) -> str:
    """The QR holds the bare token; a pass link (``…/p/<token>``) works too, e.g. from
    a handheld scanner reading the link, or a guard pasting it."""
    s = payload.strip()
    if "/p/" in s:
        s = urlparse(s).path.rsplit("/p/", 1)[-1] if "://" in s else s.rsplit("/p/", 1)[-1]
    return s.strip("/ ")


async def scan(
    db: AsyncSession,
    org: Organization,
    site: Site,
    payload: str,
    guard_id: UUID,
    at: datetime | None = None,
) -> tuple[ScanOut, AfterCommit]:
    """``at``: when the pass was scanned, if that was earlier (an offline check-in being
    replayed); validity is judged at that moment."""
    after = AfterCommit()
    at = at or now()

    def out(result: str, **kw: Any) -> tuple[ScanOut, AfterCommit]:
        return ScanOut(result=result, message=MESSAGES[result], **kw), after  # type: ignore[arg-type]

    try:
        claims = passes.read(token_from(payload))
    except AppError:
        return out("invalid")
    jti = claims["jti"]
    claims["expired"] = claims["exp"] <= at.timestamp()

    # RLS: a pass from another organization is simply not found here.
    v = (await db.execute(select(Visit).where(Visit.pass_jti == jti))).scalar_one_or_none()
    if v is not None:
        c = await card(db, v)
        if v.site_id != site.id:
            other = await db.get(Site, v.site_id)
            return out("wrong_site", visit=c, site_name=other.name if other else None)
        if v.status == "checked_in":
            return out("inside", visit=c)
        if v.status == "approved":
            if claims["expired"] or v.valid_until <= at:
                return out("expired", visit=c)
            # Checked live: an entry added after the host approved still applies.
            hit = await blacklist.match(db, v.visitor_phone, site.id)
            if hit:
                c.alert = Alert(action=hit.action, reason=hit.reason)  # type: ignore[arg-type]
            if hit and hit.action == "block":
                return out("blocked", visit=c)
            return out("ok", visit=c)
        result = {
            "pending": "not_approved",
            "waiting": "not_approved",
            "checked_out": "used",
            "expired": "expired",
        }.get(v.status, "revoked")
        return out(result, visit=c)

    guest = (
        await db.execute(select(InviteGuest).where(InviteGuest.pass_jti == jti))
    ).scalar_one_or_none()
    if guest is None:
        return out("invalid")
    invite = await db.get(Invite, guest.invite_id)
    assert invite is not None
    g = await expected_guest(db, invite, guest)
    if claims["expired"] and invite.status == "active":
        return out("expired", guest=g)
    problem, visit, after = await invite_svc.arrive(db, org, invite, guest, site.id, guard_id, at)
    c = await card(db, visit) if visit else None
    if problem == "wrong_site":
        other = await db.get(Site, invite.site_id)
        return out("wrong_site", guest=g, site_name=other.name if other else None)
    if problem:
        return out(problem, visit=c, guest=g)
    assert visit is not None and c is not None
    if visit.status == "checked_in":
        return out("inside", visit=c, guest=g)
    hit = await blacklist.match(db, guest.phone, site.id)
    if hit:
        c.alert = Alert(action=hit.action, reason=hit.reason)  # type: ignore[arg-type]
    return out("blocked" if hit and hit.action == "block" else "ok", visit=c, guest=g)


# ---------- Actions ----------


def _when(occurred_at: datetime | None, not_before: datetime | None) -> datetime:
    """Accept the device's time for replayed offline actions, within reason."""
    t = now()
    if occurred_at is None:
        return t
    at = min(max(occurred_at, t - timedelta(hours=24)), t)
    return max(at, not_before) if not_before else at


async def _admit(db: AsyncSession, v: Visit, guard: Principal, reason: str) -> Visit:
    """Guard override: approve without the host's answer. Audited via the event."""
    t = now()
    return await transition(
        db,
        v.id,
        "approved",
        actor_type="guard",
        actor_id=guard.id,
        channel="web",
        meta={"override": True, "reason": reason},
        approved_at=t,
        responded_at=t,
        responded_by=guard.id,
        response_channel="guard",
        guard_note=reason,
        next_escalation_at=None,
        pass_jti=v.pass_jti or passes.new_jti(),
    )


async def check_in(
    db: AsyncSession,
    org: Organization,
    visit_id: UUID,
    guard: Principal,
    occurred_at: datetime | None,
    override_reason: str | None,
) -> tuple[Visit, AfterCommit]:
    v = await lock(db, visit_id)
    if v.status in ("pending", "waiting"):
        if not override_reason:
            raise AppError(
                409,
                "needs_approval",
                "The host has not approved this visit yet",
                {"current": v.status},
            )
        v = await _admit(db, v, guard, override_reason)
    if v.status != "approved":
        raise InvalidTransition(v.status, "checked_in")
    if v.valid_until <= now():
        raise AppError(409, "pass_expired", "This visit's pass has expired")
    hit = await blacklist.match(db, v.visitor_phone, v.site_id)
    if hit and hit.action == "block":
        raise AppError(403, "blocked", MESSAGES["blocked"], {"reason": hit.reason})
    if hit and not v.blacklist_hit_id:
        v.blacklist_hit_id = hit.id

    if v.invite_guest_id:
        guest, invite = await invite_svc.lock_guest(db, v.invite_guest_id)
        if guest.status == "revoked" or invite.status == "revoked":
            raise AppError(409, "pass_revoked", MESSAGES["revoked"])
        if guest.max_uses is not None and guest.use_count >= guest.max_uses:
            raise AppError(409, "pass_used", MESSAGES["used"])
        guest.use_count += 1
        guest.last_used_at = now()
        if guest.max_uses is not None and guest.use_count >= guest.max_uses:
            guest.status = "used"

    at = _when(occurred_at, v.approved_at or v.requested_at)
    v = await transition(
        db,
        v.id,
        "checked_in",
        actor_type="guard",
        actor_id=guard.id,
        channel="web",
        meta={"occurred_at": at.isoformat()} if occurred_at else {},
        checked_in_at=at,
        checked_in_by=guard.id,
    )
    after = AfterCommit(visits=[v])
    host = await db.get(User, v.host_id)
    if host and host.phone:
        site = await db.get(Site, v.site_id)
        gate = await db.get(Gate, v.gate_id) if v.gate_id else None
        after.notes.append(
            dispatcher.queue(
                db,
                org_id=org.id,
                to=host.phone,
                template="visitor_arrived",
                locale=org.default_locale,
                params={
                    "visitor": v.visitor_name,
                    "company": f" ({v.visitor_company})" if v.visitor_company else "",
                    "site": site.name if site else "",
                    "gate": f", {gate.name}" if gate else "",
                    "note": f"\nLet in by security: {v.guard_note}" if v.guard_note else "",
                },
                visit_id=v.id,
                user_id=host.id,
            )
        )
    return v, after


async def check_out(
    db: AsyncSession, visit_id: UUID, guard: Principal, occurred_at: datetime | None
) -> tuple[Visit, AfterCommit]:
    v = await lock(db, visit_id)
    at = _when(occurred_at, v.checked_in_at)
    v = await transition(
        db,
        v.id,
        "checked_out",
        actor_type="guard",
        actor_id=guard.id,
        channel="web",
        meta={"occurred_at": at.isoformat()} if occurred_at else {},
        checked_out_at=at,
        checked_out_by=guard.id,
        checkout_method="guard",
    )
    return v, AfterCommit(visits=[v])


async def remind_host(db: AsyncSession, org: Organization, v: Visit) -> AfterCommit:
    if v.status not in ("pending", "waiting"):
        raise InvalidTransition(v.status, "pending")
    approver = await db.get(User, v.current_approver_id or v.host_id)
    if approver is None or not approver.phone:
        raise AppError(409, "no_host_phone", "The host has no phone number")
    after = AfterCommit()
    await ask_approver(db, org, v, approver, "visit_reminder", after)
    return after


# ---------- Background ----------


async def auto_checkout_due(limit: int = 200) -> int:
    """People still checked in when the day ends (the org's auto-checkout time)."""
    t = now()
    async with system_session() as db:
        ids = (
            (
                await db.execute(
                    select(Visit.id)
                    .where(Visit.status == "checked_in", Visit.valid_until <= t)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    done = 0
    for vid in ids:
        async with system_session() as db:
            try:
                v = await lock(db, vid)
                v = await transition(
                    db,
                    vid,
                    "checked_out",
                    actor_type="system",
                    channel="system",
                    meta={"reason": "auto_checkout"},
                    checked_out_at=v.valid_until,
                    checkout_method="auto",
                )
            except InvalidTransition:
                continue
            await db.commit()
            await AfterCommit(visits=[v]).run()
            done += 1
    return done


# ---------- Offline ----------
#
# A pass QR holds only a random jti and an expiry. To check passes with no connection,
# the guard's device keeps an "offline pack" for its site: the public key that signs
# passes, and today's expected passes (approved visits, people inside, invite guests)
# keyed by SHA-256 of the jti. A scan offline verifies the signature locally, looks the
# hash up, and shows who it is. The check-in is queued and replayed through
# ``pass_check_in``, which runs the full server-side scan, so anything the device
# couldn't know (revoked, already used, blacklisted since) still stops it.


def jti_hash(jti: str) -> str:
    return hashlib.sha256(jti.encode()).hexdigest()


async def offline_pack(db: AsyncSession, site: Site) -> OfflinePack:
    t = now()
    q = await queue(db, site.id)
    rows = list(
        (
            await db.execute(
                select(Visit).where(Visit.id.in_([c.id for c in q.expected + q.on_site]))
            )
        ).scalars()
    )
    # A visit made from an invite is entered with the guest's pass.
    guest_jti = dict(
        (
            await db.execute(
                select(InviteGuest.id, InviteGuest.pass_jti).where(
                    InviteGuest.id.in_([v.invite_guest_id for v in rows if v.invite_guest_id])
                )
            )
        ).all()
    )
    jtis = {
        v.id: v.pass_jti or guest_jti.get(v.invite_guest_id)  # type: ignore[arg-type]
        for v in rows
    }
    entries: list[OfflineEntry] = []
    for c in q.expected + q.on_site:
        jti = jtis.get(c.id)
        if not jti:
            continue
        entries.append(
            OfflineEntry(
                h=jti_hash(jti),
                kind="visit",
                ref_id=c.id,
                name=c.visitor_name or "",
                company=c.visitor_company,
                host_name=c.host_name,
                purpose=c.purpose,
                state=c.status,
                accompanying_count=c.accompanying_count,
                valid_until=c.valid_until,
                photo_url=c.photo_url,
                alert=c.alert,
            )
        )
    if q.invites:
        guests = {
            g.id: g
            for g in (
                await db.execute(
                    select(InviteGuest).where(InviteGuest.id.in_([e.guest_id for e in q.invites]))
                )
            ).scalars()
        }
        for e in q.invites:
            g = guests.get(e.guest_id)
            if g is None or not g.phone:
                continue
            hit = await blacklist.match(db, g.phone, site.id)
            entries.append(
                OfflineEntry(
                    h=jti_hash(g.pass_jti),
                    kind="invite",
                    ref_id=g.id,
                    name=e.name,
                    company=e.company,
                    host_name=e.host_name,
                    purpose=e.title,
                    state="invite",
                    accompanying_count=0,
                    valid_from=e.valid_from,
                    valid_until=e.valid_until,
                    daily_start_time=e.daily_start_time,
                    daily_end_time=e.daily_end_time,
                    consented=e.consented,
                    alert=Alert(action=hit.action, reason=hit.reason) if hit else None,  # type: ignore[arg-type]
                )
            )
    day_end = invite_svc.today_start(t) + timedelta(days=1)
    return OfflinePack(
        site_id=site.id,
        generated_at=t,
        use_until=day_end,
        key=passes.public_jwk(),
        entries=entries,
    )


async def pass_check_in(
    db: AsyncSession,
    org: Organization,
    site: Site,
    payload: str,
    guard: Principal,
    occurred_at: datetime | None,
) -> tuple[ScanOut, AfterCommit]:
    """Scan + check in, in one step: what an offline check-in replays once the
    connection is back. Refused (409) if the server-side scan says no."""
    at = _when(occurred_at, None)
    r, after = await scan(db, org, site, payload, guard.id, at)
    if r.result == "inside":
        return r, after  # already done (e.g. replayed twice, or another guard)
    if r.result != "ok" or r.visit is None or (r.visit.alert and r.visit.alert.action == "block"):
        raise AppError(
            409,
            f"pass_{r.result}",
            r.message,
            {"name": r.visit.visitor_name if r.visit else (r.guest.name if r.guest else None)},
        )
    v, more = await check_in(db, org, r.visit.id, guard, occurred_at, None)
    after = AfterCommit(notes=after.notes + more.notes, visits=[v])
    return ScanOut(
        result="ok", message=MESSAGES["ok"], visit=await card(db, v), guest=r.guest
    ), after
