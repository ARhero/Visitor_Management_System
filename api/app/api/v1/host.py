"""Hosts answering visitors from the web app (same service as the WhatsApp buttons)."""

from fastapi import APIRouter
from sqlalchemy import select

from app.api.v1.public import visit_for_host
from app.core.deps import StaffUser, TenantDB
from app.core.errors import forbidden, not_found
from app.models import Organization, User, Visit
from app.schemas.visits import RespondIn, VisitForHost
from app.services import visits as visit_svc
from app.services.loaders import VisitPath

router = APIRouter(prefix="/host", tags=["host"])


@router.get("/visits", response_model=list[VisitForHost])
async def my_open_visits(p: StaffUser, db: TenantDB) -> list[VisitForHost]:
    """Visitors waiting for my answer (including ones escalated to me as backup)."""
    return [await visit_for_host(db, v, p.id) for v in await visit_svc.open_visits_for(db, p.id)]


@router.get("/visits/today", response_model=list[VisitForHost])
async def my_visits_today(p: StaffUser, db: TenantDB) -> list[VisitForHost]:
    """Everyone who came (or asked) to see me today, newest first."""
    from app.services.invites import today_start
    from app.services.visits import now

    rows = (
        await db.execute(
            select(Visit)
            .where(
                Visit.host_id == p.id,
                Visit.requested_at >= today_start(now()),
                # Blacklist-blocked attempts: the host was never asked, so don't show
                # them as "declined" (admins and guards see them).
                ~((Visit.status == "rejected") & Visit.responded_by.is_(None)),
            )
            .order_by(Visit.requested_at.desc())
            .limit(100)
        )
    ).scalars()
    return [await visit_for_host(db, v, p.id) for v in rows]


@router.post("/visits/{visit_id}/respond", response_model=VisitForHost)
async def respond(visit: VisitPath, body: RespondIn, p: StaffUser, db: TenantDB) -> VisitForHost:
    if not p.has("host"):
        raise forbidden()
    org = await db.get(Organization, p.org_id)
    user = await db.get(User, p.id)
    if org is None or user is None:
        raise not_found("Visit")
    v, after = await visit_svc.respond(db, org, visit.id, user, body.action, body.message, "web")
    await db.commit()
    await after.run()
    v = (await db.execute(select(Visit).where(Visit.id == v.id))).scalar_one()
    return await visit_for_host(db, v, p.id)
