"""Request-scoped dependencies: who is calling, which org, which DB session."""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import system_session, tenant_session
from app.core.errors import AppError, forbidden
from app.core.security import decode_access_token
from app.models import Organization, PlatformUser, User

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    id: UUID
    scope: str  # "org" | "platform"
    org_id: UUID | None
    roles: frozenset[str] = field(default_factory=frozenset)
    full_name: str = ""
    ip: str | None = None
    user_agent: str | None = None

    @property
    def is_platform(self) -> bool:
        return self.scope == "platform"

    def has(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))


def _unauthorized(msg: str = "Not signed in") -> AppError:
    return AppError(401, "unauthorized", msg, headers={"WWW-Authenticate": "Bearer"})


async def get_principal(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if creds is None:
        raise _unauthorized()
    try:
        claims = decode_access_token(creds.credentials)
    except jwt.PyJWTError as exc:
        raise _unauthorized("Session expired or invalid") from exc

    sub = UUID(claims["sub"])
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "")[:300]

    # Re-check the account on every request so deactivation / suspension is immediate.
    async with system_session() as s:
        if claims.get("scope") == "platform":
            pu = await s.get(PlatformUser, sub)
            if not pu or not pu.is_active:
                raise _unauthorized()
            return Principal(
                sub, "platform", None, frozenset({"super_admin"}), pu.full_name, ip, ua
            )

        org_id = UUID(claims["org"])
        row = (
            await s.execute(
                select(User, Organization.status)
                .join(Organization, Organization.id == User.org_id)
                .where(User.id == sub, User.org_id == org_id)
            )
        ).first()
    if row is None:
        raise _unauthorized()
    user, org_status = row
    if not user.is_active:
        raise _unauthorized("Account is deactivated")
    if org_status == "suspended":
        raise AppError(403, "org_suspended", "This organization is suspended")
    return Principal(sub, "org", org_id, frozenset(user.roles), user.full_name, ip, ua)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_roles(*roles: str) -> Callable[..., Principal]:
    async def _dep(p: CurrentPrincipal) -> Principal:
        if p.is_platform or not p.has(*roles):
            raise forbidden()
        return p

    return _dep


async def require_platform(p: CurrentPrincipal) -> Principal:
    if not p.is_platform:
        raise forbidden()
    return p


async def get_tenant_db(p: CurrentPrincipal) -> AsyncIterator[AsyncSession]:
    if p.org_id is None:
        raise forbidden("This endpoint needs an organization account")
    async with tenant_session(p.org_id) as s:
        yield s


async def get_system_db() -> AsyncIterator[AsyncSession]:
    async with system_session() as s:
        yield s


TenantDB = Annotated[AsyncSession, Depends(get_tenant_db)]
SystemDB = Annotated[AsyncSession, Depends(get_system_db)]
AdminUser = Annotated[Principal, Depends(require_roles("org_admin"))]
StaffUser = Annotated[Principal, Depends(require_roles("org_admin", "guard", "host"))]
PlatformAdmin = Annotated[Principal, Depends(require_platform)]
