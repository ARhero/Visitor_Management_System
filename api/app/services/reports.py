"""Reports and the live dashboard. All bucketing is by IST calendar day / hour, done in
SQL so a 23:30 IST visit lands on the right day.

IST is a fixed +05:30 (India has no daylight saving), so we use the offset rather than
the zone name: that works even on a PostgreSQL built without the time zone database
(e.g. the embedded server used for local development on Windows)."""

from datetime import UTC, date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Date, and_, cast, distinct, extract, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Department, Gate, Purpose, Site, User, Visit, VisitEvent
from app.schemas.reports import (
    ApprovalTimes,
    DepartmentRow,
    Live,
    PeakHours,
    Point,
    TopHost,
    Traffic,
)
from app.services.invites import today_start
from app.services.visit_log import day_after, day_start
from app.services.visits import now

IST_OFFSET = text("INTERVAL '+05:30'")
ANSWERED = Visit.response_channel.in_(("whatsapp", "web"))
WAIT = extract("epoch", Visit.responded_at - Visit.requested_at)
CAME = Visit.status.in_(("checked_in", "checked_out"))
BUCKETS = [
    ("< 1 min", 60),
    ("1–2 min", 120),
    ("2–5 min", 300),
    ("5–10 min", 600),
    ("10–30 min", 1800),
    ("> 30 min", None),
]


def local(col: Any) -> Any:
    return func.timezone(IST_OFFSET, col)


def _range(f: date, t: date, site_id: UUID | None, col: Any = Visit.requested_at) -> list[Any]:
    conds = [col >= day_start(f), col < day_after(t)]
    if site_id:
        conds.append(Visit.site_id == site_id)
    return conds


def _int(x: Any) -> int | None:
    return int(round(float(x))) if x is not None else None


async def traffic(db: AsyncSession, f: date, t: date, site_id: UUID | None) -> Traffic:
    day = cast(local(Visit.requested_at), Date)
    rows = (
        await db.execute(
            select(
                day.label("day"),
                func.count(),
                func.count().filter(CAME),
                func.count().filter(Visit.status == "rejected"),
                func.count().filter(Visit.status == "expired"),
            )
            .where(*_range(f, t, site_id))
            .group_by(day)
        )
    ).all()
    by_day = {r[0]: r for r in rows}
    days = []
    d = f
    while d <= t:  # every day in the range, zeros included, so charts have no gaps
        r = by_day.get(d)
        days.append(
            Point(
                day=d,
                requests=r[1] if r else 0,
                checked_in=r[2] if r else 0,
                rejected=r[3] if r else 0,
                expired=r[4] if r else 0,
            )
        )
        d += timedelta(days=1)

    tot = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(CAME),
                func.coalesce(func.sum(1 + Visit.accompanying_count).filter(CAME), 0),
                func.count().filter(Visit.status == "rejected"),
                func.count().filter(Visit.status == "expired"),
                func.count().filter(Visit.status == "cancelled"),
                func.count(distinct(Visit.visitor_id)),
                func.count().filter(Visit.blacklist_hit_id.is_not(None)),
            ).where(*_range(f, t, site_id))
        )
    ).one()
    sources = dict(
        (
            await db.execute(
                select(Visit.source, func.count())
                .where(*_range(f, t, site_id))
                .group_by(Visit.source)
            )
        ).all()
    )
    purposes = (
        await db.execute(
            select(func.coalesce(Purpose.label, literal("Other")), func.count())
            .select_from(Visit)
            .outerjoin(Purpose, Purpose.id == Visit.purpose_id)
            .where(*_range(f, t, site_id))
            .group_by(Purpose.label)
            .order_by(func.count().desc())
            .limit(8)
        )
    ).all()
    return Traffic(
        days=days,
        totals={
            "requests": tot[0],
            "visits": tot[1],
            "people": int(tot[2]),
            "rejected": tot[3],
            "expired": tot[4],
            "cancelled": tot[5],
            "unique_visitors": tot[6],
            "flagged": tot[7],
        },
        by_source={k: sources.get(k, 0) for k in ("qr_self", "guard_manual", "invite")},
        by_purpose=[{"label": p, "visits": n} for p, n in purposes],
    )


async def peak_hours(db: AsyncSession, f: date, t: date, site_id: UUID | None) -> PeakHours:
    lt = local(Visit.checked_in_at)
    wd = (extract("isodow", lt) - 1).label("wd")
    hr = extract("hour", lt).label("hr")
    rows = (
        await db.execute(
            select(wd, hr, func.count())
            .where(*_range(f, t, site_id, Visit.checked_in_at))
            .group_by(wd, hr)
        )
    ).all()
    grid = [[0] * 24 for _ in range(7)]
    for w, h, n in rows:
        grid[int(w)][int(h)] = n
    best = max(((w, h, grid[w][h]) for w in range(7) for h in range(24)), key=lambda x: x[2])
    busiest = {"weekday": best[0], "hour": best[1], "check_ins": best[2]} if best[2] else None
    return PeakHours(grid=grid, busiest=busiest)


async def top_hosts(
    db: AsyncSession, f: date, t: date, site_id: UUID | None, limit: int = 10
) -> list[TopHost]:
    rows = (
        await db.execute(
            select(
                User.id,
                User.full_name,
                Department.name,
                func.count(Visit.id),
                func.count(Visit.id).filter(
                    Visit.status.in_(("approved", "checked_in", "checked_out"))
                ),
                func.percentile_cont(0.5).within_group(WAIT).filter(ANSWERED),
            )
            .select_from(Visit)
            .join(User, User.id == Visit.host_id)
            .outerjoin(Department, Department.id == User.department_id)
            .where(*_range(f, t, site_id))
            .group_by(User.id, User.full_name, Department.name)
            .order_by(func.count(Visit.id).desc(), User.full_name)
            .limit(limit)
        )
    ).all()
    return [
        TopHost(
            host_id=r[0],
            host_name=r[1],
            department=r[2],
            visits=r[3],
            approved=r[4],
            median_wait_seconds=_int(r[5]),
        )
        for r in rows
    ]


async def departments(
    db: AsyncSession, f: date, t: date, site_id: UUID | None
) -> list[DepartmentRow]:
    name = func.coalesce(Department.name, literal("No department"))
    rows = (
        await db.execute(
            select(name, func.count(Visit.id), func.count(distinct(Visit.host_id)))
            .select_from(Visit)
            .join(User, User.id == Visit.host_id)
            .outerjoin(Department, Department.id == User.department_id)
            .where(*_range(f, t, site_id))
            .group_by(name)
            .order_by(func.count(Visit.id).desc())
        )
    ).all()
    return [DepartmentRow(department=r[0], visits=r[1], hosts=r[2]) for r in rows]


async def approval_times(db: AsyncSession, f: date, t: date, site_id: UUID | None) -> ApprovalTimes:
    scope = [*_range(f, t, site_id), Visit.source != "invite"]
    bucket_cols = []
    lo = 0
    for label, hi in BUCKETS:
        cond = and_(ANSWERED, WAIT >= lo) if hi is None else and_(ANSWERED, WAIT >= lo, WAIT < hi)
        bucket_cols.append(func.count().filter(cond).label(label))
        lo = hi or lo
    r = (
        await db.execute(
            select(
                func.count().filter(ANSWERED),
                func.count().filter(
                    Visit.status == "expired",
                    Visit.responded_at.is_(None),
                    Visit.approved_at.is_(None),
                ),
                func.percentile_cont(0.5).within_group(WAIT).filter(ANSWERED),
                func.percentile_cont(0.9).within_group(WAIT).filter(ANSWERED),
                func.count().filter(Visit.response_channel == "whatsapp"),
                func.count().filter(Visit.response_channel == "web"),
                func.count().filter(Visit.escalation_level > 0),
                func.count().filter(Visit.response_channel == "guard"),
                *bucket_cols,
            ).where(*scope)
        )
    ).one()
    return ApprovalTimes(
        answered=r[0],
        unanswered=r[1],
        median_seconds=_int(r[2]),
        p90_seconds=_int(r[3]),
        by_channel={"whatsapp": r[4], "web": r[5]},
        escalated=r[6],
        overrides=r[7],
        buckets=[
            {"label": label, "max_seconds": hi, "count": r[8 + i]}
            for i, (label, hi) in enumerate(BUCKETS)
        ],
    )


# ---------- Live ----------


async def live(db: AsyncSession, site_id: UUID | None) -> Live:
    t = now()
    day = today_start(t)
    scope = [Visit.site_id == site_id] if site_id else []
    c = (
        await db.execute(
            select(
                func.count().filter(Visit.status == "checked_in"),
                func.coalesce(
                    func.sum(1 + Visit.accompanying_count).filter(Visit.status == "checked_in"), 0
                ),
                func.count().filter(
                    Visit.status.in_(("pending", "waiting")), Visit.valid_until > t
                ),
                func.count().filter(Visit.status == "approved", Visit.valid_until > t),
                func.count().filter(Visit.requested_at >= day),
                func.count().filter(Visit.checked_in_at >= day),
                func.count().filter(Visit.checked_out_at >= day),
                func.count().filter(
                    Visit.requested_at >= day,
                    Visit.status == "rejected",
                    Visit.blacklist_hit_id.is_(None),
                ),
                func.count().filter(Visit.requested_at >= day, Visit.status == "expired"),
                func.count().filter(Visit.requested_at >= day, Visit.blacklist_hit_id.is_not(None)),
                func.percentile_cont(0.5)
                .within_group(WAIT)
                .filter(ANSWERED, Visit.requested_at >= day),
            ).where(*scope)
        )
    ).one()
    gates = (
        await db.execute(
            select(Site.name, func.coalesce(Gate.name, literal("At the desk")), func.count())
            .select_from(Visit)
            .join(Site, Site.id == Visit.site_id)
            .outerjoin(Gate, Gate.id == Visit.gate_id)
            .where(Visit.checked_in_at >= day, *scope)
            .group_by(Site.name, Gate.name)
            .order_by(func.count().desc())
        )
    ).all()
    hr = extract("hour", local(Visit.checked_in_at))
    hours = dict(
        (
            await db.execute(
                select(hr, func.count()).where(Visit.checked_in_at >= day, *scope).group_by(hr)
            )
        ).all()
    )
    sites = (
        await db.execute(
            select(
                Site.id,
                Site.name,
                func.count(Visit.id),
                func.coalesce(func.sum(1 + Visit.accompanying_count), 0),
            )
            .select_from(Site)
            .outerjoin(Visit, and_(Visit.site_id == Site.id, Visit.status == "checked_in"))
            .where(Site.is_active.is_(True), *([Site.id == site_id] if site_id else []))
            .group_by(Site.id, Site.name)
            .order_by(Site.name)
        )
    ).all()
    events = (
        await db.execute(
            select(VisitEvent, Visit.visitor_name, Site.name)
            .join(Visit, Visit.id == VisitEvent.visit_id)
            .join(Site, Site.id == Visit.site_id)
            .where(VisitEvent.created_at >= day, *scope)
            .order_by(VisitEvent.created_at.desc())
            .limit(12)
        )
    ).all()
    return Live(
        at=t,
        on_site=c[0],
        people_on_site=int(c[1]),
        waiting_for_host=c[2],
        approved_not_arrived=c[3],
        today={
            "requests": c[4],
            "checked_in": c[5],
            "checked_out": c[6],
            "rejected": c[7],
            "expired": c[8],
            "blocked": c[9],
        },
        median_wait_seconds_today=_int(c[10]),
        by_gate=[{"site": s, "gate": g, "check_ins": n} for s, g, n in gates],
        by_hour=[int(hours.get(h, 0)) for h in range(24)],
        by_site=[
            {"site_id": str(i), "site": n, "on_site": v, "people": int(p)} for i, n, v, p in sites
        ],
        recent=[
            {
                "at": e.created_at.astimezone(UTC).isoformat(),
                "visit_id": str(e.visit_id),
                "visitor": name,
                "site": site,
                "to": e.to_status,
                "from": e.from_status,
                "actor": e.actor_type,
            }
            for e, name, site in events
        ],
    )
