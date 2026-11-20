"""DPDP tools.

Admins (``/privacy``): retention status, look up / download / erase one person's data,
erasure requests from visitors, and the privacy notice (versioned).

Visitors (``/public/privacy/{slug}``): verify their number with a WhatsApp OTP, then see
and download what the org holds about them and ask for it to be erased.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.core import rate_limit, tokens
from app.core.config import get_settings
from app.core.db import system_session, tenant_session
from app.core.deps import AdminUser, TenantDB
from app.core.errors import AppError, not_found
from app.models import ConsentNotice, ConsentRecord, Organization, PrivacyRequest, User, Visit
from app.notifications import contacts, dispatcher
from app.schemas.common import Phone
from app.schemas.privacy import (
    EraseIn,
    EraseOut,
    ErasureRequestIn,
    MyData,
    NoticeIn,
    NoticeOut,
    PrivacyOtpIn,
    PrivacyOverview,
    PrivacyPage,
    PrivacyRequestOut,
    PrivacyToken,
    PrivacyVerifyIn,
    RejectIn,
    ResolveIn,
    RetentionStatus,
)
from app.services import audit, consent, otp, privacy, storage
from app.services.privacy import ACTIVE, mask, phone_hash

router = APIRouter(prefix="/privacy", tags=["privacy"])
public_router = APIRouter(prefix="/public/privacy", tags=["public"])

TOKEN_TTL = timedelta(minutes=20)


async def _org(db, org_id: UUID) -> Organization:  # noqa: ANN001
    org = await db.get(Organization, org_id)
    assert org is not None
    return org


def _zip(data: bytes, phone: str) -> Response:
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="visitor-data-{phone[-4:]}-{stamp}.zip"',
            "Cache-Control": "no-store",
        },
    )


async def _request_out(db, rows: list[PrivacyRequest]) -> list[PrivacyRequestOut]:  # noqa: ANN001
    users = {
        u.id: u.full_name
        for u in (
            await db.execute(
                select(User).where(User.id.in_({r.resolved_by for r in rows if r.resolved_by}))
            )
        ).scalars()
    }
    phones = [r.phone for r in rows if r.phone]
    counts: dict[str, tuple[int, bool]] = {}
    if phones:
        for ph, n, active in (
            await db.execute(
                select(
                    Visit.visitor_phone,
                    func.count(),
                    func.bool_or(Visit.status.in_(ACTIVE)),
                )
                .where(Visit.visitor_phone.in_(phones))
                .group_by(Visit.visitor_phone)
            )
        ).all():
            counts[ph] = (n, bool(active))
    return [
        PrivacyRequestOut(
            id=r.id,
            kind=r.kind,
            phone=r.phone,
            phone_masked=r.phone_masked,
            name=r.name,
            reason=r.reason,
            status=r.status,
            resolution_note=r.resolution_note,
            resolved_at=r.resolved_at,
            resolved_by_name=users.get(r.resolved_by) if r.resolved_by else None,
            created_at=r.created_at,
            visits=counts.get(r.phone or "", (0, False))[0],
            active_visit=counts.get(r.phone or "", (0, False))[1],
        )
        for r in rows
    ]


# ---------- Admin ----------


@router.get("/overview", response_model=PrivacyOverview)
async def overview(p: AdminUser, db: TenantDB) -> PrivacyOverview:
    org = await _org(db, p.org_id)
    n = (
        await db.execute(
            select(func.count()).select_from(PrivacyRequest).where(PrivacyRequest.status == "open")
        )
    ).scalar_one()
    return PrivacyOverview(
        retention=RetentionStatus(**await privacy.retention_status(db, org)),
        open_requests=n,
        privacy_url=consent.privacy_url(org),
        privacy_contact=(org.settings or {}).get("privacy_contact"),
    )


@router.post("/retention/run", response_model=EraseOut)
async def run_retention(p: AdminUser, db: TenantDB) -> EraseOut:
    """Run the retention job for this org now (it also runs by itself every 6 hours)."""
    await rate_limit.hit(f"retention-run:{p.org_id}", limit=5, window_seconds=600)
    counts = await privacy.retention_run(p.org_id)
    audit.record(db, p, "retention.run", "organization", p.org_id, counts)
    await db.commit()
    return EraseOut(**counts)


@router.get("/lookup")
async def lookup(p: AdminUser, db: TenantDB, phone: Annotated[Phone, Query()]) -> dict:
    org = await _org(db, p.org_id)
    data = await privacy.collect(db, org, phone, for_admin=True)
    audit.record(db, p, "privacy.lookup", "visitor", None, {"phone": mask(phone)})
    await db.commit()
    return data


@router.get("/export")
async def export(p: AdminUser, db: TenantDB, phone: Annotated[Phone, Query()]) -> Response:
    org = await _org(db, p.org_id)
    data = await privacy.export_zip(db, org, phone, for_admin=True)
    audit.record(db, p, "privacy.export", "visitor", None, {"phone": mask(phone)})
    await db.commit()
    return _zip(data, phone)


async def _erase(db, p, org: Organization, phone: str, note: str | None) -> privacy.Result:  # noqa: ANN001
    res = await privacy.erase(db, org, phone)
    audit.record(
        db,
        p,
        "privacy.erase",
        "visitor",
        None,
        {"phone": mask(phone), **res.counts(), "note": note},
    )
    return res


@router.post("/erase", response_model=EraseOut)
async def erase(body: EraseIn, p: AdminUser, db: TenantDB) -> EraseOut:
    if body.phone != body.confirm_phone:
        raise AppError(422, "confirm_mismatch", "The two numbers don't match")
    org = await _org(db, p.org_id)
    res = await _erase(db, p, org, body.phone, body.note)
    # Close any open request from the same person.
    await db.execute(
        update(PrivacyRequest)
        .where(
            PrivacyRequest.status == "open",
            PrivacyRequest.phone_hash == phone_hash(org.id, body.phone),
        )
        .values(
            status="completed",
            phone=None,
            resolved_at=datetime.now(UTC),
            resolved_by=p.id,
            resolution_note=body.note or "Erased from the privacy tools",
        )
    )
    await db.commit()
    res.files = await privacy.delete_files(res.keys)
    res.keys = set()
    return EraseOut(**res.counts())


@router.get("/requests", response_model=list[PrivacyRequestOut])
async def list_requests(
    p: AdminUser,  # noqa: ARG001
    db: TenantDB,
    status: Annotated[str | None, Query(pattern="^(open|completed|rejected)$")] = None,
) -> list[PrivacyRequestOut]:
    q = select(PrivacyRequest).order_by(PrivacyRequest.created_at.desc()).limit(200)
    if status:
        q = q.where(PrivacyRequest.status == status)
    return await _request_out(db, list((await db.execute(q)).scalars()))


async def _open_request(db, request_id: UUID) -> PrivacyRequest:  # noqa: ANN001
    r = (
        await db.execute(
            select(PrivacyRequest).where(
                PrivacyRequest.id == request_id, PrivacyRequest.org_id == db.info["org_id"]
            )
        )
    ).scalar_one_or_none()
    if r is None:
        raise not_found("Request")
    if r.status != "open":
        raise AppError(409, "already_resolved", "This request has already been handled")
    return r


async def _request(request_id: UUID, db: TenantDB) -> PrivacyRequest:
    return await _open_request(db, request_id)


RequestPath = Annotated[PrivacyRequest, Depends(_request)]


@router.post("/requests/{request_id}/erase", response_model=PrivacyRequestOut)
async def resolve_erase(
    r: RequestPath, body: ResolveIn, p: AdminUser, db: TenantDB
) -> PrivacyRequestOut:
    org = await _org(db, p.org_id)
    phone = r.phone or ""
    res = await _erase(db, p, org, phone, body.note)
    note = dispatcher.queue(
        db,
        org_id=org.id,
        to=phone,
        template="privacy_erased",
        locale=r.locale,
        params={"org": org.name},
    )
    r.status, r.phone, r.name = "completed", None, None
    r.resolved_at, r.resolved_by, r.resolution_note = datetime.now(UTC), p.id, body.note
    await db.commit()
    await privacy.delete_files(res.keys)
    await dispatcher.dispatch([note.id])
    return (await _request_out(db, [r]))[0]


@router.post("/requests/{request_id}/reject", response_model=PrivacyRequestOut)
async def resolve_reject(
    r: RequestPath, body: RejectIn, p: AdminUser, db: TenantDB
) -> PrivacyRequestOut:
    org = await _org(db, p.org_id)
    note = dispatcher.queue(
        db,
        org_id=org.id,
        to=r.phone or "",
        template="privacy_rejected",
        locale=r.locale,
        params={
            "org": org.name,
            "note": body.note.rstrip(".") + ".",
            "contact": (org.settings or {}).get("privacy_contact") or "",
        },
    )
    audit.record(
        db,
        p,
        "privacy.reject",
        "privacy_request",
        r.id,
        {"phone": r.phone_masked, "note": body.note},
    )
    r.status, r.phone = "rejected", None
    r.resolved_at, r.resolved_by, r.resolution_note = datetime.now(UTC), p.id, body.note
    await db.commit()
    await dispatcher.dispatch([note.id])
    return (await _request_out(db, [r]))[0]


@router.get("/notices", response_model=list[NoticeOut])
async def list_notices(p: AdminUser, db: TenantDB) -> list[NoticeOut]:
    org = await _org(db, p.org_id)
    counts = dict(
        (
            await db.execute(
                select(ConsentRecord.notice_id, func.count()).group_by(ConsentRecord.notice_id)
            )
        ).all()
    )
    rows = (
        await db.execute(
            select(ConsentNotice).order_by(ConsentNotice.locale, ConsentNotice.version.desc())
        )
    ).scalars()
    return [
        NoticeOut(
            id=n.id,
            locale=n.locale,
            version=n.version,
            body=n.body,
            preview=consent.render(n.body, org),
            is_current=n.is_current,
            published_at=n.published_at,
            acceptances=counts.get(n.id, 0),
        )
        for n in rows
    ]


@router.post("/notices", response_model=NoticeOut, status_code=201)
async def publish_notice(body: NoticeIn, p: AdminUser, db: TenantDB) -> NoticeOut:
    """Publish a new version. Earlier versions stay, so every acceptance still points
    at the exact text the visitor saw."""
    org = await _org(db, p.org_id)
    current = (
        await db.execute(
            select(ConsentNotice)
            .where(ConsentNotice.locale == body.locale, ConsentNotice.is_current.is_(True))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if current and current.body.strip() == body.body.strip():
        raise AppError(422, "unchanged", "This is the same as the current notice")
    top = (
        await db.execute(
            select(func.max(ConsentNotice.version)).where(ConsentNotice.locale == body.locale)
        )
    ).scalar_one()
    if current:
        current.is_current = False
        await db.flush()
    n = ConsentNotice(
        org_id=org.id,
        version=(top or 0) + 1,
        locale=body.locale,
        body=body.body.strip(),
        is_current=True,
        published_at=datetime.now(UTC),
    )
    db.add(n)
    await db.flush()
    audit.record(
        db, p, "notice.publish", "consent_notice", n.id, {"locale": n.locale, "version": n.version}
    )
    await db.commit()
    return NoticeOut(
        id=n.id,
        locale=n.locale,
        version=n.version,
        body=n.body,
        preview=consent.render(n.body, org),
        is_current=True,
        published_at=n.published_at,
        acceptances=0,
    )


# ---------- Visitor self-service ----------

_bearer = HTTPBearer(auto_error=False)


async def _org_by_slug(slug: str) -> Organization:
    # A suspended org still holds visitors' data, so their rights to see, download and
    # ask for erasure stay available; only deleted orgs are gone.
    async with system_session() as db:
        org = (
            await db.execute(
                select(Organization).where(
                    Organization.slug == slug, Organization.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
    if org is None:
        raise not_found("Organization")
    return org


async def _me(
    slug: str, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> tuple[Organization, str]:
    if creds is None:
        raise AppError(401, "unauthorized", "Please verify your mobile number first")
    c = tokens.verify(
        "privacy", creds.credentials, message="Your session expired. Please verify again."
    )
    org = await _org_by_slug(slug)
    if c["o"] != str(org.id):
        raise AppError(401, "unauthorized", "Please verify your mobile number again")
    return org, c["p"]


Me = Annotated[tuple[Organization, str], Depends(_me)]


@public_router.get("/{slug}", response_model=PrivacyPage)
async def privacy_page(slug: str) -> PrivacyPage:
    org = await _org_by_slug(slug)
    async with tenant_session(org.id) as db:
        notices = await consent.current_notices(db, org.id)
    branding = org.branding or {}
    return PrivacyPage(
        org_name=org.name,
        logo_url=await storage.signed_url(branding.get("logo_key")),
        primary_color=branding.get("primary_color", "#0F4C5C"),
        retention_days=int((org.settings or {}).get("retention_days", 90)),
        privacy_contact=(org.settings or {}).get("privacy_contact"),
        notices={loc: consent.render(n.body, org) for loc, n in notices.items()},
        self_serve=get_settings().whatsapp_enabled,
    )


@public_router.post("/{slug}/otp/send", status_code=202)
async def privacy_otp(slug: str, body: PrivacyOtpIn, request: Request) -> dict[str, int | str]:
    org = await _org_by_slug(slug)
    if not get_settings().whatsapp_enabled:
        raise AppError(409, "whatsapp_off", "Please contact the organization about your data.")
    ip = request.client.host if request.client else "unknown"
    code = await otp.issue(org.id, org.id, body.phone, ip, purpose="privacy")
    async with tenant_session(org.id) as db:
        note = dispatcher.queue(
            db,
            org_id=org.id,
            to=body.phone,
            template="otp",
            locale=body.locale,
            params={"code": code, "org": org.name},
        )
        await db.commit()
    await contacts.opt_in(body.phone, "privacy_otp")
    await dispatcher.dispatch([note.id])
    return {"sent_to": mask(body.phone), "expires_in": 300}


@public_router.post("/{slug}/otp/verify", response_model=PrivacyToken)
async def privacy_verify(slug: str, body: PrivacyVerifyIn, request: Request) -> PrivacyToken:
    org = await _org_by_slug(slug)
    ip = request.client.host if request.client else "unknown"
    await rate_limit.hit(f"privacy-verify-ip:{ip}", limit=30, window_seconds=600)
    await otp.check(org.id, body.phone, body.code, purpose="privacy")
    tok = tokens.sign("privacy", {"o": str(org.id), "p": body.phone}, TOKEN_TTL)
    return PrivacyToken(token=tok, expires_in=int(TOKEN_TTL.total_seconds()))


async def _open_for(db, org_id: UUID, phone: str) -> PrivacyRequest | None:  # noqa: ANN001
    return (
        await db.execute(
            select(PrivacyRequest).where(
                PrivacyRequest.status == "open",
                PrivacyRequest.phone_hash == phone_hash(org_id, phone),
            )
        )
    ).scalar_one_or_none()


@public_router.get("/{slug}/me", response_model=MyData)
async def my_data(me: Me) -> MyData:
    org, phone = me
    async with tenant_session(org.id) as db:
        data = await privacy.collect(db, org, phone, for_admin=False)
        r = await _open_for(db, org.id, phone)
        out = (await _request_out(db, [r]))[0] if r else None
    return MyData(data=data, open_request=out)


@public_router.get("/{slug}/me/export")
async def my_export(me: Me) -> Response:
    org, phone = me
    await rate_limit.hit(f"privacy-export:{phone}", limit=5, window_seconds=3600)
    async with tenant_session(org.id) as db:
        data = await privacy.export_zip(db, org, phone, for_admin=False)
    return _zip(data, phone)


@public_router.post("/{slug}/me/erasure", response_model=PrivacyRequestOut, status_code=201)
async def request_erasure(body: ErasureRequestIn, me: Me) -> PrivacyRequestOut:
    org, phone = me
    async with tenant_session(org.id) as db:
        if existing := await _open_for(db, org.id, phone):
            return (await _request_out(db, [existing]))[0]
        data = await privacy.collect(db, org, phone, for_admin=False)
        if not data["visitor"] and not data["visits"] and not data["invitations"]:
            raise AppError(404, "no_data", "We don't hold any visitor data for this number")
        name = (data["visitor"] or {}).get("name") or next(
            (v["name"] for v in data["visits"] if v["name"]), None
        )
        r = PrivacyRequest(
            org_id=org.id,
            kind="erasure",
            phone=phone,
            phone_masked=mask(phone),
            phone_hash=phone_hash(org.id, phone),
            name=name,
            reason=body.reason,
            locale=body.locale,
            status="open",
        )
        db.add(r)
        try:
            await db.commit()
        except IntegrityError:  # two taps at once: the other one won
            await db.rollback()
            existing = await _open_for(db, org.id, phone)
            assert existing is not None
            return (await _request_out(db, [existing]))[0]
        return (await _request_out(db, [r]))[0]
