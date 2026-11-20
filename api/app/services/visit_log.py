"""The visit log: one filtered query shared by the log screen, the host's history and
every export, so a CSV always contains exactly what the screen showed."""

import base64
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Department, Gate, Purpose, Site, User, Visit
from app.schemas.reports import VisitFilters, VisitRow
from app.services.visits import IST


def day_start(d: date) -> datetime:
    return datetime.combine(d, time(0), IST).astimezone(UTC)


def day_after(d: date) -> datetime:
    return day_start(d + timedelta(days=1))


def base_query(f: VisitFilters, host_only: UUID | None = None) -> Select:
    host = User.__table__.alias("host")
    q = (
        select(
            Visit,
            host.c.full_name.label("host_name"),
            Department.name.label("department"),
            Site.name.label("site_name"),
            Gate.name.label("gate_name"),
            Purpose.label.label("purpose"),
        )
        .join(host, host.c.id == Visit.host_id)
        .join(Site, Site.id == Visit.site_id)
        .outerjoin(Department, Department.id == host.c.department_id)
        .outerjoin(Gate, Gate.id == Visit.gate_id)
        .outerjoin(Purpose, Purpose.id == Visit.purpose_id)
    )
    conds = []
    if host_only:
        conds.append(Visit.host_id == host_only)
        # Blacklist-blocked attempts: the host was never asked; admins and guards see them.
        conds.append(
            ~(
                (Visit.status == "rejected")
                & Visit.responded_by.is_(None)
                & Visit.blacklist_hit_id.is_not(None)
            )
        )
    if f.from_date:
        conds.append(Visit.requested_at >= day_start(f.from_date))
    if f.to_date:
        conds.append(Visit.requested_at < day_after(f.to_date))
    if f.site_id:
        conds.append(Visit.site_id == f.site_id)
    if f.gate_id:
        conds.append(Visit.gate_id == f.gate_id)
    if f.host_id:
        conds.append(Visit.host_id == f.host_id)
    if f.department_id:
        conds.append(host.c.department_id == f.department_id)
    if f.purpose_id:
        conds.append(Visit.purpose_id == f.purpose_id)
    if f.status:
        conds.append(Visit.status.in_(f.status))
    if f.source:
        conds.append(Visit.source == f.source)
    if f.q and f.q.strip():
        text = f.q.strip().lower().replace("%", "").replace("_", "")
        like = f"%{text}%"
        digits = "".join(c for c in text if c.isdigit())
        alts = [
            func.lower(Visit.visitor_name).like(like),
            func.lower(Visit.visitor_company).like(like),
            func.lower(host.c.full_name).like(like),
            func.lower(func.replace(Visit.vehicle_number, " ", "")).like(
                f"%{text.replace(' ', '')}%"
            ),
        ]
        if len(digits) >= 4:
            alts.append(Visit.visitor_phone.like(f"%{digits}"))
        conds.append(or_(*alts))
    if conds:
        q = q.where(and_(*conds))
    return q


def to_row(r: Any) -> VisitRow:
    v: Visit = r[0]
    wait = (
        int((v.responded_at - v.requested_at).total_seconds())
        if v.responded_at and v.response_channel in ("whatsapp", "web")
        else None
    )
    return VisitRow(
        id=v.id,
        status=v.status,
        source=v.source,
        visitor_name=v.visitor_name,
        visitor_company=v.visitor_company,
        visitor_phone=v.visitor_phone,
        host_id=v.host_id,
        host_name=r.host_name,
        department=r.department,
        site_id=v.site_id,
        site_name=r.site_name,
        gate_name=r.gate_name,
        purpose=r.purpose,
        purpose_note=v.purpose_note,
        accompanying_count=v.accompanying_count,
        vehicle_number=v.vehicle_number,
        requested_at=v.requested_at,
        responded_at=v.responded_at,
        response_channel=v.response_channel,
        checked_in_at=v.checked_in_at,
        checked_out_at=v.checked_out_at,
        checkout_method=v.checkout_method,
        wait_seconds=wait,
        guard_note=v.guard_note,
        flagged=v.blacklist_hit_id is not None,
        anonymized=v.anonymized_at is not None,
    )


def encode_cursor(v: Visit) -> str:
    raw = f"{v.requested_at.isoformat()}|{v.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(c: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(c + "=" * (-len(c) % 4)).decode()
        at, vid = raw.split("|")
        return datetime.fromisoformat(at), UUID(vid)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError(422, "bad_cursor", "Invalid page cursor") from exc


async def page(
    db: AsyncSession,
    f: VisitFilters,
    *,
    limit: int,
    cursor: str | None,
    host_only: UUID | None = None,
) -> tuple[list[VisitRow], str | None, int | None]:
    """Newest first; keyset pagination on (requested_at, id) so pages stay stable while
    new visits arrive."""
    q = base_query(f, host_only)
    total = None
    if cursor:
        at, vid = decode_cursor(cursor)
        q = q.where(or_(Visit.requested_at < at, and_(Visit.requested_at == at, Visit.id < vid)))
    else:
        total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (
        await db.execute(q.order_by(Visit.requested_at.desc(), Visit.id.desc()).limit(limit + 1))
    ).all()
    more = len(rows) > limit
    rows = rows[:limit]
    nxt = encode_cursor(rows[-1][0]) if more and rows else None
    return [to_row(r) for r in rows], nxt, total


async def all_rows(
    db: AsyncSession, f: VisitFilters, cap: int, host_only: UUID | None = None
) -> list[VisitRow]:
    q = base_query(f, host_only).order_by(Visit.requested_at.desc(), Visit.id.desc()).limit(cap)
    return [to_row(r) for r in (await db.execute(q)).all()]
