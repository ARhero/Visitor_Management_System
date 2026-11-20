from datetime import datetime
from secrets import token_hex
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Query, UploadFile
from sqlalchemy import func, select

from app.core.deps import AdminUser, StaffUser, TenantDB
from app.core.errors import not_found
from app.models import AuditLog, Organization, User
from app.schemas.common import Page
from app.schemas.config import AuditOut
from app.schemas.org import OrgOut, OrgUpdate
from app.services import audit, storage

router = APIRouter(tags=["organization"])


async def _org(db, org_id: UUID) -> Organization:  # noqa: ANN001
    # Explicit filter; RLS on organizations also limits the app role to its own row.
    org = (
        await db.execute(select(Organization).where(Organization.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise not_found("Organization")
    return org


async def org_out(org: Organization) -> OrgOut:
    out = OrgOut.model_validate(org)
    out.logo_url = await storage.signed_url((org.branding or {}).get("logo_key"))
    return out


@router.get("/org", response_model=OrgOut)
async def get_org(p: StaffUser, db: TenantDB) -> OrgOut:
    return await org_out(await _org(db, p.org_id))


@router.patch("/org", response_model=OrgOut)
async def update_org(body: OrgUpdate, p: AdminUser, db: TenantDB) -> OrgOut:
    org = await _org(db, p.org_id)
    data = body.model_dump(exclude_unset=True, mode="json")
    if "branding" in data:  # the logo is only set by uploading one
        data["branding"]["logo_key"] = (org.branding or {}).get("logo_key")
    diff = audit.changes(org, data)
    if diff:
        audit.record(db, p, "org.update", "organization", org.id, diff)
        await db.commit()
        await db.refresh(org)
    return await org_out(org)


@router.post("/org/logo", response_model=OrgOut)
async def upload_logo(p: AdminUser, db: TenantDB, file: Annotated[UploadFile, File()]) -> OrgOut:
    org = await _org(db, p.org_id)
    data = storage.sanitize_logo(await file.read(2 * 1024 * 1024 + 1))
    key = f"orgs/{org.id}/branding/logo-{token_hex(6)}.png"
    await storage.put(key, data, "image/png")
    old = (org.branding or {}).get("logo_key")
    org.branding = {**(org.branding or {}), "logo_key": key}
    audit.record(db, p, "org.logo", "organization", org.id, {"logo_key": [old, key]})
    await db.commit()
    if old:
        await storage.delete(old)
    return await org_out(org)


@router.delete("/org/logo", response_model=OrgOut)
async def remove_logo(p: AdminUser, db: TenantDB) -> OrgOut:
    org = await _org(db, p.org_id)
    old = (org.branding or {}).get("logo_key")
    if old:
        org.branding = {**(org.branding or {}), "logo_key": None}
        audit.record(db, p, "org.logo", "organization", org.id, {"logo_key": [old, None]})
        await db.commit()
        await storage.delete(old)
    return await org_out(org)


@router.get("/audit-logs", response_model=Page[AuditOut])
async def list_audit_logs(
    p: AdminUser,
    db: TenantDB,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AuditOut]:
    q = select(AuditLog).where(AuditLog.org_id == p.org_id)
    if action:
        q = q.where(AuditLog.action.startswith(action))
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    if actor_user_id:
        q = q.where(AuditLog.actor_user_id == actor_user_id)
    if since:
        q = q.where(AuditLog.created_at >= since)
    if until:
        q = q.where(AuditLog.created_at < until)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    ids = {r.actor_user_id for r in rows if r.actor_user_id}
    names = (
        dict((await db.execute(select(User.id, User.full_name).where(User.id.in_(ids)))).all())
        if ids
        else {}
    )
    items = []
    for r in rows:
        out = AuditOut.model_validate(r)
        out.actor_name = names.get(r.actor_user_id) if r.actor_user_id else None
        if out.actor_name is None and r.actor_type == "platform":
            out.actor_name = "VMS support"
        items.append(out)
    return Page(items=items, total=total, limit=limit, offset=offset)
