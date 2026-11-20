from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Request, Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.ids import uuid7
from app.core.phone import normalize_phone
from app.core.security import (
    create_access_token,
    hash_token,
    new_refresh_token,
    refresh_expiry,
    verify_password,
)
from app.models import Organization, PlatformUser, RefreshToken, User

INVALID = AppError(401, "invalid_credentials", "Incorrect login or password")


def _client(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    return ip, (request.headers.get("user-agent") or "")[:300]


def set_refresh_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        s.refresh_cookie_name,
        token,
        max_age=s.refresh_token_ttl_days * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path="/api/v1/auth",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(get_settings().refresh_cookie_name, path="/api/v1/auth")


def login_key(identifier: str) -> str:
    """Canonical form of a login identifier, so rate limits can't be dodged by reformatting
    a phone number ("98610 00002", "+919861000002", ...)."""
    ident = identifier.strip().lower()
    if "@" not in ident:
        try:
            return normalize_phone(ident)
        except ValueError:
            pass
    return ident


async def find_login_candidates(
    db: AsyncSession, identifier: str, org_slug: str | None
) -> list[tuple[User, Organization]]:
    ident = identifier.strip()
    conds = [func.lower(User.email) == ident.lower()]
    try:
        conds.append(User.phone == normalize_phone(ident))
    except ValueError:
        pass
    q = (
        select(User, Organization)
        .join(Organization, Organization.id == User.org_id)
        .where(or_(*conds), User.is_active.is_(True), User.password_hash.is_not(None))
        .where(Organization.deleted_at.is_(None))
    )
    if org_slug:
        q = q.where(Organization.slug == org_slug)
    return [(u, o) for u, o in (await db.execute(q)).all()]


async def authenticate(
    db: AsyncSession, identifier: str, password: str, org_slug: str | None
) -> User:
    candidates = await find_login_candidates(db, identifier, org_slug)
    matches = [(u, o) for u, o in candidates if verify_password(password, u.password_hash)]
    if not candidates:
        verify_password(password, None)  # constant-ish timing
    if not matches:
        raise INVALID
    if len(matches) > 1:
        raise AppError(
            409,
            "choose_organization",
            "This login belongs to more than one organization",
            details=[{"slug": o.slug, "name": o.name} for _, o in matches],
        )
    user, org = matches[0]
    if org.status == "suspended":
        raise AppError(403, "org_suspended", "This organization is suspended")
    return user


async def issue_tokens(
    db: AsyncSession,
    request: Request,
    *,
    subject_type: str,
    subject_id: UUID,
    org_id: UUID | None,
    roles: list[str],
    family_id: UUID | None = None,
) -> tuple[str, int, str, RefreshToken]:
    ip, ua = _client(request)
    raw = new_refresh_token()
    rt = RefreshToken(
        id=uuid7(),
        subject_type=subject_type,
        subject_id=subject_id,
        org_id=org_id,
        token_hash=hash_token(raw),
        family_id=family_id or uuid7(),
        expires_at=refresh_expiry(),
        ip=ip,
        user_agent=ua,
    )
    db.add(rt)
    access, ttl = create_access_token(
        subject=subject_id,
        scope="platform" if subject_type == "platform" else "org",
        org_id=org_id,
        roles=roles,
    )
    return access, ttl, raw, rt


# Two tabs reloading together (or a retried request) present the same refresh token a
# moment apart. Within this window the second one gets its own new token in the same
# family instead of being treated as theft. A token revoked by signing out
# (no ``replaced_by``) never gets this grace.
REUSE_GRACE = timedelta(seconds=20)


async def rotate(db: AsyncSession, request: Request, raw: str) -> tuple[str, int, str]:
    now = datetime.now(UTC)
    rt = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)).with_for_update()
        )
    ).scalar_one_or_none()
    if rt is None:
        raise AppError(401, "unauthorized", "Session expired")
    benign_race = (
        rt.revoked_at is not None
        and rt.replaced_by is not None
        and now - rt.revoked_at < REUSE_GRACE
    )
    if rt.revoked_at is not None and not benign_race:
        # Reuse of a rotated token: assume theft, kill the whole family.
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == rt.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await db.commit()
        raise AppError(401, "unauthorized", "Session expired")
    if rt.expires_at <= now:
        raise AppError(401, "unauthorized", "Session expired")

    if rt.subject_type == "platform":
        pu = await db.get(PlatformUser, rt.subject_id)
        if not pu or not pu.is_active:
            raise AppError(401, "unauthorized", "Session expired")
        roles = ["super_admin"]
    else:
        row = (
            await db.execute(
                select(User, Organization.status)
                .join(Organization, Organization.id == User.org_id)
                .where(User.id == rt.subject_id)
            )
        ).first()
        if row is None or not row[0].is_active or row[1] == "suspended":
            raise AppError(401, "unauthorized", "Session expired")
        roles = list(row[0].roles)

    access, ttl, new_raw, new_rt = await issue_tokens(
        db,
        request,
        subject_type=rt.subject_type,
        subject_id=rt.subject_id,
        org_id=rt.org_id,
        roles=roles,
        family_id=rt.family_id,
    )
    if not benign_race:
        rt.revoked_at = now
        rt.replaced_by = new_rt.id
    await db.commit()
    return access, ttl, new_raw


async def revoke_family(db: AsyncSession, raw: str) -> None:
    rt = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
    ).scalar_one_or_none()
    if rt:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == rt.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await db.commit()


async def revoke_all_for_user(db: AsyncSession, user_id: UUID) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.subject_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
