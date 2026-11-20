"""Resource loaders used as FastAPI dependencies.

Loading a path resource in a dependency means a wrong-org or unknown ID returns
404 *before* body validation runs, which keeps behaviour uniform and lets the
tenancy test matrix probe every route without crafting bodies.
"""

from typing import Annotated, TypeVar
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select

from app.core.deps import TenantDB
from app.core.errors import not_found
from app.models import (
    BlacklistEntry,
    CustomField,
    Department,
    Gate,
    Invite,
    InviteGuest,
    Purpose,
    Site,
    User,
    Visit,
)
from app.models.base import Base

M = TypeVar("M", bound=Base)


async def load(db, model: type[M], obj_id: UUID, what: str) -> M:  # noqa: ANN001
    # Explicit org filter (layer 1); RLS (layer 2) would also hide it.
    org_id = db.info["org_id"]
    obj = (
        await db.execute(select(model).where(model.id == obj_id, model.org_id == org_id))
    ).scalar_one_or_none()
    if obj is None:
        raise not_found(what)
    return obj


async def _site(site_id: UUID, db: TenantDB) -> Site:
    return await load(db, Site, site_id, "Site")


async def _gate(gate_id: UUID, db: TenantDB) -> Gate:
    return await load(db, Gate, gate_id, "Gate")


async def _department(department_id: UUID, db: TenantDB) -> Department:
    return await load(db, Department, department_id, "Department")


async def _user(user_id: UUID, db: TenantDB) -> User:
    return await load(db, User, user_id, "User")


async def _purpose(purpose_id: UUID, db: TenantDB) -> Purpose:
    return await load(db, Purpose, purpose_id, "Purpose")


async def _field(field_id: UUID, db: TenantDB) -> CustomField:
    return await load(db, CustomField, field_id, "Custom field")


async def _visit(visit_id: UUID, db: TenantDB) -> Visit:
    return await load(db, Visit, visit_id, "Visit")


SitePath = Annotated[Site, Depends(_site)]
GatePath = Annotated[Gate, Depends(_gate)]
DepartmentPath = Annotated[Department, Depends(_department)]
UserPath = Annotated[User, Depends(_user)]
PurposePath = Annotated[Purpose, Depends(_purpose)]
FieldPath = Annotated[CustomField, Depends(_field)]
VisitPath = Annotated[Visit, Depends(_visit)]


async def _invite(invite_id: UUID, db: TenantDB) -> Invite:
    return await load(db, Invite, invite_id, "Invite")


async def _guest(guest_id: UUID, db: TenantDB) -> InviteGuest:
    return await load(db, InviteGuest, guest_id, "Guest")


async def _entry(entry_id: UUID, db: TenantDB) -> BlacklistEntry:
    return await load(db, BlacklistEntry, entry_id, "Entry")


InvitePath = Annotated[Invite, Depends(_invite)]
GuestPath = Annotated[InviteGuest, Depends(_guest)]
EntryPath = Annotated[BlacklistEntry, Depends(_entry)]
