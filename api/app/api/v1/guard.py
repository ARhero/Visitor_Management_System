"""Guard console: the queue at a site, scanning passes, walk-ins, check-in/out.

Guards see only their assigned sites (admins see all). Check-in and check-out need an
``Idempotency-Key`` so retries and offline replays never act twice.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.core import idempotency, rate_limit, tokens
from app.core.config import get_settings
from app.core.db import tenant_session
from app.core.deps import Principal, TenantDB, require_roles
from app.core.errors import AppError, not_found
from app.core.i18n import Locale
from app.core.redis import get_redis
from app.models import (
    ConsentRecord,
    CustomField,
    Gate,
    Invite,
    Organization,
    Purpose,
    Site,
    Visit,
)
from app.notifications import contacts, dispatcher
from app.schemas.guard import (
    CheckInIn,
    CheckOutIn,
    GuardCard,
    GuardForm,
    GuardOtpIn,
    GuardQueue,
    GuardSite,
    OfflinePack,
    PassCheckInIn,
    ScanIn,
    ScanOut,
    WalkInIn,
)
from app.schemas.visits import OtpSendOut, UploadOut
from app.services import consent, otp, realtime, storage
from app.services import guard as svc
from app.services import visits as visit_svc
from app.services.loaders import GuestPath
from app.services.visits import AfterCommit

router = APIRouter(prefix="/guard", tags=["guard"])
GuardUser = Annotated[Principal, Depends(require_roles("guard", "org_admin"))]


async def _org(db, p: Principal) -> Organization:  # noqa: ANN001
    org = await db.get(Organization, p.org_id)
    assert org is not None
    return org


async def _visit(visit_id: UUID, p: GuardUser, db: TenantDB) -> Visit:
    return await svc.require_visit(db, p, visit_id)


GuardVisit = Annotated[Visit, Depends(_visit)]


@router.get("/sites", response_model=list[GuardSite])
async def my_sites(p: GuardUser, db: TenantDB) -> list[GuardSite]:
    allowed = await svc.site_ids(db, p)
    q = select(Site).where(Site.is_active.is_(True)).order_by(Site.name)
    if allowed is not None:
        q = q.where(Site.id.in_(allowed))
    sites = list((await db.execute(q)).scalars())
    gates = (
        await db.execute(
            select(Gate)
            .where(Gate.site_id.in_([s.id for s in sites]), Gate.is_active.is_(True))
            .order_by(Gate.name)
        )
    ).scalars()
    by_site: dict[UUID, list[dict[str, str]]] = {}
    for g in gates:
        by_site.setdefault(g.site_id, []).append({"id": str(g.id), "name": g.name})
    return [
        GuardSite(id=s.id, name=s.name, city=s.city, gates=by_site.get(s.id, [])) for s in sites
    ]


@router.get("/form", response_model=GuardForm)
async def walk_in_form(p: GuardUser, db: TenantDB, site_id: Annotated[UUID, Query()]) -> GuardForm:
    site = await svc.require_site(db, p, site_id)
    org = await _org(db, p)
    settings = org.settings or {}
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
                (CustomField.site_id.is_(None)) | (CustomField.site_id == site.id),
            )
            .order_by(CustomField.sort_order)
        )
    ).scalars()
    notices = await consent.current_notices(db, org.id)
    return GuardForm(
        require_selfie=settings.get("require_selfie", True),
        id_proof_mode=settings.get("id_proof_mode", "off"),
        otp_required=get_settings().whatsapp_enabled
        and bool(settings.get("guard_manual_requires_otp", False)),
        purposes=[
            {
                "id": str(x.id),
                "label": x.label,
                "label_i18n": x.label_i18n,
                "requires_id_proof": x.requires_id_proof,
            }
            for x in purposes
        ],
        fields=[
            {
                "key": f.key,
                "label": f.label,
                "label_i18n": f.label_i18n,
                "type": f.type,
                "options": f.options,
                "required": f.required or f.type == "declaration",
            }
            for f in fields
        ],
        notices={
            loc: {
                "id": str(n.id),
                "version": n.version,
                "body": consent.render(n.body, org),
            }
            for loc, n in notices.items()
        },
    )


@router.get("/queue", response_model=GuardQueue)
async def site_queue(p: GuardUser, db: TenantDB, site_id: Annotated[UUID, Query()]) -> GuardQueue:
    await svc.require_site(db, p, site_id)
    return await svc.queue(db, site_id)


@router.get("/stream")
async def site_stream(
    p: GuardUser, request: Request, site_id: Annotated[UUID, Query()]
) -> StreamingResponse:
    """SSE: a ``change`` event whenever a visit at this site changes. The console then
    refetches the queue. Pings every 15 s; the server ends the stream after 30 minutes
    and the client reconnects."""
    async with tenant_session(p.org_id) as db:  # type: ignore[arg-type]
        await svc.require_site(db, p, site_id)

    async def stream() -> AsyncIterator[str]:
        pubsub = get_redis().pubsub()
        await pubsub.subscribe(realtime.site_channel(site_id))
        try:
            yield "event: ready\ndata: {}\n\n"
            deadline = asyncio.get_event_loop().time() + 30 * 60
            while asyncio.get_event_loop().time() < deadline:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
                if msg is None:
                    yield ": ping\n\n"
                else:
                    data = msg["data"]
                    text = data if isinstance(data, str) else data.decode()
                    yield f"event: change\ndata: {text}\n\n"
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


@router.post("/scan", response_model=ScanOut)
async def scan(body: ScanIn, p: GuardUser, db: TenantDB) -> ScanOut:
    await rate_limit.hit(f"scan:{p.id}", limit=120, window_seconds=60)
    site = await svc.require_site(db, p, body.site_id)
    out, after = await svc.scan(db, await _org(db, p), site, body.payload, p.id)
    await db.commit()
    await after.run()
    return out


@router.get("/offline-pack", response_model=OfflinePack)
async def offline_pack(site_id: UUID, p: GuardUser, db: TenantDB) -> OfflinePack:
    """Today's expected passes at the site plus the pass-signing public key, so the
    console can check passes when the connection drops. Refreshed every minute."""
    await rate_limit.hit(f"offline-pack:{p.id}", limit=30, window_seconds=60)
    site = await svc.require_site(db, p, site_id)
    return await svc.offline_pack(db, site)


@router.post("/pass-check-in", response_model=ScanOut)
async def pass_check_in(body: PassCheckInIn, p: GuardUser, db: TenantDB, request: Request) -> dict:
    """Scan and check in at once: how a check-in made offline is sent when the
    connection is back (with its Idempotency-Key and the time of the tap)."""

    async def act() -> dict:
        site = await svc.require_site(db, p, body.site_id)
        out, after = await svc.pass_check_in(
            db, await _org(db, p), site, body.payload, p, body.occurred_at
        )
        await db.commit()
        await after.run()
        return out.model_dump(mode="json")

    return await idempotency.run(request, f"{p.org_id}:{p.id}", act)


class ArriveIn(BaseModel):
    site_id: UUID
    # The guard showed the privacy notice to a guest who never opened their pass.
    consent: bool = False
    locale: Locale = "en"


@router.post("/invite-guests/{guest_id}/arrive", response_model=ScanOut)
async def guest_arrives(guest: GuestPath, body: ArriveIn, p: GuardUser, db: TenantDB) -> ScanOut:
    """Picked from "expected today" (no QR): same checks as scanning their pass."""
    invite = await db.get(Invite, guest.invite_id)
    assert invite is not None
    allowed = await svc.site_ids(db, p)
    if allowed is not None and invite.site_id not in allowed:
        raise not_found("Guest")
    site = await svc.require_site(db, p, body.site_id)
    org = await _org(db, p)
    if guest.consented_at is None:
        if not body.consent:
            raise AppError(409, "consent_required", "Show the guest the privacy notice and confirm")
        notices = await consent.current_notices(db, org.id)
        notice = notices.get(body.locale) or notices.get("en")
        if notice and guest.visitor_id:
            db.add(
                ConsentRecord(
                    org_id=org.id,
                    visitor_id=guest.visitor_id,
                    notice_id=notice.id,
                    locale=body.locale,
                    consented_at=datetime.now(UTC),
                    ip=None,
                    user_agent=f"guard:{p.id}",
                )
            )
        guest.consented_at = datetime.now(UTC)
    problem, visit, after = await svc.invite_svc.arrive(db, org, invite, guest, site.id, p.id)
    g = await svc.expected_guest(db, invite, guest)
    c = await svc.card(db, visit) if visit else None
    await db.commit()
    await after.run()
    if problem:
        other = await db.get(Site, invite.site_id) if problem == "wrong_site" else None
        return ScanOut(
            result=problem,
            message=svc.MESSAGES[problem],
            visit=c,
            guest=g,  # type: ignore[arg-type]
            site_name=other.name if other else None,
        )
    assert visit is not None
    res = "inside" if visit.status == "checked_in" else "ok"
    return ScanOut(result=res, message=svc.MESSAGES[res], visit=c, guest=g)


@router.get("/visits/{visit_id}", response_model=GuardCard)
async def get_visit(visit: GuardVisit, db: TenantDB) -> GuardCard:
    return await svc.card(db, visit)


@router.post("/visits/{visit_id}/check-in", response_model=GuardCard)
async def check_in(
    visit: GuardVisit, body: CheckInIn, p: GuardUser, db: TenantDB, request: Request
) -> dict:
    async def act() -> dict:
        org = await _org(db, p)
        v, after = await svc.check_in(db, org, visit.id, p, body.occurred_at, body.override_reason)
        c = await svc.card(db, v)
        await db.commit()
        await after.run()
        return c.model_dump(mode="json")

    return await idempotency.run(request, f"{p.org_id}:{p.id}", act)


@router.post("/visits/{visit_id}/check-out", response_model=GuardCard)
async def check_out(
    visit: GuardVisit, body: CheckOutIn, p: GuardUser, db: TenantDB, request: Request
) -> dict:
    async def act() -> dict:
        v, after = await svc.check_out(db, visit.id, p, body.occurred_at)
        c = await svc.card(db, v)
        await db.commit()
        await after.run()
        return c.model_dump(mode="json")

    return await idempotency.run(request, f"{p.org_id}:{p.id}", act)


@router.post("/visits/{visit_id}/notify-host", response_model=GuardCard)
async def notify_host(visit: GuardVisit, p: GuardUser, db: TenantDB) -> GuardCard:
    await rate_limit.hit(f"remind:{visit.id}", limit=1, window_seconds=60)
    after = await svc.remind_host(db, await _org(db, p), visit)
    await db.commit()
    await after.run()
    return await svc.card(db, visit)


# ---------- Walk-in ----------


@router.post("/otp/send", response_model=OtpSendOut, status_code=202)
async def walk_in_otp(body: GuardOtpIn, p: GuardUser, db: TenantDB, request: Request) -> OtpSendOut:
    await svc.require_site(db, p, body.site_id)
    org = await _org(db, p)
    ip = request.client.host if request.client else "unknown"
    code = await otp.issue(org.id, body.site_id, body.phone, ip)
    note = dispatcher.queue(
        db,
        org_id=org.id,
        to=body.phone,
        template="otp",
        locale=body.locale,
        params={"code": code, "org": org.name},
    )
    await db.commit()
    await contacts.opt_in(body.phone, "visitor_otp")
    await dispatcher.dispatch([note.id])

    s = get_settings()
    return OtpSendOut(
        sent_to=body.phone[:3] + " " + "•" * 6 + body.phone[-4:],
        resend_after=s.otp_resend_seconds,
        expires_in=s.otp_ttl_seconds,
    )


@router.post("/uploads", response_model=UploadOut, status_code=201)
async def walk_in_photo(
    p: GuardUser,
    file: Annotated[UploadFile, File()],
    kind: Annotated[Literal["selfie"], Form()] = "selfie",
) -> UploadOut:
    await rate_limit.hit(f"guard-upload:{p.id}", limit=60, window_seconds=600)
    raw = await file.read(storage.MAX_UPLOAD_BYTES + 1)
    data = storage.sanitize_image(raw, 640)
    key = f"orgs/{p.org_id}/{kind}/{datetime.now(UTC):%Y/%m}/{uuid4().hex}.webp"
    await storage.put(key, data)
    tok = tokens.sign(
        "upload",
        {"o": str(p.org_id), "p": f"guard:{p.id}", "k": key, "kind": kind},
        timedelta(minutes=60),
    )
    return UploadOut(upload_token=tok)


@router.post("/visits", response_model=GuardCard, status_code=201)
async def walk_in(body: WalkInIn, p: GuardUser, db: TenantDB, request: Request) -> GuardCard:
    site = await svc.require_site(db, p, body.site_id)
    gate = None
    if body.gate_id:
        gate = (
            await db.execute(select(Gate).where(Gate.id == body.gate_id, Gate.site_id == site.id))
        ).scalar_one_or_none()
        if gate is None:
            raise AppError(422, "invalid_gate", "Choose a gate at this site")
    org = await _org(db, p)
    if get_settings().whatsapp_enabled and (org.settings or {}).get("guard_manual_requires_otp"):
        if not body.otp_code:
            raise AppError(422, "otp_required", "Enter the code sent to the visitor's phone")
        await otp.check(org.id, body.phone, body.otp_code)
    if body.admit and not body.override_reason:
        raise AppError(422, "reason_required", "Say why you are letting them in without the host")

    photo = None
    if body.photo_upload:
        c = tokens.verify("upload", body.photo_upload, message="The photo expired. Take it again.")
        if c["o"] != str(org.id) or c["p"] != f"guard:{p.id}":
            raise AppError(422, "bad_upload", "Please take the photo again")
        photo = c["k"]

    v, after, _ = await visit_svc.create(
        db,
        org=org,
        site=site,
        gate=gate,
        phone=body.phone,
        body=body,
        photo_key=photo,
        id_image_key=None,
        ip=request.client.host if request.client else None,
        user_agent=f"guard:{p.id}",
        source="guard_manual",
        actor_type="guard",
        actor_id=p.id,
        ask_host=not body.admit,
    )
    if visit_svc.blocked(v):
        await db.commit()
        await after.run()
        from app.models import BlacklistEntry

        hit = await db.get(BlacklistEntry, v.blacklist_hit_id)
        raise AppError(
            403,
            "blocked",
            svc.MESSAGES["blocked"],
            {"reason": hit.reason if hit else None, "visit_id": str(v.id)},
        )
    if body.admit and v.status in ("pending", "waiting", "approved"):
        v, more = await svc.check_in(db, org, v.id, p, None, body.override_reason)
        after = AfterCommit(notes=after.notes + more.notes, visits=[v])
    c = await svc.card(db, v)
    await db.commit()
    await after.run()
    return c
