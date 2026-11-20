"""DPDP: retention, and a visitor's rights to see, download and erase their data.

Anonymizing a visit keeps what reports need (site, gate, host, purpose, times, status)
and removes everything that identifies the visitor: name, phone, company, notes,
vehicle, custom answers, ID details, photos, and the text of the WhatsApp messages
about the visit. Consent records keep the notice version and time (proof of consent)
but lose the IP address and browser.

- Retention: every org's visits older than ``retention_days`` are anonymized, then
  visitors with nothing left, invite guests whose invite ended before the cutoff, and
  uploaded photos that never became part of a visit (an abandoned check-in).
- Erasure: the same, at once, for every record with one phone number in one org.
  Not allowed while that person has a visit in progress.

What is kept on purpose: blacklist entries (security, set by an admin, with their own
expiry) and the platform's WhatsApp opt-out record (so a STOP keeps working).

Files are deleted only after the database change commits, so a failed run never leaves
a record pointing at a missing photo.
"""

import hashlib
import hmac
import io
import json
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import case, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import system_session, tenant_session
from app.core.errors import AppError
from app.core.redis import get_redis
from app.models import (
    AuditLog,
    BlacklistEntry,
    ConsentNotice,
    ConsentRecord,
    Gate,
    Invite,
    InviteGuest,
    NotificationLog,
    Organization,
    Purpose,
    Site,
    User,
    Visit,
    Visitor,
)
from app.services import storage
from app.services.visits import IST

log = logging.getLogger(__name__)

ACTIVE = ("pending", "waiting", "approved", "checked_in")
REMOVED = "[removed]"
BATCH = 500
ORPHAN_AGE = timedelta(days=1)  # upload tokens last an hour; a day is plenty
RUN_EVERY = timedelta(hours=6)


def now() -> datetime:
    return datetime.now(UTC)


def mask(phone: str) -> str:
    return phone[:3] + "•" * max(len(phone) - 7, 0) + phone[-4:]


def phone_hash(org_id: UUID, phone: str) -> str:
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, f"privacy:{org_id}:{phone}".encode(), hashlib.sha256).hexdigest()


@dataclass
class Result:
    visits: int = 0
    visitors: int = 0
    guests: int = 0
    messages: int = 0
    files: int = 0
    keys: set[str] = field(default_factory=set)  # deleted after commit

    def counts(self) -> dict[str, int]:
        return {
            "visits": self.visits,
            "visitors": self.visitors,
            "guests": self.guests,
            "messages": self.messages,
            "files": self.files + len(self.keys),
        }

    @property
    def any(self) -> bool:
        return any(self.counts().values())


# ---------- Building blocks (caller's transaction) ----------

VISIT_PII = {
    "visitor_name": None,
    "visitor_company": None,
    "visitor_phone": None,
    "purpose_note": None,
    "vehicle_number": None,
    "custom_values": {},
    "photo_key": None,
    "id_last4": None,
    "id_image_key": None,
    "host_message": None,
    "guard_note": None,
    "pass_jti": None,
}
SCRUBBED = {"params": {}, "buttons": [], "text": REMOVED}


async def anonymize_visits(db: AsyncSession, ids: list[UUID], res: Result) -> None:
    if not ids:
        return
    keys = (
        await db.execute(select(Visit.photo_key, Visit.id_image_key).where(Visit.id.in_(ids)))
    ).all()
    res.keys |= {k for row in keys for k in row if k}
    t = now()
    await db.execute(update(Visit).where(Visit.id.in_(ids)).values(**VISIT_PII, anonymized_at=t))
    # Every message about these visits (to the host too) quotes the visitor's name.
    r = await db.execute(
        update(NotificationLog)
        .where(NotificationLog.visit_id.in_(ids), NotificationLog.payload != SCRUBBED)
        .values(payload=SCRUBBED)
    )
    res.messages += r.rowcount or 0
    await db.execute(
        update(NotificationLog)
        .where(NotificationLog.visit_id.in_(ids), NotificationLog.recipient_user_id.is_(None))
        .values(recipient_phone=None)
    )
    await db.execute(
        update(ConsentRecord)
        .where(ConsentRecord.visit_id.in_(ids))
        .values(ip=None, user_agent=None)
    )
    res.visits += len(ids)


async def anonymize_visitors(db: AsyncSession, ids: list[UUID], res: Result) -> None:
    if not ids:
        return
    res.keys |= {
        k
        for k in (
            await db.execute(select(Visitor.last_photo_key).where(Visitor.id.in_(ids)))
        ).scalars()
        if k
    }
    await db.execute(
        update(Visitor)
        .where(Visitor.id.in_(ids))
        .values(
            phone=None,
            full_name=None,
            company=None,
            email=None,
            last_photo_key=None,
            anonymized_at=now(),
        )
    )
    await db.execute(
        update(ConsentRecord)
        .where(ConsentRecord.visitor_id.in_(ids))
        .values(ip=None, user_agent=None)
    )
    res.visitors += len(ids)


async def anonymize_guests(db: AsyncSession, ids: list[UUID], res: Result) -> None:
    if not ids:
        return
    await db.execute(
        update(InviteGuest)
        .where(InviteGuest.id.in_(ids))
        .values(
            name=None,
            phone=None,
            company=None,
            status=case((InviteGuest.status == "active", "revoked"), else_=InviteGuest.status),
        )
    )
    res.guests += len(ids)


async def delete_files(keys: set[str]) -> int:
    done = 0
    for k in keys:
        try:
            await storage.delete(k)
            done += 1
        except Exception:  # noqa: BLE001
            log.warning("could not delete %s (it will be found again as an orphan)", k)
    return done


# ---------- Retention ----------


async def retention_run(org_id: UUID, at: datetime | None = None) -> dict[str, int]:
    """Anonymize everything past the org's retention period. Idempotent."""
    at = at or now()
    res = Result()
    async with tenant_session(org_id) as db:
        org = await db.get(Organization, org_id)
        if org is None:
            return {}
        days = int((org.settings or {}).get("retention_days", 90))
        cutoff = at - timedelta(days=days)
        while True:
            ids = list(
                (
                    await db.execute(
                        select(Visit.id)
                        .where(
                            Visit.requested_at < cutoff,
                            Visit.anonymized_at.is_(None),
                            Visit.status.not_in(ACTIVE),
                        )
                        .limit(BATCH)
                    )
                ).scalars()
            )
            await anonymize_visits(db, ids, res)
            if len(ids) < BATCH:
                break
        # Guests first: a visitor whose only link was an old invite can then go too.
        guest_ids = list(
            (
                await db.execute(
                    select(InviteGuest.id)
                    .join(Invite, Invite.id == InviteGuest.invite_id)
                    .where(Invite.valid_until < cutoff, InviteGuest.phone.is_not(None))
                )
            ).scalars()
        )
        await anonymize_guests(db, guest_ids, res)
        open_visit = exists().where(Visit.visitor_id == Visitor.id, Visit.anonymized_at.is_(None))
        live_guest = exists().where(
            InviteGuest.visitor_id == Visitor.id, InviteGuest.phone.is_not(None)
        )
        visitor_ids = list(
            (
                await db.execute(
                    select(Visitor.id).where(
                        Visitor.anonymized_at.is_(None),
                        func.coalesce(Visitor.last_visit_at, Visitor.first_seen_at) < cutoff,
                        ~open_visit,
                        ~live_guest,
                    )
                )
            ).scalars()
        )
        await anonymize_visitors(db, visitor_ids, res)
        referenced = await _referenced_keys(db)
        if res.any:
            db.add(
                AuditLog(
                    org_id=org_id,
                    actor_type="system",
                    action="retention.purge",
                    entity_type="organization",
                    entity_id=org_id,
                    diff={**res.counts(), "retention_days": days, "cutoff": cutoff.isoformat()},
                )
            )
        await db.commit()
    res.files = await delete_files(res.keys)
    res.keys = set()
    res.files += await _purge_orphans(org_id, referenced, at)
    counts = res.counts()
    await get_redis().set(
        f"retention:last:{org_id}",
        json.dumps({"at": at.isoformat(), **counts}),
        ex=int(timedelta(days=30).total_seconds()),
    )
    return counts


async def _referenced_keys(db: AsyncSession) -> set[str]:
    rows = await db.execute(
        select(Visit.photo_key, Visit.id_image_key).where(
            or_(Visit.photo_key.is_not(None), Visit.id_image_key.is_not(None))
        )
    )
    keys = {k for row in rows for k in row if k}
    keys |= {
        k
        for k in (
            await db.execute(
                select(Visitor.last_photo_key).where(Visitor.last_photo_key.is_not(None))
            )
        ).scalars()
        if k
    }
    return keys


async def _purge_orphans(org_id: UUID, referenced: set[str], at: datetime) -> int:
    """Photos uploaded during a check-in that was never submitted."""
    gone = 0
    for kind in ("selfie", "id"):
        try:
            files = await storage.list_keys(f"orgs/{org_id}/{kind}/")
        except Exception:  # noqa: BLE001
            log.warning("could not list uploads for %s", org_id)
            continue
        old = {k for k, mtime in files if at - mtime > ORPHAN_AGE and k not in referenced}
        gone += await delete_files(old)
    return gone


async def retention_due() -> int:
    """Run retention for each org at most every 6 hours (called by the sweeper)."""
    async with system_session() as db:
        orgs = list(
            (
                await db.execute(select(Organization.id).where(Organization.deleted_at.is_(None)))
            ).scalars()
        )
    r = get_redis()
    done = 0
    for org_id in orgs:
        if not await r.set(
            f"retention:lock:{org_id}", 1, nx=True, ex=int(RUN_EVERY.total_seconds())
        ):
            continue
        try:
            counts = await retention_run(org_id)
            done += counts.get("visits", 0) + counts.get("visitors", 0)
        except Exception:  # noqa: BLE001
            log.exception("retention failed for %s", org_id)
            await r.delete(f"retention:lock:{org_id}")
    return done


async def retention_status(db: AsyncSession, org: Organization) -> dict[str, Any]:
    days = int((org.settings or {}).get("retention_days", 90))
    cutoff = now() - timedelta(days=days)
    due = (
        await db.execute(
            select(func.count())
            .select_from(Visit)
            .where(
                Visit.requested_at < cutoff,
                Visit.anonymized_at.is_(None),
                Visit.status.not_in(ACTIVE),
            )
        )
    ).scalar_one()
    anonymized = (
        await db.execute(
            select(func.count()).select_from(Visit).where(Visit.anonymized_at.is_not(None))
        )
    ).scalar_one()
    oldest = (
        await db.execute(select(func.min(Visit.requested_at)).where(Visit.anonymized_at.is_(None)))
    ).scalar_one()
    raw = await get_redis().get(f"retention:last:{org.id}")
    return {
        "retention_days": days,
        "cutoff": cutoff,
        "due": due,
        "anonymized_visits": anonymized,
        "oldest_identifiable": oldest,
        "last_run": json.loads(raw) if raw else None,
    }


# ---------- One person's data ----------


async def _visits_for(db: AsyncSession, phone: str) -> list[Visit]:
    visitor_ids = select(Visitor.id).where(Visitor.phone == phone).scalar_subquery()
    return list(
        (
            await db.execute(
                select(Visit)
                .where(
                    or_(Visit.visitor_phone == phone, Visit.visitor_id.in_(visitor_ids)),
                    Visit.anonymized_at.is_(None),
                )
                .order_by(Visit.requested_at.desc())
            )
        ).scalars()
    )


async def collect(
    db: AsyncSession, org: Organization, phone: str, *, for_admin: bool
) -> dict[str, Any]:
    """Everything held about ``phone`` in this org, as plain data."""
    visitor = (await db.execute(select(Visitor).where(Visitor.phone == phone))).scalar_one_or_none()
    visits = await _visits_for(db, phone)
    names = await _names(db, visits)
    guests = list(
        (
            await db.execute(
                select(InviteGuest, Invite)
                .join(Invite, Invite.id == InviteGuest.invite_id)
                .where(InviteGuest.phone == phone)
                .order_by(Invite.valid_from.desc())
            )
        ).all()
    )
    consents = []
    if visitor:
        consents = list(
            (
                await db.execute(
                    select(ConsentRecord, ConsentNotice)
                    .join(ConsentNotice, ConsentNotice.id == ConsentRecord.notice_id)
                    .where(ConsentRecord.visitor_id == visitor.id)
                    .order_by(ConsentRecord.consented_at.desc())
                )
            ).all()
        )
    messages = list(
        (
            await db.execute(
                select(NotificationLog)
                .where(NotificationLog.recipient_phone == phone, NotificationLog.direction == "out")
                .order_by(NotificationLog.created_at.desc())
                .limit(500)
            )
        ).scalars()
    )
    out: dict[str, Any] = {
        "organization": org.name,
        "phone": phone,
        "generated_at": _ist(now()),
        "visitor": None,
        "visits": [],
        "invitations": [],
        "consents": [],
        "messages": [],
    }
    if visitor:
        out["visitor"] = {
            "name": visitor.full_name,
            "company": visitor.company,
            "email": visitor.email,
            "language": visitor.preferred_locale,
            "first_seen": _ist(visitor.first_seen_at),
            "last_visit": _ist(visitor.last_visit_at),
            "visit_count": visitor.visit_count,
        }
    for v in visits:
        n = names.get(v.id, {})
        row: dict[str, Any] = {
            "id": str(v.id),
            "requested_at": _ist(v.requested_at),
            "site": n.get("site"),
            "gate": n.get("gate"),
            "host": n.get("host"),
            "purpose": n.get("purpose"),
            "purpose_note": v.purpose_note,
            "name": v.visitor_name,
            "company": v.visitor_company,
            "accompanying": v.accompanying_count,
            "vehicle": v.vehicle_number,
            "answers": v.custom_values or {},
            "id_proof": f"{v.id_type} ending {v.id_last4}" if v.id_type and v.id_last4 else None,
            "status": "rejected" if v.blacklist_hit_id and not for_admin else v.status,
            "checked_in_at": _ist(v.checked_in_at),
            "checked_out_at": _ist(v.checked_out_at),
            "has_photo": bool(v.photo_key),
            "has_id_image": bool(v.id_image_key),
            "active": v.status in ACTIVE,
        }
        out["visits"].append(row)
    for g, inv in guests:
        out["invitations"].append(
            {
                "name": g.name,
                "company": g.company,
                "title": inv.title,
                "from": _ist(inv.valid_from),
                "until": _ist(inv.valid_until),
                "status": g.status,
                "times_used": g.use_count,
            }
        )
    for c, notice in consents:
        out["consents"].append(
            {
                "notice_version": notice.version,
                "language": c.locale,
                "accepted_at": _ist(c.consented_at),
                "withdrawn_at": _ist(c.withdrawn_at),
            }
        )
    for m in messages:
        out["messages"].append(
            {
                "at": _ist(m.sent_at or m.created_at),
                "kind": m.template_key,
                "status": m.status,
                "text": "[verification code]"
                if m.template_key == "otp"
                else (m.payload or {}).get("text"),
            }
        )
    if for_admin:
        out["blacklist_entries"] = (
            await db.execute(
                select(func.count())
                .select_from(BlacklistEntry)
                .where(BlacklistEntry.phone == phone)
            )
        ).scalar_one()
    return out


async def export_zip(db: AsyncSession, org: Organization, phone: str, *, for_admin: bool) -> bytes:
    data = await collect(db, org, phone, for_admin=for_admin)
    visits = {str(v.id): v for v in await _visits_for(db, phone)}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for row in data["visits"]:
            v = visits.get(row["id"])
            for attr, label in (("photo_key", "photo"), ("id_image_key", "id")):
                key = getattr(v, attr) if v else None
                if not key:
                    continue
                name = f"photos/{row['requested_at'][:10]}-{row['id'][:8]}-{label}.webp"
                try:
                    z.writestr(name, await storage.read(key))
                    row[f"{label}_file"] = name
                except Exception:  # noqa: BLE001
                    row[f"{label}_file"] = None
        z.writestr("data.json", json.dumps(data, ensure_ascii=False, indent=2))
        z.writestr(
            "README.txt",
            f"Your data held by {org.name} in its visitor management system, "
            f"generated {data['generated_at']} (IST).\n\n"
            "data.json: your details, every visit, invitations, the privacy notices you "
            "accepted and the WhatsApp messages sent to you.\n"
            "photos/: the photos taken at check-in.\n",
        )
    return buf.getvalue()


async def erase(db: AsyncSession, org: Organization, phone: str) -> Result:
    """Anonymize everything for ``phone`` in this org (the caller commits, then calls
    ``delete_files(res.keys)``)."""
    visits = await _visits_for(db, phone)
    if any(v.status in ACTIVE for v in visits):
        raise AppError(
            409,
            "visit_in_progress",
            "This person has a visit in progress. Erase their data after they leave.",
        )
    res = Result()
    await anonymize_visits(db, [v.id for v in visits], res)
    guests = list(
        (await db.execute(select(InviteGuest.id).where(InviteGuest.phone == phone))).scalars()
    )
    await anonymize_guests(db, guests, res)
    visitors = list((await db.execute(select(Visitor.id).where(Visitor.phone == phone))).scalars())
    await db.execute(
        update(ConsentRecord)
        .where(
            ConsentRecord.visitor_id.in_(visitors or [UUID(int=0)]),
            ConsentRecord.withdrawn_at.is_(None),
        )
        .values(withdrawn_at=now())
    )
    await anonymize_visitors(db, visitors, res)
    r = await db.execute(
        update(NotificationLog)
        .where(NotificationLog.recipient_phone == phone)
        .values(recipient_phone=None, payload=SCRUBBED)
    )
    res.messages += r.rowcount or 0
    return res


async def _names(db: AsyncSession, visits: list[Visit]) -> dict[UUID, dict[str, str | None]]:
    if not visits:
        return {}
    sites = {s.id: s.name for s in (await db.execute(select(Site))).scalars()}
    gates = {g.id: g.name for g in (await db.execute(select(Gate))).scalars()}
    hosts = {
        u.id: u.full_name
        for u in (
            await db.execute(select(User).where(User.id.in_({v.host_id for v in visits})))
        ).scalars()
    }
    purposes = {p.id: p.label for p in (await db.execute(select(Purpose))).scalars()}
    return {
        v.id: {
            "site": sites.get(v.site_id),
            "gate": gates.get(v.gate_id) if v.gate_id else None,
            "host": hosts.get(v.host_id),
            "purpose": purposes.get(v.purpose_id) if v.purpose_id else None,
        }
        for v in visits
    }


def _ist(dt: datetime | None) -> str | None:
    return dt.astimezone(IST).strftime("%Y-%m-%d %H:%M") if dt else None
