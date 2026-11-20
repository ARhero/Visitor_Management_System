import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select

from app.core import rate_limit, tokens
from app.core.config import get_settings
from app.core.deps import CurrentPrincipal, SystemDB
from app.core.errors import AppError, conflict
from app.core.redis import get_redis
from app.core.security import verify_password
from app.models import GuardSiteAssignment, Organization, PlatformUser, User
from app.notifications import contacts, dispatcher
from app.schemas.auth import (
    LoginIn,
    MagicExchangeIn,
    MagicLinkIn,
    MeOut,
    PlatformLoginIn,
    TokenOut,
)
from app.schemas.org import OrgRef, SignupIn
from app.services import auth as svc
from app.services.orgs import create_org_with_admin, email_taken

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, response: Response, db: SystemDB) -> TokenOut:
    s = get_settings()
    ip = request.client.host if request.client else "unknown"
    bucket = f"login:{svc.login_key(body.identifier)}"
    await rate_limit.hit(
        bucket, limit=s.login_rate_limit, window_seconds=s.login_rate_window_seconds
    )
    await rate_limit.hit(
        f"login-ip:{ip}", limit=s.login_rate_limit * 5, window_seconds=s.login_rate_window_seconds
    )

    user = await svc.authenticate(db, body.identifier, body.password, body.org_slug)
    access, ttl, raw, _ = await svc.issue_tokens(
        db, request, subject_type="user", subject_id=user.id, org_id=user.org_id, roles=user.roles
    )
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    await rate_limit.reset(bucket, window_seconds=s.login_rate_window_seconds)
    svc.set_refresh_cookie(response, raw)
    return TokenOut(access_token=access, expires_in=ttl)


MAGIC_TTL = timedelta(minutes=15)
# Links an admin creates and hands over themselves (e.g. from their own WhatsApp).
SHARED_LINK_TTL = timedelta(days=3)


def login_link(org_id: UUID, user_id: UUID, ttl: timedelta = MAGIC_TTL) -> str:
    tok = tokens.sign(
        "login", {"o": str(org_id), "u": str(user_id), "j": secrets.token_urlsafe(9)}, ttl
    )
    return f"{get_settings().public_web_url.rstrip('/')}/m/{tok}"


@router.post("/magic-link", status_code=202)
async def magic_link(body: MagicLinkIn, request: Request, db: SystemDB) -> dict[str, bool]:
    """Sign in without a password: a one-time link on WhatsApp (hosts have no password).
    The answer is the same whether or not the number belongs to anyone."""
    if not get_settings().whatsapp_enabled:
        raise AppError(
            409,
            "whatsapp_off",
            "Sign-in links can't be sent here. Ask your admin for a link, or use a password.",
        )
    ip = request.client.host if request.client else "unknown"
    await rate_limit.hit(f"magic:{body.phone}", limit=3, window_seconds=600)
    await rate_limit.hit(f"magic-ip:{ip}", limit=20, window_seconds=600)
    rows = (
        await db.execute(
            select(User, Organization)
            .join(Organization, Organization.id == User.org_id)
            .where(
                User.phone == body.phone,
                User.is_active.is_(True),
                Organization.status != "suspended",
                Organization.deleted_at.is_(None),
            )
        )
    ).all()
    notes = []
    for user, org in rows:
        notes.append(
            dispatcher.queue(
                db,
                org_id=org.id,
                to=body.phone,
                template="login_link",
                locale=body.locale,
                params={"org": org.name, "link": login_link(org.id, user.id)},
                user_id=user.id,
            )
        )
    await db.commit()
    if notes:
        await contacts.opt_in(body.phone, "login_link")
    await dispatcher.dispatch([n.id for n in notes])
    return {"sent": True}


@router.post("/magic", response_model=TokenOut)
async def magic_exchange(
    body: MagicExchangeIn, request: Request, response: Response, db: SystemDB
) -> TokenOut:
    c = tokens.verify(
        "login", body.token, message="This sign-in link has expired. Please ask for a new one."
    )
    used = await get_redis().set(
        f"magic-used:{c['j']}", 1, nx=True, ex=int(SHARED_LINK_TTL.total_seconds()) + 60
    )
    if not used:
        raise AppError(401, "link_used", "This sign-in link was already used. Ask for a new one.")
    row = (
        await db.execute(
            select(User, Organization.status)
            .join(Organization, Organization.id == User.org_id)
            .where(User.id == c["u"], User.org_id == c["o"])
        )
    ).first()
    if row is None or not row[0].is_active or row[1] == "suspended":
        raise AppError(401, "invalid_token", "This link is not valid")
    user = row[0]
    access, ttl, raw, _ = await svc.issue_tokens(
        db, request, subject_type="user", subject_id=user.id, org_id=user.org_id, roles=user.roles
    )
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    svc.set_refresh_cookie(response, raw)
    return TokenOut(access_token=access, expires_in=ttl)


@router.post("/platform/login", response_model=TokenOut)
async def platform_login(
    body: PlatformLoginIn, request: Request, response: Response, db: SystemDB
) -> TokenOut:
    s = get_settings()
    await rate_limit.hit(
        f"plogin:{body.email.lower()}",
        limit=s.login_rate_limit,
        window_seconds=s.login_rate_window_seconds,
    )
    pu = (
        await db.execute(
            select(PlatformUser).where(func.lower(PlatformUser.email) == body.email.lower())
        )
    ).scalar_one_or_none()
    if (
        not verify_password(body.password, pu.password_hash if pu else None)
        or not pu
        or not pu.is_active
    ):
        raise svc.INVALID
    access, ttl, raw, _ = await svc.issue_tokens(
        db, request, subject_type="platform", subject_id=pu.id, org_id=None, roles=["super_admin"]
    )
    pu.last_login_at = datetime.now(UTC)
    await db.commit()
    svc.set_refresh_cookie(response, raw)
    return TokenOut(access_token=access, expires_in=ttl)


@router.post("/refresh", response_model=TokenOut)
async def refresh(request: Request, response: Response, db: SystemDB) -> TokenOut:
    raw = request.cookies.get(get_settings().refresh_cookie_name)
    if not raw:
        raise AppError(401, "unauthorized", "Not signed in")
    try:
        access, ttl, new_raw = await svc.rotate(db, request, raw)
    except AppError:
        svc.clear_refresh_cookie(response)
        raise
    svc.set_refresh_cookie(response, new_raw)
    return TokenOut(access_token=access, expires_in=ttl)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: SystemDB) -> Response:
    raw = request.cookies.get(get_settings().refresh_cookie_name)
    if raw:
        await svc.revoke_family(db, raw)
    response.status_code = 204
    svc.clear_refresh_cookie(response)
    return response


@router.get("/me", response_model=MeOut)
async def me(p: CurrentPrincipal, db: SystemDB) -> MeOut:
    if p.is_platform:
        pu = await db.get(PlatformUser, p.id)
        assert pu
        return MeOut(
            id=pu.id,
            scope="platform",
            full_name=pu.full_name,
            email=pu.email,
            phone=None,
            roles=["super_admin"],
            org=None,
            site_ids=[],
            whatsapp_enabled=get_settings().whatsapp_enabled,
        )
    user = await db.get(User, p.id)
    org = await db.get(Organization, p.org_id)
    assert user and org
    sites = (
        (
            await db.execute(
                select(GuardSiteAssignment.site_id).where(GuardSiteAssignment.user_id == p.id)
            )
        )
        .scalars()
        .all()
    )
    return MeOut(
        id=user.id,
        scope="org",
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        roles=list(user.roles),
        org=OrgRef(id=org.id, name=org.name, slug=org.slug),
        site_ids=list(sites),
        whatsapp_enabled=get_settings().whatsapp_enabled,
    )


@router.post("/signup", response_model=TokenOut, status_code=201)
async def signup(body: SignupIn, request: Request, response: Response, db: SystemDB) -> TokenOut:
    if not get_settings().allow_signup:
        raise AppError(403, "signup_closed", "New organizations are set up by the administrator.")
    ip = request.client.host if request.client else "unknown"
    await rate_limit.hit(
        f"signup:{ip}", limit=get_settings().signup_rate_limit, window_seconds=3600
    )
    if await email_taken(db, body.email):
        raise conflict("An account with this email already exists. Sign in instead.")
    org, admin = await create_org_with_admin(
        db,
        name=body.org_name,
        admin_name=body.admin_name,
        admin_email=body.email,
        admin_password=body.password,
        admin_phone=body.phone,
    )
    access, ttl, raw, _ = await svc.issue_tokens(
        db, request, subject_type="user", subject_id=admin.id, org_id=org.id, roles=admin.roles
    )
    await db.commit()
    svc.set_refresh_cookie(response, raw)
    return TokenOut(access_token=access, expires_in=ttl)
