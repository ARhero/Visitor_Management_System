"""Visit lifecycle: check-in submission, host responses, escalation and expiry.

Status changes always go through ``visit_state.transition``. Messages and live
updates are collected in an ``AfterCommit`` and sent only once the transaction
has committed.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, any_, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import tokens
from app.core.config import get_settings
from app.core.db import system_session
from app.core.errors import AppError, not_found
from app.models import (
    ConsentNotice,
    ConsentRecord,
    CustomField,
    Gate,
    NotificationLog,
    Organization,
    Purpose,
    Site,
    User,
    Visit,
    VisitEvent,
    Visitor,
)
from app.notifications import dispatcher
from app.notifications.templates import OUTCOMES, pick
from app.schemas.visits import VisitIn
from app.services import blacklist, passes, realtime
from app.services.visit_state import OPEN, InvalidTransition, lock, transition

IST = ZoneInfo("Asia/Kolkata")
ACTION_TO_STATUS = {"approve": "approved", "reject": "rejected", "wait": "waiting"}
DETAIL = {
    "note": {"en": "Note", "hi": "टिप्पणी"},
    "people": {"en": "With {n} more", "hi": "साथ में {n} और"},
    "vehicle": {"en": "Vehicle", "hi": "वाहन"},
}


@dataclass
class AfterCommit:
    notes: list[NotificationLog] = field(default_factory=list)
    visits: list[Visit] = field(default_factory=list)

    async def run(self) -> None:
        await dispatcher.dispatch([n.id for n in self.notes])
        for v in self.visits:
            await realtime.publish_visit(v.org_id, v.site_id, v.id, v.status)


def now() -> datetime:
    return datetime.now(UTC)


def day_end(org_settings: dict[str, Any], at: datetime) -> datetime:
    """A visit (and its pass) is good until the org's auto-checkout time that day, IST.
    Late arrivals (less than an hour before that time) get 4 hours."""
    local = at.astimezone(IST)
    t = time.fromisoformat(str(org_settings.get("auto_checkout_time", "20:00:00")))
    end = datetime.combine(local.date(), t, IST)
    if end <= local + timedelta(hours=1):
        end = local + timedelta(hours=4)
    return end.astimezone(UTC)


def phone_check_on(org: Organization) -> bool:
    """Do visitors prove their number with a WhatsApp code? Never when WhatsApp is off."""
    return get_settings().whatsapp_enabled and bool(
        (org.settings or {}).get("verify_visitor_phone", True)
    )


def respond_link(v: Visit, user_id: UUID) -> str:
    tok = tokens.sign(
        "respond", {"o": str(v.org_id), "v": str(v.id), "u": str(user_id)}, v.valid_until
    )
    return f"{get_settings().public_web_url.rstrip('/')}/r/{tok}"


def status_token(v: Visit) -> str:
    return tokens.sign(
        "visit", {"o": str(v.org_id), "v": str(v.id)}, v.valid_until + timedelta(hours=12)
    )


def pass_token(v: Visit) -> str | None:
    if not v.pass_jti or v.status not in ("approved", "checked_in"):
        return None
    return passes.issue(v.pass_jti, v.valid_until)


# ---------- Messages ----------


async def _names(db: AsyncSession, v: Visit) -> tuple[Site, Gate | None, User, Purpose | None]:
    site = await db.get(Site, v.site_id)
    gate = await db.get(Gate, v.gate_id) if v.gate_id else None
    host = await db.get(User, v.host_id)
    purpose = await db.get(Purpose, v.purpose_id) if v.purpose_id else None
    assert site and host
    return site, gate, host, purpose


def _details(v: Visit, locale: str) -> str:
    out = []
    if v.purpose_note:
        out.append(f"{pick(DETAIL['note'], locale)}: {v.purpose_note}")
    if v.accompanying_count:
        out.append(pick(DETAIL["people"], locale).format(n=v.accompanying_count))
    if v.vehicle_number:
        out.append(f"{pick(DETAIL['vehicle'], locale)}: {v.vehicle_number}")
    return "".join(f"\n{line}" for line in out)


async def ask_approver(
    db: AsyncSession, org: Organization, v: Visit, approver: User, template: str, after: AfterCommit
) -> None:
    site, gate, host, purpose = await _names(db, v)
    locale = org.default_locale
    after.notes.append(
        dispatcher.queue(
            db,
            org_id=org.id,
            to=approver.phone or "",
            template=template,
            locale=locale,
            params={
                "visitor": v.visitor_name,
                "company": f", {v.visitor_company}" if v.visitor_company else "",
                "site": site.name,
                "gate": gate.name if gate else "",
                "purpose": (purpose.label_i18n.get(locale) or purpose.label) if purpose else "",
                "details": _details(v, locale),
                "host": host.full_name,
                "link": respond_link(v, approver.id),
            },
            visit_id=v.id,
            user_id=approver.id,
            actions=("approve", "wait", "reject"),
            button_ref=str(v.id),
        )
    )


async def tell_visitor(
    db: AsyncSession, v: Visit, template: str, after: AfterCommit, **extra: str
) -> None:
    if not v.visitor_phone:
        return
    site, _, host, _ = await _names(db, v)
    msg = f" “{v.host_message}”" if v.host_message else ""
    after.notes.append(
        dispatcher.queue(
            db,
            org_id=v.org_id,
            to=v.visitor_phone,
            template=template,
            locale=v.locale,
            params={"host": host.full_name, "site": site.name, "message": msg, **extra},
            visit_id=v.id,
        )
    )


# ---------- Check-in ----------


def validate_custom_values(fields: list[CustomField], values: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    known = {f.key: f for f in fields}
    out: dict[str, Any] = {}
    for key in values:
        if key not in known:
            errors.append({"field": key, "msg": "Unknown field"})
    for f in fields:
        val = values.get(f.key)
        empty = val is None or val == "" or val is False
        if empty:
            if f.required or f.type == "declaration":
                errors.append({"field": f.key, "msg": "This is required"})
            continue
        if f.type == "number":
            try:
                out[f.key] = float(val) if "." in str(val) else int(val)
            except ValueError:
                errors.append({"field": f.key, "msg": "Enter a number"})
        elif f.type == "select":
            if val not in f.options:
                errors.append({"field": f.key, "msg": "Choose one of the options"})
            else:
                out[f.key] = val
        elif f.type == "checkbox":
            out[f.key] = bool(val)
        elif f.type == "declaration":
            # Keep the exact wording that was accepted.
            out[f.key] = {"accepted": True, "text": f.label}
        else:
            out[f.key] = str(val).strip()[:500]
    if errors:
        raise AppError(422, "invalid_fields", "Some answers need attention", errors)
    return out


async def create(
    db: AsyncSession,
    *,
    org: Organization,
    site: Site,
    gate: Gate | None,
    phone: str,
    body: VisitIn,
    photo_key: str | None,
    id_image_key: str | None,
    ip: str | None,
    user_agent: str | None,
    source: str = "qr_self",
    actor_type: str = "visitor",
    actor_id: UUID | None = None,
    ask_host: bool = True,
    phone_verified: bool = True,
) -> tuple[Visit, AfterCommit, bool]:
    """Returns (visit, after_commit, created). Re-submitting while a request to the same
    host is still open returns that visit instead of pinging the host twice.

    A phone on the blacklist with ``block`` gets a visit that is rejected straight away
    (so the attempt is on record and the guard is alerted) and the host is not asked;
    the caller tells the person to see reception. ``alert`` lets the visit continue,
    flagged for the guard.

    ``phone_verified`` False (typed in without a code, WhatsApp off) means anyone could
    have typed this number, so nothing stored under it is handed back: no earlier
    photo, and no existing open request (that would give away its pass)."""
    settings = org.settings or {}
    t = now()

    host = (
        await db.execute(select(User).where(User.id == body.host_id, User.is_active.is_(True)))
    ).scalar_one_or_none()
    if host is None or "host" not in host.roles or not host.phone:
        raise AppError(422, "invalid_host", "Please choose the person you are visiting")
    purpose = (
        await db.execute(
            select(Purpose).where(Purpose.id == body.purpose_id, Purpose.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if purpose is None:
        raise AppError(422, "invalid_purpose", "Please choose a purpose")
    notice = await db.get(ConsentNotice, body.consent_notice_id)
    if notice is None or not notice.is_current:
        raise AppError(
            409, "notice_changed", "The privacy notice was updated. Please review it again."
        )

    # ID proof: only type + last 4 characters, and only when asked for.
    mode = settings.get("id_proof_mode", "off")
    id_needed = mode == "required" or purpose.requires_id_proof
    if id_needed and not (body.id_type and body.id_last4):
        raise AppError(422, "id_required", "Please enter your ID type and its last 4 characters")
    id_type, id_last4 = (
        (body.id_type, body.id_last4) if (id_needed or mode != "off") else (None, None)
    )

    fields = (
        (
            await db.execute(
                select(CustomField)
                .where(
                    CustomField.is_active.is_(True),
                    CustomField.applies_to.in_(("checkin", "both")),
                    (CustomField.site_id.is_(None)) | (CustomField.site_id == site.id),
                )
                .order_by(CustomField.sort_order)
            )
        )
        .scalars()
        .all()
    )
    custom = validate_custom_values(list(fields), body.custom_values)

    visitor = (await db.execute(select(Visitor).where(Visitor.phone == phone))).scalar_one_or_none()
    if (
        photo_key is None
        and phone_verified
        and body.use_previous_photo
        and visitor
        and visitor.last_photo_key
    ):
        photo_key = visitor.last_photo_key
    if settings.get("require_selfie", True) and not photo_key:
        raise AppError(422, "photo_required", "Please take a photo")

    if visitor is None:
        visitor = Visitor(org_id=org.id, phone=phone, first_seen_at=t, visit_count=0)
        db.add(visitor)
    visitor.full_name = body.full_name
    visitor.company = body.company
    visitor.email = body.email or visitor.email
    visitor.preferred_locale = body.locale
    if photo_key:
        visitor.last_photo_key = photo_key
    await db.flush()

    existing = (
        await db.execute(
            select(Visit).where(
                Visit.visitor_id == visitor.id,
                Visit.host_id == host.id,
                Visit.site_id == site.id,
                Visit.status.in_(OPEN),
                Visit.valid_until > t,
            )
        )
    ).scalar_one_or_none()
    if existing:
        if not phone_verified:
            raise AppError(
                409,
                "already_requested",
                "A request from this number to this person is already open. "
                "Please speak to the security desk at the gate.",
            )
        return existing, AfterCommit(), False

    hit = await blacklist.match(db, phone, site.id)
    visitor.visit_count += 1
    visitor.last_visit_at = t
    timeout = int(settings.get("approval_timeout_min", 5))
    v = Visit(
        org_id=org.id,
        site_id=site.id,
        gate_id=gate.id if gate else None,
        host_id=host.id,
        visitor_id=visitor.id,
        source=source,
        status="pending",
        locale=body.locale,
        visitor_name=body.full_name,
        visitor_company=body.company,
        visitor_phone=phone,
        phone_verified=phone_verified,
        purpose_id=purpose.id,
        purpose_note=body.purpose_note,
        accompanying_count=body.accompanying_count,
        vehicle_number=body.vehicle_number,
        custom_values=custom,
        photo_key=photo_key,
        id_type=id_type,
        id_last4=id_last4,
        id_image_key=id_image_key if settings.get("store_id_image") else None,
        current_approver_id=host.id,
        notified_approver_ids=[host.id],
        escalation_level=0,
        next_escalation_at=t + timedelta(minutes=timeout),
        requested_at=t,
        valid_until=day_end(settings, t),
        blacklist_hit_id=hit.id if hit else None,
    )
    db.add(v)
    await db.flush()
    db.add(
        VisitEvent(
            org_id=org.id,
            visit_id=v.id,
            from_status=None,
            to_status="pending",
            actor_type=actor_type,
            actor_id=actor_id,
            channel="web",
        )
    )
    db.add(
        ConsentRecord(
            org_id=org.id,
            visitor_id=visitor.id,
            visit_id=v.id,
            notice_id=notice.id,
            locale=body.locale,
            consented_at=t,
            ip=ip,
            user_agent=user_agent,
        )
    )
    after = AfterCommit(visits=[v])
    if hit and hit.action == "block":
        v = await transition(
            db,
            v.id,
            "rejected",
            actor_type="system",
            channel="system",
            meta={"reason": "blacklist", "entry": str(hit.id)},
            next_escalation_at=None,
            current_approver_id=None,
        )
    elif ask_host:
        await ask_approver(db, org, v, host, "visit_request", after)
    return v, after, True


def blocked(v: Visit) -> bool:
    return v.status == "rejected" and v.blacklist_hit_id is not None and v.responded_by is None


# ---------- Host response ----------


async def respond(
    db: AsyncSession,
    org: Organization,
    visit_id: UUID,
    user: User,
    action: str,
    message: str | None,
    channel: str,
) -> tuple[Visit, AfterCommit]:
    v = await lock(db, visit_id)
    if user.id != v.host_id and user.id not in (v.notified_approver_ids or []):
        raise not_found("Visit")  # not theirs to answer; don't reveal it exists
    to = ACTION_TO_STATUS[action]
    t = now()
    changes: dict[str, Any] = {
        "responded_at": t,
        "responded_by": user.id,
        "response_channel": channel,
        "host_message": message,
        "next_escalation_at": None,
    }
    if to == "approved":
        changes |= {"pass_jti": v.pass_jti or passes.new_jti(), "approved_at": t}
    v = await transition(
        db,
        v.id,
        to,
        actor_type="host",
        actor_id=user.id,
        channel=channel,
        meta={"message": message} if message else {},
        **changes,
    )
    after = AfterCommit(visits=[v])
    if to == "approved":
        tok = pass_token(v)
        await tell_visitor(db, v, "visit_approved", after, pass_url=passes.pass_url(tok or ""))
    else:
        await tell_visitor(db, v, f"visit_{to}", after)
    if channel == "whatsapp" and user.phone:
        locale = org.default_locale
        after.notes.append(
            dispatcher.queue(
                db,
                org_id=org.id,
                to=user.phone,
                template="response_ack",
                locale=locale,
                params={"visitor": v.visitor_name, "outcome": pick(OUTCOMES[to], locale)},
                visit_id=v.id,
                user_id=user.id,
            )
        )
    return v, after


def too_late_note(
    db: AsyncSession, org: Organization, v: Visit, user: User, current: str
) -> NotificationLog:
    locale = org.default_locale
    return dispatcher.queue(
        db,
        org_id=org.id,
        to=user.phone or "",
        template="response_too_late",
        locale=locale,
        params={
            "visitor": v.visitor_name,
            "outcome": pick(OUTCOMES.get(current, {"en": current}), locale),
        },
        visit_id=v.id,
        user_id=user.id,
    )


async def cancel_by_visitor(db: AsyncSession, visit_id: UUID) -> tuple[Visit, AfterCommit]:
    v = await transition(
        db, visit_id, "cancelled", actor_type="visitor", channel="web", next_escalation_at=None
    )
    return v, AfterCommit(visits=[v])


# ---------- Background: escalation and expiry (system session, all orgs) ----------


async def escalate_due(limit: int = 50) -> int:
    """Pending visits whose approver didn't answer in time go to that approver's backup
    host, up to ``max_escalations`` levels. With nobody left to ask, the visit expires
    and the visitor is told to check with reception."""
    t = now()
    async with system_session() as db:
        ids = (
            (
                await db.execute(
                    select(Visit.id)
                    .where(Visit.status == "pending", Visit.next_escalation_at <= t)
                    .order_by(Visit.next_escalation_at)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    done = 0
    for vid in ids:
        async with system_session() as db:
            v = await lock(db, vid)
            if v.status != "pending" or not v.next_escalation_at or v.next_escalation_at > t:
                continue
            org = await db.get(Organization, v.org_id)
            assert org is not None
            settings = org.settings or {}
            approver = await db.get(User, v.current_approver_id) if v.current_approver_id else None
            backup = None
            if (
                approver
                and approver.backup_host_id
                and v.escalation_level < int(settings.get("max_escalations", 2))
            ):
                b = await db.get(User, approver.backup_host_id)
                if (
                    b
                    and b.is_active
                    and "host" in b.roles
                    and b.phone
                    and b.id not in v.notified_approver_ids
                ):
                    backup = b
            after = AfterCommit()
            if backup:
                v.escalation_level += 1
                v.current_approver_id = backup.id
                v.notified_approver_ids = [*v.notified_approver_ids, backup.id]
                v.next_escalation_at = t + timedelta(
                    minutes=int(settings.get("approval_timeout_min", 5))
                )
                db.add(
                    VisitEvent(
                        org_id=v.org_id,
                        visit_id=v.id,
                        from_status="pending",
                        to_status="pending",
                        actor_type="system",
                        channel="system",
                        meta={"escalated_to": str(backup.id), "level": v.escalation_level},
                    )
                )
                await ask_approver(db, org, v, backup, "visit_escalated", after)
            else:
                v = await transition(
                    db,
                    v.id,
                    "expired",
                    actor_type="system",
                    channel="system",
                    meta={"reason": "no_response"},
                    next_escalation_at=None,
                )
                await tell_visitor(db, v, "visit_expired", after)
                after.visits.append(v)
            await db.commit()
            await after.run()
            done += 1
    return done


async def expire_stale(limit: int = 200) -> int:
    """Open visits whose day is over: never answered, or approved but never arrived."""
    t = now()
    async with system_session() as db:
        ids = (
            (
                await db.execute(
                    select(Visit.id)
                    .where(
                        Visit.status.in_(("pending", "waiting", "approved")), Visit.valid_until <= t
                    )
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    for vid in ids:
        async with system_session() as db:
            try:
                v = await transition(
                    db,
                    vid,
                    "expired",
                    actor_type="system",
                    channel="system",
                    meta={"reason": "day_over"},
                    next_escalation_at=None,
                )
            except InvalidTransition:
                continue
            await db.commit()
            await AfterCommit(visits=[v]).run()
    return len(ids)


async def open_visits_for(db: AsyncSession, user_id: UUID) -> list[Visit]:
    """Visits this person was asked about that are still waiting for an answer."""
    return list(
        (
            await db.execute(
                select(Visit)
                .where(
                    and_(
                        Visit.status.in_(OPEN),
                        literal(user_id) == any_(Visit.notified_approver_ids),
                    )
                )
                .order_by(Visit.requested_at)
            )
        ).scalars()
    )
