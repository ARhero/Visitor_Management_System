"""Visit log, reports and exports.

Admins see everything. A host (without the admin role) sees only their own visits
through the same log endpoints; reports and exports are admin-only."""

from datetime import date, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select

from app.core.deps import AdminUser, Principal, StaffUser, TenantDB
from app.core.errors import AppError, forbidden, not_found
from app.models import (
    BlacklistEntry,
    ConsentNotice,
    ConsentRecord,
    ExportJob,
    Invite,
    InviteGuest,
    NotificationLog,
    User,
    VisitEvent,
)
from app.schemas.reports import (
    ApprovalTimes,
    DepartmentRow,
    ExportIn,
    ExportOut,
    PeakHours,
    TimelineEvent,
    TopHost,
    Traffic,
    VisitDetail,
    VisitFilters,
    VisitPage,
)
from app.services import audit, exports, reports, storage, visit_log
from app.services.loaders import VisitPath, load
from app.services.visits import IST, now

router = APIRouter(tags=["visits"])


def _scope(p: Principal) -> UUID | None:
    """None = all visits (admin); otherwise only this host's."""
    if p.has("org_admin"):
        return None
    if p.has("host"):
        return p.id
    raise forbidden()


def _filters(
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    site_id: UUID | None = None,
    gate_id: UUID | None = None,
    host_id: UUID | None = None,
    department_id: UUID | None = None,
    purpose_id: UUID | None = None,
    status: Annotated[list[str] | None, Query()] = None,
    source: str | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> VisitFilters:
    try:
        return VisitFilters(
            from_date=from_date,
            to_date=to_date,
            site_id=site_id,
            gate_id=gate_id,
            host_id=host_id,
            department_id=department_id,
            purpose_id=purpose_id,
            status=status or [],
            source=source,
            q=q,  # type: ignore[arg-type]
        )
    except ValueError as exc:
        raise AppError(422, "invalid_filters", str(exc).split("\n")[-1]) from exc


Filters = Annotated[VisitFilters, Depends(_filters)]


@router.get("/visits", response_model=VisitPage)
async def visit_log_page(
    p: StaffUser,
    db: TenantDB,
    f: Filters,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> VisitPage:
    items, nxt, total = await visit_log.page(db, f, limit=limit, cursor=cursor, host_only=_scope(p))
    return VisitPage(items=items, next_cursor=nxt, total=total)


@router.get("/visits/{visit_id}", response_model=VisitDetail)
async def visit_detail(visit: VisitPath, p: StaffUser, db: TenantDB) -> VisitDetail:
    host_only = _scope(p)
    blocked = visit.status == "rejected" and not visit.responded_by and visit.blacklist_hit_id
    if host_only and (visit.host_id != host_only or blocked):
        raise not_found("Visit")
    row = (
        await db.execute(visit_log.base_query(VisitFilters()).where(visit_log.Visit.id == visit.id))
    ).one()
    base = visit_log.to_row(row)
    events = list(
        (
            await db.execute(
                select(VisitEvent)
                .where(VisitEvent.visit_id == visit.id)
                .order_by(VisitEvent.created_at)
            )
        ).scalars()
    )
    actor_ids = {e.actor_id for e in events if e.actor_id}
    names = (
        {
            u.id: u.full_name
            for u in (await db.execute(select(User).where(User.id.in_(actor_ids)))).scalars()
        }
        if actor_ids
        else {}
    )
    consent = (
        await db.execute(
            select(ConsentRecord, ConsentNotice.version)
            .join(ConsentNotice, ConsentNotice.id == ConsentRecord.notice_id)
            .where(ConsentRecord.visit_id == visit.id)
        )
    ).first()
    msgs = (
        await db.execute(
            select(NotificationLog)
            .where(NotificationLog.visit_id == visit.id)
            .order_by(NotificationLog.created_at)
        )
    ).scalars()
    hit = await db.get(BlacklistEntry, visit.blacklist_hit_id) if visit.blacklist_hit_id else None
    invite_title = None
    if visit.invite_guest_id:
        g = await db.get(InviteGuest, visit.invite_guest_id)
        inv = await db.get(Invite, g.invite_id) if g else None
        invite_title = inv.title if inv else None
    return VisitDetail(
        **base.model_dump(),
        photo_url=await storage.signed_url(visit.photo_key),
        id_type=visit.id_type,
        id_last4=visit.id_last4,
        custom_values=visit.custom_values or {},
        host_message=visit.host_message,
        invite_title=invite_title,
        alert_reason=hit.reason if hit and not host_only else None,
        consent={
            "version": consent[1],
            "locale": consent[0].locale,
            "at": consent[0].consented_at.isoformat(),
        }
        if consent
        else None,
        timeline=[
            TimelineEvent(
                at=e.created_at,
                from_status=e.from_status,
                to_status=e.to_status,
                actor_type=e.actor_type,
                actor_name=names.get(e.actor_id),
                channel=e.channel,
                meta=e.meta or {},
            )
            for e in events
        ],
        messages=[
            {
                "at": m.created_at.isoformat(),
                "template": m.template_key,
                "direction": m.direction,
                "status": m.status,
                "to": "••" + m.recipient_phone[-4:] if m.recipient_phone else None,
            }
            for m in msgs
        ],
    )


# ---------- Reports (admin) ----------


def _range(
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    site_id: UUID | None = None,
) -> tuple[date, date, UUID | None]:
    to = to_date or now().astimezone(IST).date()
    fr = from_date or to - timedelta(days=29)  # default: the last 30 days
    if fr > to:
        raise AppError(422, "invalid_filters", "'to' must be on or after 'from'")
    if (to - fr).days > 366:
        raise AppError(422, "invalid_filters", "Choose at most 366 days")
    return fr, to, site_id


Range = Annotated[tuple[date, date, UUID | None], Depends(_range)]


async def _check_site(db, site_id: UUID | None) -> None:  # noqa: ANN001
    if site_id:
        from app.models import Site

        await load(db, Site, site_id, "Site")


@router.get("/reports/traffic", response_model=Traffic)
async def r_traffic(_: AdminUser, db: TenantDB, r: Range) -> Traffic:
    await _check_site(db, r[2])
    return await reports.traffic(db, *r)


@router.get("/reports/peak-hours", response_model=PeakHours)
async def r_peak(_: AdminUser, db: TenantDB, r: Range) -> PeakHours:
    await _check_site(db, r[2])
    return await reports.peak_hours(db, *r)


@router.get("/reports/top-hosts", response_model=list[TopHost])
async def r_hosts(_: AdminUser, db: TenantDB, r: Range) -> list[TopHost]:
    await _check_site(db, r[2])
    return await reports.top_hosts(db, *r)


@router.get("/reports/departments", response_model=list[DepartmentRow])
async def r_depts(_: AdminUser, db: TenantDB, r: Range) -> list[DepartmentRow]:
    await _check_site(db, r[2])
    return await reports.departments(db, *r)


@router.get("/reports/approval-times", response_model=ApprovalTimes)
async def r_approval(_: AdminUser, db: TenantDB, r: Range) -> ApprovalTimes:
    await _check_site(db, r[2])
    return await reports.approval_times(db, *r)


# ---------- Exports (admin) ----------


def _export_out(j: ExportJob) -> ExportOut:
    return ExportOut(
        id=j.id,
        kind=j.kind,
        status=j.status,
        file_name=j.file_name,
        row_count=j.row_count,
        error=j.error,
        created_at=j.created_at,
        finished_at=j.finished_at,
        expires_at=j.expires_at,
    )


@router.post("/exports", response_model=ExportOut, status_code=202)
async def create_export(body: ExportIn, p: AdminUser, db: TenantDB) -> ExportOut:
    from app.core import rate_limit

    await rate_limit.hit(f"exports:{p.id}", limit=20, window_seconds=3600)
    if body.filters.site_id:
        await _check_site(db, body.filters.site_id)
    job = ExportJob(
        org_id=p.org_id,
        requested_by=p.id,
        kind=body.kind,
        filters=body.filters.model_dump(mode="json"),
        status="queued",
    )
    db.add(job)
    await db.flush()
    # Exports take personal data out of the system: always on record.
    audit.record(
        db,
        p,
        "export.create",
        "export",
        job.id,
        {"kind": body.kind, "filters": body.filters.model_dump(mode="json", exclude_defaults=True)},
    )
    await db.commit()
    await exports.start(job.id)
    await db.refresh(job)
    return _export_out(job)


@router.get("/exports", response_model=list[ExportOut])
async def my_exports(p: AdminUser, db: TenantDB) -> list[ExportOut]:
    rows = (
        await db.execute(
            select(ExportJob)
            .where(ExportJob.requested_by == p.id)
            .order_by(ExportJob.created_at.desc())
            .limit(20)
        )
    ).scalars()
    return [_export_out(j) for j in rows]


async def _job(export_id: UUID, p: AdminUser, db: TenantDB) -> ExportJob:
    j = await load(db, ExportJob, export_id, "Export")
    if j.requested_by != p.id:
        raise not_found("Export")  # one admin's download link isn't another's
    return j


ExportPath = Annotated[ExportJob, Depends(_job)]


@router.get("/exports/{export_id}", response_model=ExportOut)
async def get_export(job: ExportPath) -> ExportOut:
    return _export_out(job)


@router.get("/exports/{export_id}/download")
async def download_export(job: ExportPath) -> Response:
    if job.status != "done" or not job.file_key:
        raise AppError(409, "not_ready", "This file is not ready (or has expired)")
    data = await storage.read(job.file_key)
    ext = job.file_key.rsplit(".", 1)[-1]
    return Response(
        data,
        media_type=exports.CONTENT_TYPES[ext],
        headers={
            "Content-Disposition": f'attachment; filename="{job.file_name}"',
            "Cache-Control": "no-store",
        },
    )
