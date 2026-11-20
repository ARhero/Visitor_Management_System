"""Super-admin tenant management. Uses the system session by design."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.deps import PlatformAdmin, SystemDB
from app.core.errors import conflict, not_found
from app.models import NotificationLog, Organization, Site, User, WhatsAppContact
from app.schemas.common import Page
from app.schemas.org import PlatformOrgCreate, PlatformOrgOut, PlatformOrgUpdate, PlatformStats
from app.services import audit
from app.services.orgs import create_org_with_admin, email_taken

router = APIRouter(prefix="/platform", tags=["platform"])


async def _with_counts(db, orgs: list[Organization]) -> list[PlatformOrgOut]:  # noqa: ANN001
    ids = [o.id for o in orgs]
    users = (
        dict(
            (
                await db.execute(
                    select(User.org_id, func.count())
                    .where(User.org_id.in_(ids), User.is_active.is_(True))
                    .group_by(User.org_id)
                )
            ).all()
        )
        if ids
        else {}
    )
    sites = (
        dict(
            (
                await db.execute(
                    select(Site.org_id, func.count())
                    .where(Site.org_id.in_(ids), Site.is_active.is_(True))
                    .group_by(Site.org_id)
                )
            ).all()
        )
        if ids
        else {}
    )
    out = []
    for o in orgs:
        m = PlatformOrgOut.model_validate(o)
        m.user_count, m.site_count = users.get(o.id, 0), sites.get(o.id, 0)
        out.append(m)
    return out


async def _get(db, org_id: UUID) -> Organization:  # noqa: ANN001
    org = await db.get(Organization, org_id)
    if org is None or org.deleted_at is not None:
        raise not_found("Organization")
    return org


@router.get("/orgs", response_model=Page[PlatformOrgOut])
async def list_orgs(
    _: PlatformAdmin,
    db: SystemDB,
    q: str | None = None,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[PlatformOrgOut]:
    stmt = select(Organization).where(Organization.deleted_at.is_(None))
    if q:
        stmt = stmt.where(func.lower(Organization.name).like(f"%{q.lower()}%"))
    if status:
        stmt = stmt.where(Organization.status == status)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    orgs = (
        (
            await db.execute(
                stmt.order_by(Organization.created_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return Page(items=await _with_counts(db, list(orgs)), total=total, limit=limit, offset=offset)


@router.post("/orgs", response_model=PlatformOrgOut, status_code=201)
async def create_org(body: PlatformOrgCreate, p: PlatformAdmin, db: SystemDB) -> PlatformOrgOut:
    if await email_taken(db, body.admin_email):
        raise conflict("That admin email is already in use")
    org, admin = await create_org_with_admin(
        db,
        name=body.name,
        admin_name=body.admin_name,
        admin_email=body.admin_email,
        admin_password=body.admin_password,
        status=body.status,
        data_region=body.data_region,
    )
    audit.record(db, p, "org.create", "organization", org.id, {"name": org.name}, org_id=org.id)
    await db.commit()
    return (await _with_counts(db, [org]))[0]


@router.get("/orgs/{org_id}", response_model=PlatformOrgOut)
async def get_org(org_id: UUID, _: PlatformAdmin, db: SystemDB) -> PlatformOrgOut:
    return (await _with_counts(db, [await _get(db, org_id)]))[0]


@router.patch("/orgs/{org_id}", response_model=PlatformOrgOut)
async def update_org(
    org_id: UUID, body: PlatformOrgUpdate, p: PlatformAdmin, db: SystemDB
) -> PlatformOrgOut:
    org = await _get(db, org_id)
    diff = audit.changes(org, body.model_dump(exclude_unset=True))
    if diff:
        audit.record(db, p, "org.platform_update", "organization", org.id, diff, org_id=org.id)
        await db.commit()
    return (await _with_counts(db, [org]))[0]


async def _set_status(org_id: UUID, status: str, p, db) -> PlatformOrgOut:  # noqa: ANN001
    org = await _get(db, org_id)
    old = org.status
    org.status = status
    audit.record(
        db,
        p,
        f"org.{'suspend' if status == 'suspended' else 'reactivate'}",
        "organization",
        org.id,
        {"status": [old, status]},
        org_id=org.id,
    )
    await db.commit()
    return (await _with_counts(db, [org]))[0]


@router.post("/orgs/{org_id}/suspend", response_model=PlatformOrgOut)
async def suspend(org_id: UUID, p: PlatformAdmin, db: SystemDB) -> PlatformOrgOut:
    return await _set_status(org_id, "suspended", p, db)


@router.post("/orgs/{org_id}/reactivate", response_model=PlatformOrgOut)
async def reactivate(org_id: UUID, p: PlatformAdmin, db: SystemDB) -> PlatformOrgOut:
    return await _set_status(org_id, "active", p, db)


@router.get("/stats", response_model=PlatformStats)
async def stats(_: PlatformAdmin, db: SystemDB) -> PlatformStats:
    orgs = (
        await db.execute(select(func.count()).where(Organization.deleted_at.is_(None)))
    ).scalar_one()
    active = (
        await db.execute(
            select(func.count()).where(
                Organization.deleted_at.is_(None), Organization.status != "suspended"
            )
        )
    ).scalar_one()
    users = (
        await db.execute(select(func.count()).select_from(User).where(User.is_active.is_(True)))
    ).scalar_one()
    sites = (
        await db.execute(select(func.count()).select_from(Site).where(Site.is_active.is_(True)))
    ).scalar_one()
    return PlatformStats(orgs=orgs, active_orgs=active, users=users, sites=sites)


@router.get("/whatsapp")
async def whatsapp_health(_: PlatformAdmin, db: SystemDB) -> dict[str, Any]:
    """The shared WhatsApp number: configuration, and the last 24 hours of messages."""
    s = get_settings()
    since = datetime.now(UTC) - timedelta(hours=24)
    by_status = dict(
        (
            await db.execute(
                select(NotificationLog.status, func.count())
                .where(NotificationLog.created_at >= since, NotificationLog.direction == "out")
                .group_by(NotificationLog.status)
            )
        ).all()
    )
    errors = [
        {"template": t, "error": e, "count": n}
        for t, e, n in (
            await db.execute(
                select(NotificationLog.template_key, NotificationLog.error, func.count())
                .where(
                    NotificationLog.created_at >= since,
                    NotificationLog.status.in_(("failed", "skipped")),
                )
                .group_by(NotificationLog.template_key, NotificationLog.error)
                .order_by(func.count().desc())
                .limit(10)
            )
        ).all()
    ]
    opted_out = (
        await db.execute(
            select(func.count())
            .select_from(WhatsAppContact)
            .where(WhatsAppContact.opted_out_at.is_not(None))
        )
    ).scalar_one()
    return {
        "provider": s.whatsapp_provider,
        "phone_number_id": s.whatsapp_phone_number_id or None,
        "webhook_secret_set": bool(s.whatsapp_app_secret),
        "template_prefix": s.whatsapp_template_prefix,
        "last_24h": by_status,
        "top_problems": errors,
        "opted_out": opted_out,
    }
