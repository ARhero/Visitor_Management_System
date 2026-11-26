from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Query, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import any_, delete, func, literal, or_, select

from app.core.deps import AdminUser, StaffUser, TenantDB
from app.core.errors import AppError, conflict
from app.core.security import hash_password
from app.models import Department, GuardSiteAssignment, Site, User
from app.notifications import contacts
from app.schemas.common import Page
from app.schemas.sites import GuardSitesIn
from app.schemas.users import (
    HostDirectoryEntry,
    ImportResult,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services import audit
from app.services import auth as auth_svc
from app.services.loaders import UserPath, load
from app.services.users_import import TEMPLATE_CSV, run_import

router = APIRouter(tags=["users"])


async def _out(db, users: list[User]) -> list[UserOut]:  # noqa: ANN001
    ids = [u.id for u in users]
    sites: dict[UUID, list[UUID]] = {}
    if ids:
        for uid, sid in (
            await db.execute(
                select(GuardSiteAssignment.user_id, GuardSiteAssignment.site_id).where(
                    GuardSiteAssignment.user_id.in_(ids)
                )
            )
        ).all():
            sites.setdefault(uid, []).append(sid)
    out = []
    for u in users:
        o = UserOut.model_validate(u)
        o.has_password = u.password_hash is not None
        o.site_ids = sites.get(u.id, [])
        out.append(o)
    return out


async def _check_unique(
    db, email: str | None, phone: str | None, exclude: UUID | None = None
) -> None:  # noqa: ANN001
    conds = []
    if email:
        conds.append(func.lower(User.email) == email.lower())
    if phone:
        conds.append(User.phone == phone)
    if not conds:
        return
    q = select(User.email, User.phone).where(or_(*conds))
    if exclude:
        q = q.where(User.id != exclude)
    row = (await db.execute(q)).first()
    if row:
        field = "email" if email and row.email and row.email.lower() == email.lower() else "phone"
        raise conflict(f"Another person already uses this {field}", {"field": field})


async def _check_refs(db, data: dict, user_id: UUID | None = None) -> None:  # noqa: ANN001
    """Referenced rows must exist in *this* org (RLS + composite FKs would also refuse)."""
    if data.get("department_id"):
        await load(db, Department, data["department_id"], "Department")
    if data.get("primary_site_id"):
        await load(db, Site, data["primary_site_id"], "Site")
    if data.get("backup_host_id"):
        if data["backup_host_id"] == user_id:
            raise AppError(422, "validation_error", "A person cannot be their own backup host")
        backup = await load(db, User, data["backup_host_id"], "Backup host")
        if "host" not in backup.roles or not backup.is_active:
            raise AppError(422, "validation_error", "The backup must be an active host")


@router.get("/users", response_model=Page[UserOut])
async def list_users(
    _: AdminUser,
    db: TenantDB,
    q: str | None = None,
    role: str | None = None,
    department_id: UUID | None = None,
    site_id: UUID | None = None,
    include_inactive: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[UserOut]:
    stmt = select(User)
    if not include_inactive:
        stmt = stmt.where(User.is_active.is_(True))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.full_name).like(like),
                func.lower(User.email).like(like),
                User.phone.like(f"%{q.strip()}%"),
                func.lower(User.employee_code).like(like),
            )
        )
    if role:
        stmt = stmt.where(literal(role) == any_(User.roles))
    if department_id:
        stmt = stmt.where(User.department_id == department_id)
    if site_id:
        stmt = stmt.where(User.primary_site_id == site_id)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    users = (
        (await db.execute(stmt.order_by(func.lower(User.full_name)).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    return Page(items=await _out(db, list(users)), total=total, limit=limit, offset=offset)


@router.get("/users/directory", response_model=list[HostDirectoryEntry])
async def host_directory(
    _: StaffUser,
    db: TenantDB,
    q: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[HostDirectoryEntry]:
    """Typeahead for staff (e.g. guards doing a manual check-in). No contact details."""
    like = f"%{q.strip().lower()}%"
    rows = (
        await db.execute(
            select(User, Department.name)
            .outerjoin(Department, Department.id == User.department_id)
            .where(User.is_active.is_(True), literal("host") == any_(User.roles))
            .where(
                or_(func.lower(User.full_name).like(like), func.lower(Department.name).like(like))
            )
            .order_by(func.lower(User.full_name))
            .limit(limit)
        )
    ).all()
    return [
        HostDirectoryEntry(id=u.id, full_name=u.full_name, department=d, designation=u.designation)
        for u, d in rows
    ]


@router.get("/users/import/template.csv")
async def import_template(_: AdminUser) -> Response:
    return Response(
        TEMPLATE_CSV,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="hosts-template.csv"'},
    )


@router.post("/users/import", response_model=ImportResult)
async def import_users(
    p: AdminUser, db: TenantDB, file: Annotated[UploadFile, File()], dry_run: bool = True
) -> ImportResult:
    raw = await file.read(2 * 1024 * 1024 + 1)
    result, touched = await run_import(db, p.org_id, raw, dry_run=dry_run)
    if not result.dry_run:
        audit.record(
            db,
            p,
            "user.import",
            "user",
            None,
            {
                "created": result.created,
                "updated": result.updated,
                "new_departments": result.new_departments,
                "filename": file.filename,
            },
        )
        phones = [u.phone for u in touched]
        await db.commit()
        await contacts.opt_in_many(phones, "added_by_org")
    else:
        await db.rollback()
    return result


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, p: AdminUser, db: TenantDB) -> UserOut:
    data = body.model_dump(exclude={"password"})
    if data.get("email"):
        data["email"] = data["email"].lower()
    await _check_unique(db, data.get("email"), data.get("phone"))
    await _check_refs(db, data)
    user = User(
        org_id=p.org_id,
        **data,
        password_hash=hash_password(body.password) if body.password else None,
    )
    db.add(user)
    await db.flush()
    audit.record(db, p, "user.create", "user", user.id, data)
    phone = user.phone
    await db.commit()
    await contacts.opt_in(phone, "added_by_org")
    return (await _out(db, [user]))[0]


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(_: AdminUser, user: UserPath, db: TenantDB) -> UserOut:
    return (await _out(db, [user]))[0]


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(p: AdminUser, user: UserPath, body: UserUpdate, db: TenantDB) -> UserOut:
    data = body.model_dump(exclude_unset=True, exclude={"password"})
    if data.get("email"):
        data["email"] = data["email"].lower()
    if "roles" in data:
        data["roles"] = sorted(set(data["roles"]))
    await _check_unique(db, data.get("email"), data.get("phone"), exclude=user.id)
    await _check_refs(db, data, user.id)

    roles = data.get("roles", user.roles)
    phone = data.get("phone", user.phone)
    if "host" in roles and not phone:
        raise AppError(422, "validation_error", "Hosts need a mobile number")
    if user.id == p.id and ("org_admin" not in roles or data.get("is_active") is False):
        raise AppError(422, "validation_error", "You cannot remove your own admin access")
    if {"org_admin", "guard"} & set(roles) and not (user.password_hash or body.password):
        raise AppError(
            422, "validation_error", "Set a password before granting admin or guard access"
        )

    diff = audit.changes(user, data)
    # A first password only adds a way to sign in, so current sign-ins (e.g. a host's link)
    # stay; replacing an existing one signs them out, in case the old one leaked.
    replaced_password = bool(body.password and user.password_hash)
    if body.password:
        user.password_hash = hash_password(body.password)
        diff["password"] = ["***" if replaced_password else None, "***"]
    if data.get("is_active") is False or replaced_password or "roles" in diff:
        # Sign the person out everywhere; the new state applies at next login/refresh.
        from app.core.db import system_session

        async with system_session() as s:
            await auth_svc.revoke_all_for_user(s, user.id)
            await s.commit()
    if diff:
        audit.record(db, p, "user.update", "user", user.id, diff)
        await db.commit()
        await db.refresh(user)
    return (await _out(db, [user]))[0]


class SignInLinkOut(BaseModel):
    url: str
    expires_at: datetime
    phone: str | None
    full_name: str


@router.post("/users/{user_id}/sign-in-link", response_model=SignInLinkOut)
async def sign_in_link(p: AdminUser, user: UserPath, db: TenantDB) -> SignInLinkOut:
    """A one-time sign-in link the admin hands over themselves (e.g. from their own
    WhatsApp), for when links can't be sent by the system. Valid for 3 days."""
    from app.api.v1.auth import SHARED_LINK_TTL, login_link

    if not user.is_active:
        raise AppError(422, "validation_error", "This person is deactivated")
    url = login_link(user.org_id, user.id, SHARED_LINK_TTL)
    audit.record(db, p, "user.sign_in_link", "user", user.id)
    await db.commit()
    return SignInLinkOut(
        url=url,
        expires_at=datetime.now(UTC) + SHARED_LINK_TTL,
        phone=user.phone,
        full_name=user.full_name,
    )


@router.delete("/users/{user_id}", status_code=204)
async def deactivate_user(p: AdminUser, user: UserPath, db: TenantDB) -> Response:
    """People are deactivated, not deleted, so visit history stays intact."""
    if user.id == p.id:
        raise AppError(422, "validation_error", "You cannot deactivate yourself")
    user.is_active = False
    audit.record(db, p, "user.deactivate", "user", user.id)
    await db.commit()
    from app.core.db import system_session

    async with system_session() as s:
        await auth_svc.revoke_all_for_user(s, user.id)
        await s.commit()
    return Response(status_code=204)


@router.put("/users/{user_id}/sites", response_model=UserOut)
async def set_guard_sites(
    p: AdminUser, user: UserPath, body: GuardSitesIn, db: TenantDB
) -> UserOut:
    site_ids = list(dict.fromkeys(body.site_ids))
    for sid in site_ids:
        await load(db, Site, sid, "Site")
    await db.execute(delete(GuardSiteAssignment).where(GuardSiteAssignment.user_id == user.id))
    for sid in site_ids:
        db.add(GuardSiteAssignment(org_id=p.org_id, user_id=user.id, site_id=sid))
    audit.record(db, p, "user.set_sites", "user", user.id, {"site_ids": site_ids})
    await db.commit()
    return (await _out(db, [user]))[0]
