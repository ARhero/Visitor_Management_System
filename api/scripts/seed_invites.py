"""Demo pre-approved invites and blacklist entries (Phase 3).

Invites are relative to today (IST) so the guard console always has guests
"expected today". Passes are not sent (no WhatsApp messages in the seed); the pass
links are printed so you can open them.
"""

from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BlacklistEntry, Invite, Organization, Purpose, Site, User
from app.services import invites as invite_svc
from app.services import passes
from app.services.visits import IST


async def seed_safety_contacts(s: AsyncSession, org: Organization) -> None:
    """Demo fire wardens for HQ, so "Send to safety contacts" can be tried."""
    hq = (
        await s.execute(select(Site).where(Site.org_id == org.id, Site.name == "Bhubaneswar HQ"))
    ).scalar_one_or_none()
    if hq and not hq.safety_contacts:
        hq.safety_contacts = [
            {"name": "Bijay Das (fire warden)", "phone": "+919900000201"},
            {"name": "Lipsa Rout (security head)", "phone": "+919900000202"},
        ]


async def seed_invites(s: AsyncSession, org: Organization) -> list[str]:
    """Returns pass links for the demo guests."""
    if (await s.execute(select(Invite.id).where(Invite.org_id == org.id).limit(1))).first():
        return []
    sites = {
        x.name: x for x in (await s.execute(select(Site).where(Site.org_id == org.id))).scalars()
    }
    hosts = {
        u.full_name: u
        for u in (await s.execute(select(User).where(User.org_id == org.id))).scalars()
    }
    meeting = (
        await s.execute(
            select(Purpose).where(Purpose.org_id == org.id).order_by(Purpose.sort_order).limit(1)
        )
    ).scalar_one_or_none()
    hq = sites["Bhubaneswar HQ"]
    today = datetime.now(IST).date()
    admin = next((u for u in hosts.values() if "org_admin" in u.roles), None)

    def at(day, hh: int, mm: int = 0) -> datetime:
        return datetime.combine(day, time(hh, mm), IST)

    specs = [
        dict(
            host="Meera Iyer",
            kind="single",
            title="Contract signing",
            notes="Escort to Legal, 4th floor",
            start=at(today, 0),
            end=at(today, 23, 59),
            guests=[("Kabir Malhotra", "+919900000101", "Malhotra & Associates")],
        ),
        dict(
            host="Sneha Patnaik",
            kind="group",
            title="Campus hiring panel",
            notes="Conference room 2",
            start=at(today, 0),
            end=at(today, 23, 59),
            guests=[
                ("Ritika Sharma", "+919900000102", "IIT Bhubaneswar"),
                ("Aditya Rao", "+919900000103", "IIT Bhubaneswar"),
                ("Neha Gupta", "+919900000104", "KIIT University"),
            ],
        ),
        dict(
            host="Arjun Nair",
            kind="multi_day",
            title="Statutory audit",
            notes="Finance wing, laptop allowed",
            start=at(today - timedelta(days=1), 0),
            end=at(today + timedelta(days=4), 23, 59),
            daily=(time(0, 0), time(23, 59)),
            guests=[("Farhan Qureshi", "+919900000105", "Deloitte")],
        ),
        dict(
            host="Vikram Singh",
            kind="single",
            title="HVAC maintenance",
            notes=None,
            start=at(today + timedelta(days=2), 10),
            end=at(today + timedelta(days=2), 13),
            guests=[("Manoj Behera", "+919900000106", "CoolAir Services")],
        ),
    ]
    links = []
    for sp in specs:
        daily = sp.get("daily")
        inv = Invite(
            org_id=org.id,
            site_id=hq.id,
            host_id=hosts[sp["host"]].id,
            purpose_id=meeting.id if meeting else None,
            kind=sp["kind"],
            title=sp["title"],
            notes=sp["notes"],
            valid_from=sp["start"],
            valid_until=sp["end"],
            daily_start_time=daily[0] if daily else None,
            daily_end_time=daily[1] if daily else None,
            status="active",
            created_via="web",
            created_by=hosts[sp["host"]].id,
        )
        s.add(inv)
        await s.flush()
        rows = await invite_svc.add_guests(
            s, inv, [{"name": n, "phone": p, "company": c} for n, p, c in sp["guests"]]
        )
        for g in rows:
            g.sent_at = inv.created_at
            links.append(f"{g.name}: {passes.pass_url(invite_svc.pass_token(inv, g))}")

    s.add_all(
        [
            BlacklistEntry(
                org_id=org.id,
                phone="+919900000666",
                name="Rajesh Kumar",
                reason="Trespassing incident on 2 Oct; police complaint filed",
                action="block",
                added_by=admin.id if admin else None,
            ),
            BlacklistEntry(
                org_id=org.id,
                phone="+919900000777",
                name="Sunil Das",
                reason="Former vendor: check ID and call Facilities before letting in",
                action="alert",
                added_by=admin.id if admin else None,
            ),
        ]
    )
    await s.flush()
    return links
