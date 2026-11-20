"""Blacklist (admins): people to stop (``block``) or watch for (``alert``) at the gate."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response
from sqlalchemy import func, select

from app.core.deps import AdminUser, TenantDB
from app.core.errors import AppError
from app.models import BlacklistEntry, Site, User, Visit
from app.schemas.common import Page
from app.schemas.invites import BlacklistIn, BlacklistOut, BlacklistUpdate
from app.services import audit
from app.services.loaders import EntryPath

router = APIRouter(prefix="/blacklist", tags=["blacklist"])


async def _out(db, rows: list[BlacklistEntry]) -> list[BlacklistOut]:  # noqa: ANN001
    if not rows:
        return []
    sites = {s.id: s.name for s in (await db.execute(select(Site))).scalars()}
    users = {
        u.id: u.full_name
        for u in (
            await db.execute(
                select(User).where(User.id.in_({r.added_by for r in rows if r.added_by}))
            )
        ).scalars()
    }
    hits = dict(
        (
            await db.execute(
                select(Visit.blacklist_hit_id, func.count())
                .where(Visit.blacklist_hit_id.in_([r.id for r in rows]))
                .group_by(Visit.blacklist_hit_id)
            )
        ).all()
    )
    return [
        BlacklistOut(
            id=r.id,
            phone=r.phone,
            name=r.name,
            reason=r.reason,
            action=r.action,
            site_id=r.site_id,
            site_name=sites.get(r.site_id) if r.site_id else None,
            expires_at=r.expires_at,
            is_active=r.is_active,
            added_by_name=users.get(r.added_by) if r.added_by else None,
            created_at=r.created_at,
            hits=hits.get(r.id, 0),
        )
        for r in rows
    ]


async def _check_site(db, site_id: UUID | None) -> None:  # noqa: ANN001
    if site_id and not (await db.execute(select(Site.id).where(Site.id == site_id))).first():
        raise AppError(422, "invalid_site", "Choose a site")


@router.get("", response_model=Page[BlacklistOut])
async def list_entries(
    _: AdminUser,
    db: TenantDB,
    q: Annotated[str | None, Query(max_length=100)] = None,
    active: bool | None = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[BlacklistOut]:
    stmt = select(BlacklistEntry)
    if active is not None:
        stmt = stmt.where(BlacklistEntry.is_active.is_(active))
    if q:
        like = f"%{q.strip().lower()}%"
        digits = "".join(c for c in q if c.isdigit())
        cond = func.lower(func.coalesce(BlacklistEntry.name, "")).like(like)
        if len(digits) >= 3:
            cond = cond | BlacklistEntry.phone.like(f"%{digits}%")
        stmt = stmt.where(cond)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list(
        (
            await db.execute(
                stmt.order_by(BlacklistEntry.created_at.desc()).limit(limit).offset(offset)
            )
        ).scalars()
    )
    return Page(items=await _out(db, rows), total=total, limit=limit, offset=offset)


@router.post("", response_model=BlacklistOut, status_code=201)
async def add_entry(body: BlacklistIn, p: AdminUser, db: TenantDB) -> BlacklistOut:
    await _check_site(db, body.site_id)
    e = BlacklistEntry(org_id=p.org_id, added_by=p.id, is_active=True, **body.model_dump())
    db.add(e)
    await db.flush()
    audit.record(
        db, p, "blacklist.add", "blacklist_entry", e.id, {"phone": e.phone[-4:], "action": e.action}
    )
    await db.commit()
    return (await _out(db, [e]))[0]


@router.patch("/{entry_id}", response_model=BlacklistOut)
async def update_entry(
    entry: EntryPath, body: BlacklistUpdate, p: AdminUser, db: TenantDB
) -> BlacklistOut:
    data = body.model_dump(exclude_unset=True)
    if "site_id" in data:
        await _check_site(db, data["site_id"])
    diff = audit.changes(entry, data)
    if diff:
        audit.record(db, p, "blacklist.update", "blacklist_entry", entry.id, diff)
        await db.commit()
    return (await _out(db, [entry]))[0]


@router.delete("/{entry_id}", status_code=204)
async def remove_entry(entry: EntryPath, p: AdminUser, db: TenantDB) -> Response:
    """Soft delete: the entry stays linked to the visits it stopped."""
    if entry.is_active:
        entry.is_active = False
        audit.record(db, p, "blacklist.remove", "blacklist_entry", entry.id)
        await db.commit()
    return Response(status_code=204)
