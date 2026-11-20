"""Setup wizard and checklist (admins)."""

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.deps import AdminUser, TenantDB
from app.models import Organization
from app.notifications import contacts
from app.schemas.common import Phone
from app.services import audit
from app.services import onboarding as svc

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class TestVisitIn(BaseModel):
    phone: Phone | None = None


async def _org(db, org_id) -> Organization:  # noqa: ANN001
    org = await db.get(Organization, org_id)
    assert org is not None
    return org


@router.get("/checklist")
async def get_checklist(p: AdminUser, db: TenantDB) -> dict[str, Any]:
    return await svc.checklist(db, await _org(db, p.org_id))


class StepIn(BaseModel):
    step: Literal["org", "form", "posters"]


@router.post("/complete")
async def complete_step(body: StepIn, p: AdminUser, db: TenantDB) -> dict[str, Any]:
    """Mark a step that can't be worked out from the data as done."""
    org = await _org(db, p.org_id)
    await svc.mark(db, org, body.step)
    await db.commit()
    return await svc.checklist(db, org)


@router.post("/dismiss")
async def dismiss(p: AdminUser, db: TenantDB) -> dict[str, Any]:
    """Hide the checklist from the dashboard."""
    org = await _org(db, p.org_id)
    await svc.mark(db, org, "dismissed")
    await db.commit()
    return await svc.checklist(db, org)


@router.post("/test-visit", status_code=201)
async def send_test_visit(body: TestVisitIn, p: AdminUser, db: TenantDB) -> dict[str, Any]:
    org = await _org(db, p.org_id)
    v, after = await svc.test_visit(db, org, p, body.phone)
    phone = v.visitor_phone
    audit.record(db, p, "onboarding.test_visit", "visit", v.id)
    await db.commit()
    await contacts.opt_in(phone, "setup_test")  # the admin asked for it themself
    await after.run()
    return {"visit_id": str(v.id), "status": v.status}
