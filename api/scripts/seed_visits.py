"""Sample visits for the demo org: about 300 over the last 30 days, plus a live picture
for today (on site, approved, waiting for a host). Used by scripts/seed.py."""

import random
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Gate, Organization, Purpose, Site, User, Visit, VisitEvent, Visitor
from app.services import passes
from app.services.visits import day_end

IST = ZoneInfo("Asia/Kolkata")
FIRST = (
    "Aarav Aditi Amit Anjali Bikash Deepika Gaurav Ishita Jyoti Karan Lakshmi Manoj Neha "
    "Nikhil Pooja Pradeep Rajesh Ritu Sabyasachi Sandeep Shreya Smita Subhash Swati Tanmay "
    "Usha Varun Yash Zoya Farhan"
).split()
LAST = (
    "Sahoo Das Mishra Jena Rao Sharma Gupta Khan Mehta Joshi Pillai Banerjee Chatterjee Bose "
    "Naik Pradhan Agarwal Kapoor Menon Shetty"
).split()
COMPANIES = [
    None,
    None,
    "Tata Consultancy Services",
    "Infosys",
    "L&T Construction",
    "Odisha Steels Ltd",
    "Deloitte India",
    "Blue Dart",
    "Wipro",
    "KPMG",
    "Godrej Interio",
    "Swiggy",
    "Urban Company",
    "Freelancer",
    "HDFC Bank",
    "Amazon Logistics",
]
LETTERS = "ABCDEFGHJK"


async def seed_visits(s: AsyncSession, org: Organization) -> int:
    rnd = random.Random(42)
    sites = (await s.execute(select(Site).where(Site.org_id == org.id))).scalars().all()
    gates = (await s.execute(select(Gate).where(Gate.org_id == org.id))).scalars().all()
    users = (await s.execute(select(User).where(User.org_id == org.id))).scalars().all()
    hosts = [u for u in users if "host" in u.roles and u.phone and u.primary_site_id]
    guard = next((u for u in users if "guard" in u.roles), None)
    purposes = (
        (
            await s.execute(
                select(Purpose).where(Purpose.org_id == org.id).order_by(Purpose.sort_order)
            )
        )
        .scalars()
        .all()
    )
    weights = [40, 12, 15, 18, 10, 5][: len(purposes)]

    now = datetime.now(UTC)
    visitors = []
    for i in range(120):
        v = Visitor(
            org_id=org.id,
            phone=f"+9190000{10000 + i:05d}",
            full_name=f"{rnd.choice(FIRST)} {rnd.choice(LAST)}",
            company=rnd.choice(COMPANIES),
            preferred_locale="hi" if rnd.random() < 0.25 else "en",
            first_seen_at=now - timedelta(days=31),
            visit_count=0,
        )
        s.add(v)
        visitors.append(v)
    await s.flush()

    pending_events: list[tuple[Visit, VisitEvent]] = []

    def add(day: date, status: str, at: time | None = None) -> None:
        visitor = rnd.choice(visitors)
        host = rnd.choice(hosts)
        site = next(x for x in sites if x.id == host.primary_site_id)
        gate = rnd.choice([g for g in gates if g.site_id == site.id])
        t_local = at or time(
            rnd.choice([9, 10, 10, 11, 11, 12, 14, 15, 15, 16, 17]), rnd.randrange(60)
        )
        requested = datetime.combine(day, t_local, IST).astimezone(UTC)
        vehicle = None
        if rnd.random() < 0.3:
            vehicle = (
                f"OD{rnd.randint(1, 35):02d}{rnd.choice(LETTERS)}{rnd.choice(LETTERS)}"
                f"{rnd.randint(1000, 9999)}"
            )
        v = Visit(
            org_id=org.id,
            site_id=site.id,
            gate_id=gate.id,
            host_id=host.id,
            visitor_id=visitor.id,
            source="qr_self",
            status=status,
            locale=visitor.preferred_locale,
            visitor_name=visitor.full_name,
            visitor_company=visitor.company,
            visitor_phone=visitor.phone,
            purpose_id=rnd.choices(purposes, weights)[0].id,
            accompanying_count=rnd.choice([0, 0, 0, 0, 1, 1, 2]),
            vehicle_number=vehicle,
            custom_values={},
            current_approver_id=host.id,
            notified_approver_ids=[host.id],
            requested_at=requested,
            valid_until=day_end(org.settings, requested),
        )
        trail = [(None, "pending", "visitor", None, "web", requested)]
        t = requested + timedelta(seconds=rnd.randint(25, 420))
        if status in ("approved", "checked_in", "checked_out"):
            v.approved_at = v.responded_at = t
            v.responded_by = host.id
            v.response_channel = "whatsapp" if rnd.random() < 0.85 else "web"
            v.pass_jti = passes.new_jti()
            trail.append(("pending", "approved", "host", host.id, v.response_channel, t))
        if status in ("checked_in", "checked_out"):
            t += timedelta(minutes=rnd.randint(1, 6))
            v.checked_in_at, v.checked_in_by = t, guard.id if guard else None
            trail.append(("approved", "checked_in", "guard", v.checked_in_by, "web", t))
        if status == "checked_out":
            auto = day < today and rnd.random() < 0.1
            t = v.valid_until if auto else t + timedelta(minutes=rnd.randint(15, 180))
            v.checked_out_at, v.checkout_method = t, "auto" if auto else "guard"
            trail.append(
                ("checked_in", "checked_out", "system" if auto else "guard", None, "web", t)
            )
        if status in ("rejected", "waiting"):
            v.responded_at, v.responded_by, v.response_channel = t, host.id, "whatsapp"
            v.host_message = (
                "In a meeting, 10 minutes"
                if status == "waiting"
                else rnd.choice([None, "Not available today", "Please reschedule"])
            )
            trail.append(("pending", status, "host", host.id, "whatsapp", t))
        if status == "expired":
            trail.append(
                ("pending", "expired", "system", None, "system", t + timedelta(minutes=10))
            )
        if status == "cancelled":
            trail.append(("pending", "cancelled", "visitor", None, "web", t))
        if status == "pending":
            v.next_escalation_at = now + timedelta(minutes=30)
        s.add(v)
        visitor.visit_count += 1
        visitor.last_visit_at = max(visitor.last_visit_at or requested, requested)
        for frm, to, actor, actor_id, channel, at_ in trail:
            ev = VisitEvent(
                org_id=org.id,
                from_status=frm,
                to_status=to,
                actor_type=actor,
                actor_id=actor_id,
                channel=channel,
                meta={},
                created_at=at_,
                updated_at=at_,
            )
            pending_events.append((v, ev))

    today = now.astimezone(IST).date()
    for back in range(30, 0, -1):
        day = today - timedelta(days=back)
        wd = day.weekday()
        n = rnd.randint(1, 3) if wd == 6 else rnd.randint(4, 7) if wd == 5 else rnd.randint(9, 14)
        for _ in range(n):
            status = rnd.choices(["checked_out", "rejected", "expired", "cancelled"], [86, 6, 5, 3])
            add(day, status[0])

    # Today: a live picture, spread over the hours before now.
    now_ist = now.astimezone(IST)
    start = now_ist.replace(hour=0, minute=5, second=0, microsecond=0)

    def ago(minutes: int) -> time:
        return max(now_ist - timedelta(minutes=minutes), start).time()

    for m in (240, 200, 150, 120, 95):
        add(today, "checked_out", ago(m))
    for m in (80, 55, 40, 25):
        add(today, "checked_in", ago(m))
    add(today, "approved", ago(12))
    add(today, "waiting", ago(6))
    add(today, "pending", ago(2))

    await s.flush()
    for v, ev in pending_events:
        ev.visit_id = v.id
        s.add(ev)
    await s.flush()
    return len({id(v) for v, _ in pending_events})
