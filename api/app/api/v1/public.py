"""Public visitor check-in. No staff account involved.

Flow: GET gate → POST otp/send → POST otp/verify (visitor token) → GET hosts,
POST uploads → POST visits (status token) → GET visits/{id} + /events (live) → pass.

The gate token in the poster URL is the only thing a visitor starts with. Every later
call carries a short-lived signed token, and each data call runs in a tenant session
for the gate's org, so RLS applies exactly as for staff.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import any_, func, literal, select

from app.core import rate_limit, tokens
from app.core.config import get_settings
from app.core.db import system_session, tenant_session
from app.core.errors import AppError, not_found
from app.core.i18n import LOCALES
from app.core.redis import get_redis
from app.models import (
    ConsentNotice,
    ConsentRecord,
    CustomField,
    Department,
    Gate,
    Invite,
    InviteGuest,
    Organization,
    Purpose,
    Site,
    User,
    Visit,
    Visitor,
)
from app.notifications import contacts, dispatcher
from app.schemas.visits import (
    GateInfo,
    HostOption,
    OtpSendIn,
    OtpSendOut,
    OtpVerifyIn,
    OtpVerifyOut,
    PassConsentIn,
    PassInfo,
    PassView,
    PublicField,
    PublicNotice,
    PublicPurpose,
    RespondIn,
    UploadOut,
    VisitCreated,
    VisitForHost,
    VisitIn,
    VisitorPrefill,
    VisitStatus,
)
from app.services import consent, otp, passes, realtime, storage
from app.services import invites as invite_svc
from app.services import visits as visit_svc
from app.services.visit_state import FINAL

router = APIRouter(prefix="/public", tags=["public"])
_bearer = HTTPBearer(auto_error=False)
GONE = "This QR code is no longer active. Please ask at reception."


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@dataclass
class GateCtx:
    org: Organization
    site: Site
    gate: Gate


async def _gate(token: str) -> GateCtx:
    async with system_session() as db:
        row = (
            await db.execute(
                select(Gate, Site, Organization)
                .join(Site, Site.id == Gate.site_id)
                .join(Organization, Organization.id == Gate.org_id)
                .where(Gate.qr_token == token)
            )
        ).first()
    if row is None:
        raise AppError(404, "gate_not_found", GONE)
    gate, site, org = row
    if not (gate.is_active and site.is_active) or org.status == "suspended" or org.deleted_at:
        raise AppError(404, "gate_not_found", GONE)
    return GateCtx(org, site, gate)


# ---------- Tokens ----------


@dataclass
class VisitorCtx:
    org_id: UUID
    site_id: UUID
    gate_id: UUID
    phone: str
    verified: bool = True


async def _visitor(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> VisitorCtx:
    if creds is None:
        raise AppError(401, "unauthorized", "Please verify your mobile number first")
    c = tokens.verify(
        "visitor",
        creds.credentials,
        message="Your session expired. Please verify your number again.",
    )
    return VisitorCtx(UUID(c["o"]), UUID(c["s"]), UUID(c["g"]), c["p"], not c.get("u"))


Visitor_ = Annotated[VisitorCtx, Depends(_visitor)]


@dataclass
class VisitTokenCtx:
    org_id: UUID
    visit_id: UUID


async def _visit_token(
    visit_id: UUID,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> VisitTokenCtx:
    if creds is None:
        raise AppError(401, "unauthorized", "Not signed in")
    c = tokens.verify("visit", creds.credentials)
    if UUID(c["v"]) != visit_id:
        raise not_found("Visit")
    return VisitTokenCtx(UUID(c["o"]), visit_id)


VisitToken = Annotated[VisitTokenCtx, Depends(_visit_token)]


# ---------- Gate ----------


@router.get("/features")
async def features() -> dict[str, bool]:
    """What this installation can do (the sign-in page asks before showing options)."""
    s = get_settings()
    return {"whatsapp": s.whatsapp_enabled, "signup": s.allow_signup}


@router.get("/gates/{gate_token}", response_model=GateInfo)
async def gate_info(gate_token: str) -> GateInfo:
    g = await _gate(gate_token)
    settings = g.org.settings or {}
    async with tenant_session(g.org.id) as db:
        purposes = (
            await db.execute(
                select(Purpose).where(Purpose.is_active.is_(True)).order_by(Purpose.sort_order)
            )
        ).scalars()
        fields = (
            await db.execute(
                select(CustomField)
                .where(
                    CustomField.is_active.is_(True),
                    CustomField.applies_to.in_(("checkin", "both")),
                    (CustomField.site_id.is_(None)) | (CustomField.site_id == g.site.id),
                )
                .order_by(CustomField.sort_order)
            )
        ).scalars()
        notices = await consent.current_notices(db, g.org.id)
        return GateInfo(
            org_name=g.org.name,
            branding=g.org.branding or {},
            logo_url=await storage.signed_url((g.org.branding or {}).get("logo_key")),
            privacy_url=consent.privacy_url(g.org),
            locales=settings.get("enabled_locales", list(LOCALES)),
            default_locale=g.org.default_locale,
            require_selfie=settings.get("require_selfie", True),
            id_proof_mode=settings.get("id_proof_mode", "off"),
            site_name=g.site.name,
            site_address=", ".join(x for x in (g.site.address, g.site.city) if x) or None,
            gate_name=g.gate.name,
            verify_phone=visit_svc.phone_check_on(g.org),
            purposes=[
                PublicPurpose(
                    id=p.id,
                    label=p.label,
                    label_i18n=p.label_i18n,
                    requires_id_proof=p.requires_id_proof,
                )
                for p in purposes
            ],
            fields=[
                PublicField(
                    key=f.key,
                    label=f.label,
                    label_i18n=f.label_i18n,
                    help_i18n=f.help_i18n,
                    type=f.type,
                    options=f.options,
                    required=f.required or f.type == "declaration",
                )
                for f in fields
            ],
            notices={
                loc: PublicNotice(id=n.id, version=n.version, body=consent.render(n.body, g.org))
                for loc, n in notices.items()
            },
        )


# ---------- OTP ----------


@router.post("/otp/send", response_model=OtpSendOut, status_code=202)
async def otp_send(body: OtpSendIn, request: Request) -> OtpSendOut:
    g = await _gate(body.gate_token)
    if not visit_svc.phone_check_on(g.org):
        raise AppError(409, "otp_off", "Codes are not used here. Please continue without one.")
    code = await otp.issue(g.org.id, g.gate.id, body.phone, _ip(request))
    async with tenant_session(g.org.id) as db:
        note = dispatcher.queue(
            db,
            org_id=g.org.id,
            to=body.phone,
            template="otp",
            locale=body.locale,
            params={"code": code, "org": g.org.name},
        )
        await db.commit()
    await contacts.opt_in(body.phone, "visitor_otp")
    await dispatcher.dispatch([note.id])
    s = get_settings()
    masked = body.phone[:3] + " " + "•" * 6 + body.phone[-4:]
    return OtpSendOut(
        sent_to=masked, resend_after=s.otp_resend_seconds, expires_in=s.otp_ttl_seconds
    )


@router.post("/start", response_model=OtpVerifyOut)
async def start_without_code(body: OtpSendIn, request: Request) -> OtpVerifyOut:
    """Check in without a WhatsApp code (when the org or the platform has codes off).
    The number is only what the visitor typed: the visit is marked unverified for the
    guard, and nothing stored about the number (name, photo, last host) is returned."""
    g = await _gate(body.gate_token)
    if visit_svc.phone_check_on(g.org):
        raise AppError(409, "otp_required", "Please verify your number with a code.")
    await rate_limit.hit(f"start-ip:{_ip(request)}", limit=30, window_seconds=600)
    await rate_limit.hit(f"start-gate:{g.gate.id}", limit=300, window_seconds=600)
    ttl = timedelta(minutes=get_settings().visitor_token_ttl_minutes)
    token = tokens.sign(
        "visitor",
        {"o": str(g.org.id), "s": str(g.site.id), "g": str(g.gate.id), "p": body.phone, "u": 1},
        ttl,
    )
    return OtpVerifyOut(token=token, expires_in=int(ttl.total_seconds()), returning=None)


@router.post("/otp/verify", response_model=OtpVerifyOut)
async def otp_verify(body: OtpVerifyIn, request: Request) -> OtpVerifyOut:
    g = await _gate(body.gate_token)
    await rate_limit.hit(f"otp-verify-ip:{_ip(request)}", limit=60, window_seconds=600)
    await otp.check(g.org.id, body.phone, body.code)
    s = get_settings()
    ttl = timedelta(minutes=s.visitor_token_ttl_minutes)
    token = tokens.sign(
        "visitor",
        {"o": str(g.org.id), "s": str(g.site.id), "g": str(g.gate.id), "p": body.phone},
        ttl,
    )
    prefill = None
    async with tenant_session(g.org.id) as db:
        v = (
            await db.execute(select(Visitor).where(Visitor.phone == body.phone))
        ).scalar_one_or_none()
        if v and v.anonymized_at is None:
            last = (
                await db.execute(
                    select(User, Department.name)
                    .join(Visit, Visit.host_id == User.id)
                    .outerjoin(Department, Department.id == User.department_id)
                    .where(
                        Visit.visitor_id == v.id,
                        User.is_active.is_(True),
                        literal("host") == any_(User.roles),
                    )
                    .order_by(Visit.requested_at.desc())
                    .limit(1)
                )
            ).first()
            prefill = VisitorPrefill(
                full_name=v.full_name,
                company=v.company,
                email=v.email,
                has_photo=bool(v.last_photo_key),
                last_host=HostOption(
                    id=last[0].id,
                    full_name=last[0].full_name,
                    department=last[1],
                    designation=last[0].designation,
                )
                if last
                else None,
            )
    return OtpVerifyOut(token=token, expires_in=int(ttl.total_seconds()), returning=prefill)


# ---------- During check-in (visitor token) ----------


@router.get("/hosts", response_model=list[HostOption])
async def search_hosts(ctx: Visitor_, q: str = "") -> list[HostOption]:
    """Typeahead. Needs a verified phone and at least 2 letters, returns at most 8 names
    and never phone numbers, so the staff list can't be scraped."""
    q = q.strip()
    if len(q) < 2:
        return []
    await rate_limit.hit(f"hosts:{ctx.phone}", limit=120, window_seconds=600)
    like = f"%{q.lower().replace('%', '').replace('_', '')}%"
    async with tenant_session(ctx.org_id) as db:
        rows = (
            await db.execute(
                select(User, Department.name)
                .outerjoin(Department, Department.id == User.department_id)
                .where(
                    User.is_active.is_(True),
                    literal("host") == any_(User.roles),
                    func.lower(User.full_name).like(like),
                )
                .order_by((User.primary_site_id == ctx.site_id).desc().nulls_last(), User.full_name)
                .limit(8)
            )
        ).all()
    return [
        HostOption(id=u.id, full_name=u.full_name, department=d, designation=u.designation)
        for u, d in rows
    ]


@router.post("/uploads", response_model=UploadOut, status_code=201)
async def upload(
    ctx: Visitor_,
    file: Annotated[UploadFile, File()],
    kind: Annotated[Literal["selfie", "id"], Form()] = "selfie",
) -> UploadOut:
    await rate_limit.hit(f"upload:{ctx.phone}", limit=20, window_seconds=600)
    raw = await file.read(storage.MAX_UPLOAD_BYTES + 1)
    data = storage.sanitize_image(raw, 640 if kind == "selfie" else 1280)
    now = datetime.now(UTC)
    key = f"orgs/{ctx.org_id}/{kind}/{now:%Y/%m}/{uuid4().hex}.webp"
    await storage.put(key, data)
    tok = tokens.sign(
        "upload",
        {"o": str(ctx.org_id), "p": ctx.phone, "k": key, "kind": kind},
        timedelta(minutes=60),
    )
    return UploadOut(upload_token=tok)


def _upload_key(token: str | None, ctx: VisitorCtx, kind: str) -> str | None:
    if not token:
        return None
    c = tokens.verify("upload", token, message="The photo upload expired. Please take it again.")
    if c["o"] != str(ctx.org_id) or c["p"] != ctx.phone or c["kind"] != kind:
        raise AppError(422, "bad_upload", "Please take the photo again")
    return c["k"]


@router.post("/visits", response_model=VisitCreated, status_code=201)
async def submit_visit(
    body: VisitIn, ctx: Visitor_, request: Request, response: Response
) -> VisitCreated:
    await rate_limit.hit(f"submit:{ctx.phone}", limit=10, window_seconds=600)
    photo = _upload_key(body.photo_upload, ctx, "selfie")
    id_image = _upload_key(body.id_upload, ctx, "id")
    async with system_session() as sdb:
        org = await sdb.get(Organization, ctx.org_id)
        site = await sdb.get(Site, ctx.site_id)
        gate = await sdb.get(Gate, ctx.gate_id)
    if (
        not (org and site and gate and site.is_active and gate.is_active)
        or org.status == "suspended"
    ):
        raise AppError(404, "gate_not_found", GONE)
    async with tenant_session(ctx.org_id) as db:
        v, after, created = await visit_svc.create(
            db,
            org=org,
            site=site,
            gate=gate,
            phone=ctx.phone,
            body=body,
            photo_key=photo,
            id_image_key=id_image,
            ip=_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:300],
            phone_verified=ctx.verified,
        )
        await db.commit()
    await after.run()
    if visit_svc.blocked(v):
        raise AppError(403, "checkin_blocked", "Please speak to the security desk at the gate.")
    if not created:
        response.status_code = 200
    return VisitCreated(visit_id=v.id, status=v.status, status_token=visit_svc.status_token(v))


# ---------- After submitting (visit token) ----------


async def _status(org_id: UUID, visit_id: UUID) -> VisitStatus:
    async with tenant_session(org_id) as db:
        row = (
            await db.execute(
                select(Visit, User.full_name, Site.name, Gate.name)
                .join(User, User.id == Visit.host_id)
                .join(Site, Site.id == Visit.site_id)
                .outerjoin(Gate, Gate.id == Visit.gate_id)
                .where(Visit.id == visit_id)
            )
        ).first()
    if row is None:
        raise not_found("Visit")
    v, host, site, gate = row
    tok = visit_svc.pass_token(v)
    return VisitStatus(
        id=v.id,
        status=v.status,
        visitor_name=v.visitor_name,
        host_name=host,
        site_name=site,
        gate_name=gate,
        host_message=v.host_message,
        requested_at=v.requested_at,
        responded_at=v.responded_at,
        valid_until=v.valid_until,
        escalated=v.escalation_level > 0,
        pass_=PassInfo(token=tok, url=passes.pass_url(tok)) if tok else None,
        whatsapp=get_settings().whatsapp_enabled,
    )


@router.get("/visits/{visit_id}", response_model=VisitStatus)
async def visit_status(ctx: VisitToken) -> VisitStatus:
    return await _status(ctx.org_id, ctx.visit_id)


@router.get("/visits/{visit_id}/events")
async def visit_events(ctx: VisitToken, request: Request) -> StreamingResponse:
    """Server-sent events: the current status right away, then again on every change.
    Ends when the visit is final; clients reconnect (and fall back to polling)."""

    async def stream() -> AsyncIterator[str]:
        pubsub = get_redis().pubsub()
        await pubsub.subscribe(realtime.visit_channel(ctx.visit_id))
        try:
            last = None
            deadline = asyncio.get_event_loop().time() + 15 * 60
            while asyncio.get_event_loop().time() < deadline:
                try:
                    st = await _status(ctx.org_id, ctx.visit_id)
                except AppError:
                    return  # gone (e.g. erased) mid-stream: the response has started, just end
                if st.status != last:
                    last = st.status
                    yield f"event: status\ndata: {st.model_dump_json(by_alias=True)}\n\n"
                if st.status in FINAL or st.status == "checked_in":
                    return
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
                if msg is None:
                    yield ": ping\n\n"
                if await request.is_disconnected():
                    return
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/visits/{visit_id}/cancel", response_model=VisitStatus)
async def cancel_visit(ctx: VisitToken) -> VisitStatus:
    async with tenant_session(ctx.org_id) as db:
        _, after = await visit_svc.cancel_by_visitor(db, ctx.visit_id)
        await db.commit()
    await after.run()
    return await _status(ctx.org_id, ctx.visit_id)


# ---------- Host's WhatsApp link ----------


async def _respond_ctx(token: str) -> tuple[UUID, UUID, UUID]:
    c = tokens.verify("respond", token, message="This request has closed")
    return UUID(c["o"]), UUID(c["v"]), UUID(c["u"])


async def visit_for_host(db, v: Visit, user_id: UUID) -> VisitForHost:  # noqa: ANN001
    site = await db.get(Site, v.site_id)
    gate = await db.get(Gate, v.gate_id) if v.gate_id else None
    host = await db.get(User, v.host_id)
    purpose = await db.get(Purpose, v.purpose_id) if v.purpose_id else None
    return VisitForHost(
        id=v.id,
        status=v.status,
        visitor_name=v.visitor_name,
        visitor_company=v.visitor_company,
        visitor_phone=v.visitor_phone,
        photo_url=await storage.signed_url(v.photo_key),
        purpose=purpose.label if purpose else None,
        purpose_i18n=purpose.label_i18n if purpose else {},
        purpose_note=v.purpose_note,
        accompanying_count=v.accompanying_count,
        vehicle_number=v.vehicle_number,
        custom_values=v.custom_values,
        id_type=v.id_type,
        id_last4=v.id_last4,
        site_name=site.name if site else "",
        gate_name=gate.name if gate else None,
        host_name=host.full_name if host else "",
        requested_at=v.requested_at,
        responded_at=v.responded_at,
        host_message=v.host_message,
        can_respond=v.status in ("pending", "waiting")
        and (user_id == v.host_id or user_id in (v.notified_approver_ids or [])),
        source=v.source,
        checked_in_at=v.checked_in_at,
        checked_out_at=v.checked_out_at,
    )


@router.get("/respond/{token}", response_model=VisitForHost)
async def respond_view(token: str) -> VisitForHost:
    org_id, visit_id, user_id = await _respond_ctx(token)
    async with tenant_session(org_id) as db:
        v = await db.get(Visit, visit_id)
        if v is None:
            raise not_found("Visit")
        return await visit_for_host(db, v, user_id)


@router.post("/respond/{token}", response_model=VisitForHost)
async def respond_action(token: str, body: RespondIn) -> VisitForHost:
    org_id, visit_id, user_id = await _respond_ctx(token)
    async with tenant_session(org_id) as db:
        org = await db.get(Organization, org_id)
        user = await db.get(User, user_id)
        if org is None or user is None or not user.is_active:
            raise AppError(401, "invalid_token", "This link is not valid")
        _, after = await visit_svc.respond(
            db, org, visit_id, user, body.action, body.message, "web"
        )
        await db.commit()
    await after.run()
    async with tenant_session(org_id) as db:
        v = await db.get(Visit, visit_id)
        assert v is not None
        return await visit_for_host(db, v, user_id)


# ---------- Pass ----------


@router.get("/passes/{token}", response_model=PassView)
async def pass_view(token: str) -> PassView:
    claims = passes.read(token)
    async with system_session() as db:
        row = (
            await db.execute(
                select(Visit, Organization, Site, User.full_name)
                .join(Organization, Organization.id == Visit.org_id)
                .join(Site, Site.id == Visit.site_id)
                .join(User, User.id == Visit.host_id)
                .where(Visit.pass_jti == claims["jti"])
            )
        ).first()
    if row is None:
        return await _invite_pass(token, claims)
    v, org, site, host = row
    state: str
    if v.status == "approved":
        state = "expired" if claims["expired"] else "valid"
    elif v.status == "checked_in":
        state = "checked_in"
    elif v.status == "checked_out":
        state = "used"
    elif v.status == "expired":
        state = "expired"
    else:
        state = "revoked"
    show_qr = state in ("valid", "checked_in")
    return PassView(
        state=state,  # type: ignore[arg-type]
        status=v.status,
        org_name=org.name,
        branding=org.branding or {},
        visitor_name=v.visitor_name,
        visitor_company=v.visitor_company,
        photo_url=await storage.signed_url(v.photo_key),
        host_name=host,
        site_name=site.name,
        site_address=", ".join(x for x in (site.address, site.city, site.pincode) if x) or None,
        directions=site.directions_text,
        map_url=site.map_url,
        accompanying_count=v.accompanying_count,
        valid_until=v.valid_until,
        qr_svg=passes.qr_svg(token) if show_qr else None,
    )


# ---------- Invite passes (pre-approved guests) ----------


async def _guest_by_jti(jti: str) -> tuple[InviteGuest, Invite, Organization]:
    async with system_session() as db:
        row = (
            await db.execute(
                select(InviteGuest, Invite, Organization)
                .join(Invite, Invite.id == InviteGuest.invite_id)
                .join(Organization, Organization.id == InviteGuest.org_id)
                .where(InviteGuest.pass_jti == jti)
            )
        ).first()
    if row is None:
        raise AppError(404, "invalid_pass", "This pass is not valid")
    return row[0], row[1], row[2]


async def _invite_pass(token: str, claims: dict) -> PassView:
    guest, invite, org = await _guest_by_jti(claims["jti"])
    settings = org.settings or {}
    async with tenant_session(org.id) as db:
        site = await db.get(Site, invite.site_id)
        host = await db.get(User, invite.host_id)
        assert site and host
        t = datetime.now(UTC)
        today = await invite_svc.todays_visit(db, guest, t)
        problem = invite_svc.problem(invite, guest, invite.site_id, t)
        state: str
        if today and today.status == "checked_in":
            state = "checked_in"
        elif problem == "revoked":
            state = "revoked"
        elif problem == "expired" or claims["expired"]:
            state = "expired"
        elif problem == "used":
            state = "used"
        elif problem in ("not_yet", "outside_hours") or (today and today.status == "checked_out"):
            state = "not_yet"  # multi-day: come back in the window / on the next day
        else:
            state = "valid"
        visitor = await db.get(Visitor, guest.visitor_id) if guest.visitor_id else None
        needs = guest.consented_at is None and state not in ("revoked", "expired", "used")
        notices = None
        if needs:
            notices = {
                loc: PublicNotice(id=n.id, version=n.version, body=consent.render(n.body, org))
                for loc, n in (await consent.current_notices(db, org.id)).items()
            }
        show_qr = not needs and state in ("valid", "not_yet", "checked_in")
        return PassView(
            state=state,  # type: ignore[arg-type]
            kind="invite",
            status=today.status if today else "approved",
            org_name=org.name,
            branding=org.branding or {},
            visitor_name=guest.name,
            visitor_company=guest.company,
            photo_url=await storage.signed_url(visitor.last_photo_key) if visitor else None,
            host_name=host.full_name,
            site_name=site.name,
            site_address=", ".join(x for x in (site.address, site.city, site.pincode) if x) or None,
            directions=site.directions_text,
            map_url=site.map_url,
            accompanying_count=0,
            valid_until=invite.valid_until,
            qr_svg=passes.qr_svg(token) if show_qr else None,
            title=invite.title,
            valid_from=invite.valid_from,
            daily_start_time=invite.daily_start_time,
            daily_end_time=invite.daily_end_time,
            needs_consent=needs,
            notices=notices,
            locales=settings.get("enabled_locales", list(LOCALES)),
        )


@router.post("/passes/{token}/consent", response_model=PassView)
async def pass_consent(token: str, body: PassConsentIn, request: Request) -> PassView:
    """An invited guest accepts the privacy notice; then their pass QR is shown."""
    claims = passes.read(token)
    guest, _, org = await _guest_by_jti(claims["jti"])
    async with tenant_session(org.id) as db:
        notice = await db.get(ConsentNotice, body.notice_id)
        if notice is None or not notice.is_current:
            raise AppError(
                409, "notice_changed", "The privacy notice was updated. Please review it again."
            )
        g = await db.get(InviteGuest, guest.id)
        assert g is not None
        if g.consented_at is None and g.visitor_id:
            t = datetime.now(UTC)
            db.add(
                ConsentRecord(
                    org_id=org.id,
                    visitor_id=g.visitor_id,
                    notice_id=notice.id,
                    locale=body.locale,
                    consented_at=t,
                    ip=_ip(request),
                    user_agent=(request.headers.get("user-agent") or "")[:300],
                )
            )
            g.consented_at = t
            visitor = await db.get(Visitor, g.visitor_id)
            if visitor:
                visitor.preferred_locale = body.locale
            await db.commit()
    return await _invite_pass(token, claims)


# ---------- Media (local storage backend only) ----------


@router.get("/media/{token}", include_in_schema=False)
async def media(token: str) -> Response:
    data = await storage.read_local(token)
    return Response(
        data, media_type="image/webp", headers={"Cache-Control": "private, max-age=300"}
    )
