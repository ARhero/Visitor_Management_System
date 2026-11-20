"""Live dashboard (admins) and the evacuation list (admins, and guards for their sites)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.core import rate_limit, tokens
from app.core.config import get_settings
from app.core.db import tenant_session
from app.core.deps import AdminUser, Principal, TenantDB, require_roles
from app.core.errors import AppError
from app.core.redis import get_redis
from app.models import Organization, Site
from app.notifications import dispatcher
from app.notifications.templates import render
from app.schemas.reports import Evacuation, Live
from app.services import audit, exports, realtime, reports
from app.services import guard as guard_svc
from app.services.pdf import ist

router = APIRouter(tags=["dashboard"])
SafetyUser = Annotated[Principal, Depends(require_roles("org_admin", "guard"))]
EVAC_LINK_TTL = timedelta(hours=6)


async def _site(db, site_id: UUID | None) -> None:  # noqa: ANN001
    if site_id and not (await db.execute(select(Site.id).where(Site.id == site_id))).first():
        raise AppError(404, "not_found", "Site not found")


@router.get("/dashboard/live", response_model=Live)
async def live(_: AdminUser, db: TenantDB, site_id: UUID | None = None) -> Live:
    await _site(db, site_id)
    return await reports.live(db, site_id)


@router.get("/dashboard/stream")
async def stream(p: AdminUser, request: Request) -> StreamingResponse:
    """SSE: a ``change`` event (debounce on the client) whenever any visit changes."""

    async def gen() -> AsyncIterator[str]:
        pubsub = get_redis().pubsub()
        await pubsub.subscribe(realtime.org_channel(p.org_id))  # type: ignore[arg-type]
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
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- Evacuation ----------


async def _evac_sites(db, p: Principal, site_id: UUID | None) -> list[UUID] | None:  # noqa: ANN001
    """Admins: one site or all. Guards: one of their sites, or all of theirs."""
    allowed = await guard_svc.site_ids(db, p)
    if site_id:
        await guard_svc.require_site(db, p, site_id)
        return [site_id]
    return allowed


@router.get("/evacuation", response_model=Evacuation)
async def evacuation(p: SafetyUser, db: TenantDB, site_id: UUID | None = None) -> Evacuation:
    return await exports.evacuation(db, await _evac_sites(db, p, site_id))


@router.get("/evacuation.pdf")
async def evacuation_pdf(p: SafetyUser, db: TenantDB, site_id: UUID | None = None) -> Response:
    ev = await exports.evacuation(db, await _evac_sites(db, p, site_id))
    org = await db.get(Organization, p.org_id)
    assert org is not None
    audit.record(db, p, "evacuation.download", "site", site_id, {"visits": ev.visits})
    await db.commit()
    return _pdf_response(exports.evacuation_pdf(org, ev), ev)


PDF_LINK_TTL = timedelta(minutes=10)


class PdfLinkIn(BaseModel):
    site_id: UUID | None = None


@router.post("/evacuation/pdf-link")
async def evacuation_pdf_link(body: PdfLinkIn, p: SafetyUser, db: TenantDB) -> dict[str, str]:
    """A short-lived address of the PDF that opens without signing in, for phones: a
    browser opened from WhatsApp, for one, can't save a file the page downloads itself,
    but it can open a PDF at an address."""
    sites = await _evac_sites(db, p, body.site_id)
    tok = tokens.sign(
        "evacpdf",
        {"o": str(p.org_id), "s": [str(x) for x in sites] if sites is not None else None},
        PDF_LINK_TTL,
    )
    audit.record(db, p, "evacuation.download", "site", body.site_id, {"via": "link"})
    await db.commit()
    return {"url": f"/api/v1/public/evacuation-pdf/{tok}"}


def _pdf_response(data: bytes, ev: Evacuation) -> Response:
    name = f"evacuation-{ev.at.astimezone(exports.IST):%Y%m%d-%H%M}.pdf"
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}"', "Cache-Control": "no-store"},
    )


class ShareIn(BaseModel):
    site_id: UUID


@router.post("/evacuation/share")
async def share(body: ShareIn, p: SafetyUser, db: TenantDB) -> dict[str, int | str]:
    """WhatsApp the site's safety contacts: the head count and a link to the live list
    (valid for a few hours, works without signing in).

    With WhatsApp off nothing is sent: the message comes back as ``share_text`` for the
    person to send from their own WhatsApp (e.g. to a safety group)."""
    site = await guard_svc.require_site(db, p, body.site_id)
    contacts = list(site.safety_contacts or [])
    whatsapp = get_settings().whatsapp_enabled
    if whatsapp and not contacts:
        raise AppError(
            409, "no_contacts", "Add safety contacts for this site first (Sites & gates)"
        )
    await rate_limit.hit(f"evac-share:{site.id}", limit=3, window_seconds=600)
    org = await db.get(Organization, p.org_id)
    assert org is not None
    ev = await exports.evacuation(db, [site.id])
    tok = tokens.sign("evac", {"o": str(org.id), "s": str(site.id)}, EVAC_LINK_TTL)
    # A web page, not the PDF itself: a phone browser opened from WhatsApp often can't
    # show or save a PDF, but every one can show a page (which links to the PDF).
    link = f"{get_settings().public_web_url.rstrip('/')}/e/{tok}"
    params = {
        "site": site.name,
        "time": ist(ev.at, "%I:%M %p"),
        "visits": ev.visits,
        "people": ev.people,
        "link": link,
        "by": p.full_name,
    }
    if not whatsapp:
        audit.record(db, p, "evacuation.share", "site", site.id, {"by_hand": True})
        await db.commit()
        return {
            "sent": 0,
            "visits": ev.visits,
            "people": ev.people,
            "share_text": render("evacuation", org.default_locale, params),
        }
    notes = [
        dispatcher.queue(
            db,
            org_id=org.id,
            to=c["phone"],
            template="evacuation",
            locale=org.default_locale,
            params=params,
        )
        for c in contacts
    ]
    audit.record(
        db, p, "evacuation.share", "site", site.id, {"contacts": len(contacts), "visits": ev.visits}
    )
    await db.commit()
    await dispatcher.dispatch([n.id for n in notes])
    return {"sent": len(notes), "visits": ev.visits, "people": ev.people}


public_router = APIRouter(prefix="/public", tags=["public"])


async def _shared_evacuation(token: str) -> tuple[Organization, Evacuation]:
    c = tokens.verify("evac", token, message="This evacuation link has expired")
    org_id, site_id = UUID(c["o"]), UUID(c["s"])
    async with tenant_session(org_id) as db:
        org = await db.get(Organization, org_id)
        if org is None or org.status == "suspended":
            raise AppError(404, "not_found", "Not found")
        return org, await exports.evacuation(db, [site_id])


@public_router.get("/evacuation/{token}")
async def evacuation_link(token: str) -> Response:
    """The PDF of a shared evacuation list, as it is right now."""
    org, ev = await _shared_evacuation(token)
    return _pdf_response(exports.evacuation_pdf(org, ev), ev)


class SharedEvacuation(Evacuation):
    org_name: str


@public_router.get("/evacuation/{token}/data", response_model=SharedEvacuation)
async def evacuation_link_data(token: str) -> SharedEvacuation:
    """The shared list for the web page at /e/<token> (the link in the WhatsApp message)."""
    org, ev = await _shared_evacuation(token)
    return SharedEvacuation(**ev.model_dump(), org_name=org.name)


@public_router.get("/evacuation-pdf/{token}")
async def evacuation_pdf_by_link(token: str) -> Response:
    """The PDF behind ``/evacuation/pdf-link`` (valid for 10 minutes)."""
    c = tokens.verify("evacpdf", token, message="This link has expired. Tap the button again.")
    org_id = UUID(c["o"])
    sites = [UUID(x) for x in c["s"]] if c.get("s") is not None else None
    async with tenant_session(org_id) as db:
        org = await db.get(Organization, org_id)
        if org is None or org.status == "suspended":
            raise AppError(404, "not_found", "Not found")
        ev = await exports.evacuation(db, sites)
        return _pdf_response(exports.evacuation_pdf(org, ev), ev)
