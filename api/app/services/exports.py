"""Files: the evacuation list, visit-log exports (CSV / Excel / PDF) and the report PDF.

Exports run as background jobs (ARQ, or a task inside the API when there is no
worker). The file goes to object storage and is deleted after ``TTL``.
"""

import asyncio
import csv
import io
import logging
from datetime import date, datetime, timedelta
from uuid import UUID

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import system_session, tenant_session
from app.models import ExportJob, Gate, Organization, Site, User, Visit
from app.schemas.reports import Evacuation, EvacuationRow, VisitFilters, VisitRow
from app.services import reports, storage, visit_log
from app.services.pdf import BOX, Doc, duration, ist
from app.services.visits import IST, now

log = logging.getLogger(__name__)
TTL = timedelta(hours=24)
MAX_ROWS = {"visits_csv": 100_000, "visits_xlsx": 100_000, "visits_pdf": 2_000}
CONTENT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ---------- Evacuation ----------


async def evacuation(db: AsyncSession, site_ids: list[UUID] | None) -> Evacuation:
    """Everyone checked in right now (optionally at some sites)."""
    host = User.__table__.alias("host")
    q = (
        select(Visit, host.c.full_name, host.c.phone, Site.name, Gate.name)
        .join(host, host.c.id == Visit.host_id)
        .join(Site, Site.id == Visit.site_id)
        .outerjoin(Gate, Gate.id == Visit.gate_id)
        .where(Visit.status == "checked_in")
        .order_by(Site.name, Visit.visitor_name)
    )
    if site_ids is not None:
        q = q.where(Visit.site_id.in_(site_ids))
    rows = (await db.execute(q)).all()
    out = [
        EvacuationRow(
            visit_id=v.id,
            visitor_name=v.visitor_name,
            visitor_company=v.visitor_company,
            visitor_phone=v.visitor_phone,
            photo_url=await storage.signed_url(v.photo_key),
            host_name=hn,
            host_phone=hp,
            site_name=sn,
            gate_name=gn,
            accompanying_count=v.accompanying_count,
            checked_in_at=v.checked_in_at,
        )
        for v, hn, hp, sn, gn in rows
    ]
    site = None
    contacts: list[dict[str, str]] = []
    if site_ids and len(site_ids) == 1:
        site = await db.get(Site, site_ids[0])
        contacts = list(site.safety_contacts or []) if site else []
    return Evacuation(
        at=now(),
        site_id=site.id if site else None,
        site_name=site.name if site else None,
        visits=len(out),
        people=sum(1 + r.accompanying_count for r in out),
        rows=out,
        contacts=contacts,
    )


def phone_text(p: str | None) -> str:
    """+919861000018 → +91 98610 00018 (readable, and doesn't wrap mid-number)."""
    if not p:
        return "–"
    if p.startswith("+91") and len(p) == 13:
        return f"+91 {p[3:8]} {p[8:]}"
    return p


def evacuation_pdf(org: Organization, ev: Evacuation) -> bytes:
    doc = Doc(
        "Evacuation list: visitors on site",
        f"{ev.site_name or 'All sites'} · as of {ist(ev.at)} IST",
        org.name,
        (org.branding or {}).get("primary_color"),
    )
    doc.stats(
        [("Visitors checked in", str(ev.visits)), ("People incl. those with them", str(ev.people))]
    )
    doc.note("Tick each person at the assembly point. Call the host if someone is missing.")
    doc.table(
        ["", "Visitor", "Company", "Phone", "+", "Host", "Host phone", "Gate", "In since"],
        [
            [
                BOX,
                r.visitor_name,
                r.visitor_company,
                phone_text(r.visitor_phone),
                f"+{r.accompanying_count}" if r.accompanying_count else "",
                r.host_name,
                phone_text(r.host_phone),
                r.gate_name
                if ev.site_id
                else " / ".join(x for x in (r.site_name, r.gate_name) if x),
                ist(r.checked_in_at, "%I:%M %p"),
            ]
            for r in ev.rows
        ],
        [3, 16, 14, 18, 4, 14, 18, 9, 11],
        font_size=8.5,
    )
    if not ev.rows:
        doc.note("Nobody is checked in.")
    return doc.render()


# ---------- Visit log files ----------

HEADERS = [
    "Date (IST)",
    "Requested (IST)",
    "Visitor",
    "Company",
    "Phone",
    "Host",
    "Department",
    "Site",
    "Gate",
    "Purpose",
    "Note",
    "People with them",
    "Vehicle",
    "Status",
    "Source",
    "Answered (IST)",
    "Wait (s)",
    "Answered via",
    "Checked in (IST)",
    "Checked out (IST)",
    "Checkout",
    "Guard note",
    "Flagged",
]


def _local(dt: datetime | None) -> datetime | None:
    return dt.astimezone(IST).replace(tzinfo=None, microsecond=0) if dt else None


def _values(r: VisitRow) -> list[object]:
    req = _local(r.requested_at)
    return [
        req.date() if req else None,
        req,
        r.visitor_name,
        r.visitor_company,
        r.visitor_phone,
        r.host_name,
        r.department,
        r.site_name,
        r.gate_name,
        r.purpose,
        r.purpose_note,
        r.accompanying_count,
        r.vehicle_number,
        r.status,
        r.source,
        _local(r.responded_at),
        r.wait_seconds,
        r.response_channel,
        _local(r.checked_in_at),
        _local(r.checked_out_at),
        r.checkout_method,
        r.guard_note,
        "yes" if r.flagged else "",
    ]


def _safe(v: object) -> str:
    """Stop spreadsheet formula injection: a visitor could type "=HYPERLINK(...)"."""
    s = "" if v is None else v.isoformat(sep=" ") if isinstance(v, datetime) else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def visits_csv(rows: list[VisitRow]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HEADERS)
    for r in rows:
        w.writerow([_safe(v) for v in _values(r)])
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM: Excel then shows Hindi right


def visits_xlsx(rows: list[VisitRow]) -> bytes:
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Visits")
    ws.freeze_panes = "A2"
    bold = Font(bold=True)
    from openpyxl.cell import WriteOnlyCell

    head = []
    for h in HEADERS:
        c = WriteOnlyCell(ws, value=h)
        c.font = bold
        head.append(c)
    ws.append(head)
    for r in rows:
        ws.append(
            [
                v if isinstance(v, int | float | datetime | date) or v is None else _safe(v)
                for v in _values(r)
            ]
        )
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _describe(f: VisitFilters) -> str:
    parts = []
    if f.from_date or f.to_date:
        parts.append(f"{f.from_date or '…'} to {f.to_date or '…'}")
    if f.status:
        parts.append("status: " + ", ".join(f.status))
    if f.q:
        parts.append(f"search: “{f.q}”")
    return " · ".join(parts) or "All visits"


def visits_pdf(org: Organization, rows: list[VisitRow], f: VisitFilters) -> bytes:
    doc = Doc(
        "Visit log",
        _describe(f),
        org.name,
        (org.branding or {}).get("primary_color"),
        landscape=True,
    )
    doc.table(
        [
            "Requested",
            "Visitor",
            "Company",
            "Host",
            "Site / gate",
            "Purpose",
            "Status",
            "In",
            "Out",
            "Wait",
        ],
        [
            [
                ist(r.requested_at, "%d %b, %I:%M %p"),
                r.visitor_name,
                r.visitor_company,
                r.host_name,
                " / ".join(x for x in (r.site_name, r.gate_name) if x),
                r.purpose,
                r.status.replace("_", " ") + (" ⚑" if r.flagged else ""),
                ist(r.checked_in_at, "%I:%M %p"),
                ist(r.checked_out_at, "%I:%M %p"),
                duration(r.wait_seconds),
            ]
            for r in rows
        ],
        [13, 15, 13, 13, 14, 11, 9, 7, 7, 6],
    )
    if not rows:
        doc.note("No visits match these filters.")
    return doc.render()


# ---------- Report PDF ----------


async def report_pdf(db: AsyncSession, org: Organization, f: VisitFilters) -> bytes:
    t_default = now().astimezone(IST).date()
    to = f.to_date or t_default
    fr = f.from_date or to - timedelta(days=29)
    site = await db.get(Site, f.site_id) if f.site_id else None
    tr = await reports.traffic(db, fr, to, f.site_id)
    ph = await reports.peak_hours(db, fr, to, f.site_id)
    hosts = await reports.top_hosts(db, fr, to, f.site_id)
    depts = await reports.departments(db, fr, to, f.site_id)
    ap = await reports.approval_times(db, fr, to, f.site_id)

    doc = Doc(
        "Visitor report",
        f"{fr:%d %b %Y} – {to:%d %b %Y} · {site.name if site else 'All sites'}",
        org.name,
        (org.branding or {}).get("primary_color"),
    )
    t = tr.totals
    doc.stats(
        [
            ("Visits", str(t["visits"])),
            ("People", str(t["people"])),
            ("Unique visitors", str(t["unique_visitors"])),
            ("Median host answer", duration(ap.median_seconds)),
        ]
    )
    doc.heading("Visits per day")
    doc.bars([(f"{p.day:%d %b}", p.checked_in) for p in tr.days])
    doc.note(
        f"Requests {t['requests']} · declined {t['rejected']} · expired {t['expired']} · "
        f"cancelled {t['cancelled']} · flagged by blacklist {t['flagged']}"
    )
    doc.heading("Check-ins by hour of day (IST)")
    doc.bars([(f"{h:02d}", sum(ph.grid[w][h] for w in range(7))) for h in range(24)], height=36)
    if ph.busiest:
        b = ph.busiest
        doc.note(
            f"Busiest: {WEEKDAYS[b['weekday']]} {b['hour']:02d}:00–{b['hour'] + 1:02d}:00 "
            f"({b['check_ins']} check-ins)"
        )
    doc.heading("How fast hosts answer")
    doc.bars([(b["label"], b["count"]) for b in ap.buckets], height=30)
    doc.note(
        f"{ap.answered} answered (WhatsApp {ap.by_channel['whatsapp']}, web "
        f"{ap.by_channel['web']}) · 90% within {duration(ap.p90_seconds)} · "
        f"{ap.unanswered} never answered · {ap.escalated} went to a backup host · "
        f"{ap.overrides} let in by security"
    )
    doc.heading("Top hosts")
    doc.table(
        ["Host", "Department", "Visits", "Approved", "Median answer"],
        [
            [h.host_name, h.department, h.visits, h.approved, duration(h.median_wait_seconds)]
            for h in hosts
        ],
        [30, 25, 12, 12, 16],
    )
    doc.heading("Visits by department")
    doc.hbars([(d.department, d.visits) for d in depts[:15]])
    doc.heading("Purpose of visit")
    doc.hbars([(p["label"], p["visits"]) for p in tr.by_purpose])
    src = tr.by_source
    doc.note(
        f"Self check-in {src['qr_self']} · at the desk {src['guard_manual']} · "
        f"pre-approved invites {src['invite']}"
    )
    return doc.render()


# ---------- Jobs ----------


EXT = {"visits_csv": "csv", "visits_xlsx": "xlsx", "visits_pdf": "pdf", "report_pdf": "pdf"}


async def build(db: AsyncSession, org: Organization, job: ExportJob) -> tuple[bytes, int | None]:
    f = VisitFilters.model_validate(job.filters)
    if job.kind == "report_pdf":
        return await report_pdf(db, org, f), None
    cap = MAX_ROWS[job.kind]
    rows = await visit_log.all_rows(db, f, cap + 1)
    if len(rows) > cap:
        raise ValueError(f"More than {cap:,} visits match. Narrow the filters (e.g. dates).")
    data = {
        "visits_csv": lambda: visits_csv(rows),
        "visits_xlsx": lambda: visits_xlsx(rows),
        "visits_pdf": lambda: visits_pdf(org, rows, f),
    }[job.kind]()
    return data, len(rows)


async def run_job(job_id: UUID) -> str:
    async with system_session() as s:
        job = await s.get(ExportJob, job_id)
        if job is None or job.status != "queued":
            return "skipped"
        org_id = job.org_id
        job.status, job.started_at = "running", now()
        await s.commit()
    try:
        async with tenant_session(org_id) as db:
            job = await db.get(ExportJob, job_id)
            org = await db.get(Organization, org_id)
            assert job and org
            data, count = await build(db, org, job)
            ext = EXT[job.kind]
            stamp = now().astimezone(IST)
            name = f"{job.kind.split('_')[0]}-{stamp:%Y%m%d-%H%M}.{ext}"
            key = f"orgs/{org_id}/exports/{job.id}.{ext}"
            await storage.put(key, data, CONTENT_TYPES[ext])
            job.status, job.file_key, job.file_name, job.row_count = "done", key, name, count
            job.finished_at, job.expires_at = now(), now() + TTL
            await db.commit()
        return "done"
    except Exception as exc:  # noqa: BLE001
        log.exception("export %s failed", job_id)
        async with system_session() as s:
            await s.execute(
                update(ExportJob)
                .where(ExportJob.id == job_id)
                .values(
                    status="failed",
                    error=str(exc)[:500]
                    if isinstance(exc, ValueError)
                    else "Something went wrong building this file",
                    finished_at=now(),
                )
            )
            await s.commit()
        return "failed"


_tasks: set[asyncio.Task] = set()


async def start(job_id: UUID) -> None:
    s = get_settings()
    if s.env == "test":
        await run_job(job_id)  # deterministic in tests
    elif s.run_jobs_in_process:
        task = asyncio.create_task(run_job(job_id))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    else:
        from app.workers.queue import enqueue

        await enqueue("run_export", str(job_id))


async def purge_expired() -> int:
    """Delete files of exports past their expiry."""
    async with system_session() as s:
        jobs = list(
            (
                await s.execute(
                    select(ExportJob)
                    .where(ExportJob.status == "done", ExportJob.expires_at <= now())
                    .limit(100)
                )
            ).scalars()
        )
        for j in jobs:
            if j.file_key:
                try:
                    await storage.delete(j.file_key)
                except Exception:  # noqa: BLE001
                    log.exception("could not delete %s", j.file_key)
                    continue
            j.status, j.file_key = "expired", None
        await s.commit()
    return len(jobs)
