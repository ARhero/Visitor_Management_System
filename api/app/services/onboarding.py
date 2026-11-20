"""Self-serve setup: the wizard's steps and the dashboard checklist.

Most steps are worked out from the data (a site with a gate exists, hosts exist...).
A few can't be: whether the admin reviewed their organization details or the check-in
form, and whether posters were printed. Those are flags in ``organizations.onboarding``
({step: ISO time}), set when the admin finishes that step (posters: when downloaded).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import all_, any_, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal
from app.core.errors import AppError
from app.models import Gate, Organization, Purpose, Site, User, Visit, VisitEvent, Visitor
from app.services import visits as visit_svc

FLAG_STEPS = ("org", "form", "posters")
TEST_NAME = "Test visitor"


@dataclass
class Step:
    key: str
    label: str
    detail: str
    done: bool
    wizard: bool = True  # part of the sign-up wizard (guard is checklist-only)


def now() -> datetime:
    return datetime.now(UTC)


async def mark(db: AsyncSession, org: Organization, step: str, value: Any = None) -> None:
    flags = dict(org.onboarding or {})
    if step not in flags or value is not None:
        flags[step] = value if value is not None else now().isoformat()
        org.onboarding = flags


async def checklist(db: AsyncSession, org: Organization) -> dict[str, Any]:
    flags = org.onboarding or {}
    sites = (
        await db.execute(
            select(func.count(func.distinct(Site.id)), func.count(Gate.id))
            .select_from(Site)
            .join(Gate, (Gate.site_id == Site.id) & Gate.is_active.is_(True), isouter=True)
            .where(Site.is_active.is_(True))
        )
    ).one()
    hosts = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(
                User.is_active.is_(True),
                literal("host") == any_(User.roles),
                literal("org_admin") != all_(User.roles),
            )
        )
    ).scalar_one()
    guards = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.is_active.is_(True), literal("guard") == any_(User.roles))
        )
    ).scalar_one()
    purposes = (
        await db.execute(
            select(func.count()).select_from(Purpose).where(Purpose.is_active.is_(True))
        )
    ).scalar_one()
    test = None
    if tid := flags.get("test_visit"):
        v = await db.get(Visit, UUID(tid))
        if v:
            test = {"id": str(v.id), "status": v.status, "requested_at": v.requested_at}
    steps = [
        Step("org", "Organization details", "Name, logo, colours, privacy contact", "org" in flags),
        Step(
            "site",
            "Add your first site",
            f"{sites[0]} site(s), {sites[1]} gate(s)" if sites[0] else "Office, plant or campus",
            sites[1] > 0,
        ),
        Step(
            "hosts",
            "Import your hosts",
            f"{hosts} host(s)" if hosts else "CSV upload or one by one",
            hosts > 0,
        ),
        Step(
            "form",
            "Customize the check-in form",
            f"{purposes} purpose(s)"
            if "form" in flags
            else "Purposes, photo, ID proof, extra fields",
            "form" in flags,
        ),
        Step("posters", "Print the QR posters", "One A4 poster per gate", "posters" in flags),
        Step(
            "test_visit",
            "Send a test visit",
            "You approve it on WhatsApp" if not test else f"Test visit: {test['status']}",
            bool(test and test["status"] != "pending"),
        ),
        Step(
            "guard",
            "Add a guard or receptionist",
            f"{guards} guard(s)" if guards else "They verify passes at the gate",
            guards > 0,
            wizard=False,
        ),
    ]
    done = sum(s.done for s in steps)
    return {
        "steps": [s.__dict__ for s in steps],
        "done": done,
        "total": len(steps),
        "complete": done == len(steps),
        "dismissed": bool(flags.get("dismissed")),
        "test_visit": test,
    }


async def test_visit(
    db: AsyncSession, org: Organization, p: Principal, phone: str | None
) -> tuple[Visit, visit_svc.AfterCommit]:
    """A visit to the admin themself, so they see the WhatsApp approval request arrive
    and can tap Approve. It goes through the real provider, then shows in the visit log
    as "Test visitor"."""
    admin = await db.get(User, p.id)
    assert admin is not None
    if phone and phone != admin.phone:
        taken = (
            await db.execute(select(User.id).where(User.phone == phone, User.id != admin.id))
        ).first()
        if taken:
            raise AppError(
                409, "phone_taken", "Another person in your organization has this number"
            )
        admin.phone = phone
    if not admin.phone:
        raise AppError(422, "phone_required", "Enter your WhatsApp number to receive the test")
    if "host" not in admin.roles:
        admin.roles = [*admin.roles, "host"]  # admins can be visited too
    row = (
        await db.execute(
            select(Site, Gate)
            .join(Gate, Gate.site_id == Site.id)
            .where(Site.is_active.is_(True), Gate.is_active.is_(True))
            .order_by(Site.created_at, Gate.created_at)
            .limit(1)
        )
    ).first()
    if row is None:
        raise AppError(409, "no_site", "Add a site with a gate first")
    site, gate = row
    purpose = (
        (
            await db.execute(
                select(Purpose).where(Purpose.is_active.is_(True)).order_by(Purpose.sort_order)
            )
        )
        .scalars()
        .first()
    )
    t = now()
    visitor = (
        await db.execute(select(Visitor).where(Visitor.phone == admin.phone))
    ).scalar_one_or_none()
    if visitor is None:
        visitor = Visitor(org_id=org.id, phone=admin.phone, first_seen_at=t, visit_count=0)
        db.add(visitor)
    visitor.full_name = visitor.full_name or TEST_NAME
    visitor.visit_count += 1
    visitor.last_visit_at = t
    await db.flush()
    settings = org.settings or {}
    v = Visit(
        org_id=org.id,
        site_id=site.id,
        gate_id=gate.id,
        host_id=admin.id,
        visitor_id=visitor.id,
        source="guard_manual",
        status="pending",
        locale=org.default_locale,
        visitor_name=TEST_NAME,
        visitor_company="Setup check",
        visitor_phone=admin.phone,
        purpose_id=purpose.id if purpose else None,
        purpose_note="Sent from the setup wizard. Tap Approve to finish.",
        current_approver_id=admin.id,
        notified_approver_ids=[admin.id],
        escalation_level=0,
        next_escalation_at=None,  # never escalate a test
        requested_at=t,
        valid_until=visit_svc.day_end(settings, t),
    )
    db.add(v)
    await db.flush()
    db.add(
        VisitEvent(
            org_id=org.id,
            visit_id=v.id,
            from_status=None,
            to_status="pending",
            actor_type="admin",
            actor_id=admin.id,
            channel="web",
            meta={"setup_test": True},
        )
    )
    after = visit_svc.AfterCommit(visits=[v])
    await visit_svc.ask_approver(db, org, v, admin, "visit_request", after)
    await mark(db, org, "test_visit", str(v.id))
    return v, after
