"""Demo data: one org ("Kalinga Infotech"), 2 sites, 10 hosts, an admin, a guard
a platform super admin, about 300 sample visits over the last 30 days
(scripts/seed_visits.py), a few of them live today, and pre-approved invites plus
two blacklist entries (scripts/seed_invites.py).

    uv run python -m scripts.seed

Safe to re-run: the org is created only if missing, visits and invites only if it
has none.
Demo logins are printed at the end (all use the password from SEED_PASSWORD,
default ``demo-password-123``).
"""

import asyncio
import os

from sqlalchemy import func, select

from app.core.db import dispose_engines, system_session
from app.core.security import hash_password
from app.models import (
    Department,
    Gate,
    GuardSiteAssignment,
    Organization,
    PlatformUser,
    Site,
    User,
    Visit,
)
from app.services.orgs import create_org_with_admin, new_qr_token
from scripts.seed_invites import seed_invites, seed_safety_contacts
from scripts.seed_visits import seed_visits

PASSWORD = os.environ.get("SEED_PASSWORD", "demo-password-123")
ORG_NAME = "Kalinga Infotech Pvt Ltd"

SITES = [
    {
        "name": "Bhubaneswar HQ",
        "address": "Plot 12, Infocity, Chandrasekharpur",
        "city": "Bhubaneswar",
        "state": "Odisha",
        "pincode": "751024",
        "gates": ["Main Gate", "Tower B Lobby"],
    },
    {
        "name": "Pune Development Centre",
        "address": "Hinjewadi Phase 2",
        "city": "Pune",
        "state": "Maharashtra",
        "pincode": "411057",
        "gates": ["Reception"],
    },
]

HOSTS = [
    ("Ananya Mohanty", "Engineering", "Engineering Manager", 0),
    ("Rahul Verma", "Engineering", "Tech Lead", 1),
    ("Sneha Patnaik", "Human Resources", "HR Business Partner", 0),
    ("Arjun Nair", "Finance", "Finance Controller", 0),
    ("Priya Deshpande", "Engineering", "Principal Engineer", 1),
    ("Vikram Singh", "Facilities", "Facilities Head", 0),
    ("Kavya Reddy", "Sales", "Account Director", 1),
    ("Suresh Panda", "Administration", "Admin Officer", 0),
    ("Meera Iyer", "Legal", "Legal Counsel", 0),
    ("Rohan Kulkarni", "Human Resources", "Talent Acquisition Lead", 1),
]


async def main() -> None:
    async with system_session() as s:
        existing = (
            await s.execute(select(Organization).where(Organization.name == ORG_NAME))
        ).scalar_one_or_none()
        if existing:
            n = (
                await s.execute(
                    select(func.count()).select_from(Visit).where(Visit.org_id == existing.id)
                )
            ).scalar_one()
            added = 0 if n else await seed_visits(s, existing)
            links = await seed_invites(s, existing)
            await seed_safety_contacts(s, existing)
            await s.commit()
            print(
                f"Demo org already exists; added {added} sample visits, {len(links)} invite passes."
            )
            _print_links(links)
            await dispose_engines()
            return

        org, admin = await create_org_with_admin(
            s,
            name=ORG_NAME,
            admin_name="Deepak Rath",
            admin_email="admin@kalinga.demo",
            admin_password=PASSWORD,
            admin_phone="+919861000001",
            status="active",
        )
        sites = []
        for sd in SITES:
            gates = sd.pop("gates")
            site = Site(org_id=org.id, **sd)
            s.add(site)
            await s.flush()
            for g in gates:
                s.add(Gate(org_id=org.id, site_id=site.id, name=g, qr_token=new_qr_token()))
            sites.append(site)

        depts: dict[str, Department] = {}
        for _, dname, _, _ in HOSTS:
            if dname not in depts:
                depts[dname] = Department(org_id=org.id, name=dname)
                s.add(depts[dname])
        await s.flush()

        hosts = []
        for i, (name, dname, title, site_idx) in enumerate(HOSTS):
            first = name.split()[0].lower()
            u = User(
                org_id=org.id,
                full_name=name,
                email=f"{first}@kalinga.demo",
                phone=f"+91986100{i + 10:04d}",
                roles=["host"],
                department_id=depts[dname].id,
                designation=title,
                employee_code=f"KIT{1001 + i}",
                primary_site_id=sites[site_idx].id,
            )
            s.add(u)
            hosts.append(u)
        await s.flush()
        for i, h in enumerate(hosts):  # pair hosts as each other's backup
            h.backup_host_id = hosts[i ^ 1].id

        guard = User(
            org_id=org.id,
            full_name="Ramesh Behera",
            phone="+919861000002",
            roles=["guard"],
            password_hash=hash_password(PASSWORD),
            primary_site_id=sites[0].id,
        )
        s.add(guard)
        await s.flush()
        s.add(GuardSiteAssignment(org_id=org.id, user_id=guard.id, site_id=sites[0].id))

        if not (
            await s.execute(select(PlatformUser).where(PlatformUser.email == "root@vms.local"))
        ).first():
            s.add(
                PlatformUser(
                    email="root@vms.local",
                    full_name="Platform Admin",
                    password_hash=hash_password(PASSWORD),
                )
            )
        await s.flush()
        added = await seed_visits(s, org)
        links = await seed_invites(s, org)
        await seed_safety_contacts(s, org)
        await s.commit()

    print(f"Seeded demo org: {ORG_NAME} with {added} sample visits")
    print(f"  Org admin : admin@kalinga.demo / {PASSWORD}")
    print(f"  Guard     : 9861000002 / {PASSWORD}")
    print(f"  Super admin (POST /api/v1/auth/platform/login): root@vms.local / {PASSWORD}")
    print("  Hosts sign in with a WhatsApp link (see /dev/whatsapp), e.g. Meera Iyer +919861000018")
    _print_links(links)
    await dispose_engines()


def _print_links(links: list[str]) -> None:
    if links:
        print("Invite passes (pre-approved guests):")
        for line in links:
            print(f"  {line}")
        print("Blacklist demo numbers: +919900000666 (block), +919900000777 (alert)")


if __name__ == "__main__":
    asyncio.run(main())
