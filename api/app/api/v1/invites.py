"""Pre-approved invites (VIP passes). Hosts manage their own; admins manage all."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, File, Query, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core import rate_limit
from app.core.config import get_settings
from app.core.deps import Principal, StaffUser, TenantDB
from app.core.errors import AppError, forbidden, not_found
from app.models import Invite, InviteGuest, Organization, Purpose, Site, User, Visit
from app.schemas.common import Page
from app.schemas.invites import (
    GuestImportResult,
    GuestIn,
    GuestOut,
    GuestsIn,
    InviteIn,
    InviteOut,
    InviteUpdate,
)
from app.services import audit, passes
from app.services import invites as svc
from app.services.loaders import GuestPath, InvitePath
from app.services.users_import import _parse
from app.services.visits import IST, AfterCommit

router = APIRouter(prefix="/invites", tags=["invites"])


def _can_invite(p: Principal) -> None:
    if not p.has("host", "org_admin"):
        raise forbidden()


def _mine(p: Principal, invite: Invite) -> Invite:
    _can_invite(p)
    if not p.has("org_admin") and invite.host_id != p.id:
        raise not_found("Invite")  # someone else's invite: don't reveal it exists
    return invite


def _guest_of(p: Principal, invite: Invite, guest: InviteGuest) -> InviteGuest:
    _mine(p, invite)
    if guest.invite_id != invite.id:
        raise not_found("Guest")
    return guest


async def _out(db, invites: list[Invite], detail: bool = False) -> list[InviteOut]:  # noqa: ANN001
    if not invites:
        return []
    ids = [i.id for i in invites]
    sites = {
        s.id: s.name
        for s in (
            await db.execute(select(Site).where(Site.id.in_({i.site_id for i in invites})))
        ).scalars()
    }
    hosts = {
        u.id: u.full_name
        for u in (
            await db.execute(select(User).where(User.id.in_({i.host_id for i in invites})))
        ).scalars()
    }
    counts = dict(
        (
            await db.execute(
                select(InviteGuest.invite_id, func.count())
                .where(InviteGuest.invite_id.in_(ids))
                .group_by(InviteGuest.invite_id)
            )
        ).all()
    )
    arrived = dict(
        (
            await db.execute(
                select(InviteGuest.invite_id, func.count(func.distinct(Visit.invite_guest_id)))
                .join(Visit, Visit.invite_guest_id == InviteGuest.id)
                .where(
                    InviteGuest.invite_id.in_(ids), Visit.status.in_(("checked_in", "checked_out"))
                )
                .group_by(InviteGuest.invite_id)
            )
        ).all()
    )
    guests: dict[UUID, list[InviteGuest]] = {}
    org = await db.get(Organization, invites[0].org_id) if detail else None
    if detail:
        for g in (
            await db.execute(
                select(InviteGuest).where(InviteGuest.invite_id.in_(ids)).order_by(InviteGuest.name)
            )
        ).scalars():
            guests.setdefault(g.invite_id, []).append(g)
    out = []
    for i in invites:
        out.append(
            InviteOut(
                id=i.id,
                site_id=i.site_id,
                site_name=sites.get(i.site_id, ""),
                host_id=i.host_id,
                host_name=hosts.get(i.host_id, ""),
                purpose_id=i.purpose_id,
                kind=i.kind,  # type: ignore[arg-type]
                title=i.title,
                notes=i.notes,
                valid_from=i.valid_from,
                valid_until=i.valid_until,
                daily_start_time=i.daily_start_time,
                daily_end_time=i.daily_end_time,
                status=i.status,
                created_via=i.created_via,
                created_at=i.created_at,
                guest_count=counts.get(i.id, 0),
                arrived_count=arrived.get(i.id, 0),
                guests=[
                    GuestOut(
                        id=g.id,
                        name=g.name,
                        phone=g.phone,
                        company=g.company,
                        status=g.status,
                        use_count=g.use_count,
                        max_uses=g.max_uses,
                        last_used_at=g.last_used_at,
                        sent_at=g.sent_at,
                        consented_at=g.consented_at,
                        pass_url=passes.pass_url(svc.pass_token(i, g))
                        if g.status == "active" and i.status == "active"
                        else None,
                        share_text=svc.share_text(
                            org.name,
                            hosts.get(i.host_id, ""),
                            sites.get(i.site_id, ""),
                            i,
                            g,
                            org.default_locale,
                        )
                        if org and g.status == "active" and i.status == "active"
                        else None,
                    )
                    for g in guests.get(i.id, [])
                ]
                if detail
                else None,
            )
        )
    return out


async def _detail(db, invite: Invite) -> InviteOut:  # noqa: ANN001
    return (await _out(db, [invite], detail=True))[0]


@router.get("", response_model=Page[InviteOut])
async def list_invites(
    p: StaffUser,
    db: TenantDB,
    status: Literal["active", "revoked", "expired"] | None = None,
    host_id: UUID | None = None,
    site_id: UUID | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[InviteOut]:
    _can_invite(p)
    stmt = select(Invite)
    if not p.has("org_admin"):
        stmt = stmt.where(Invite.host_id == p.id)
    elif host_id:
        stmt = stmt.where(Invite.host_id == host_id)
    if status:
        stmt = stmt.where(Invite.status == status)
    if site_id:
        stmt = stmt.where(Invite.site_id == site_id)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            func.lower(func.coalesce(Invite.title, "")).like(like)
            | Invite.id.in_(
                select(InviteGuest.invite_id).where(func.lower(InviteGuest.name).like(like))
            )
        )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list(
        (
            await db.execute(stmt.order_by(Invite.valid_from.desc()).limit(limit).offset(offset))
        ).scalars()
    )
    return Page(items=await _out(db, rows), total=total, limit=limit, offset=offset)


@router.post("", response_model=InviteOut, status_code=201)
async def create_invite(body: InviteIn, p: StaffUser, db: TenantDB) -> InviteOut:
    _can_invite(p)
    host_id = body.host_id or p.id
    if host_id != p.id and not p.has("org_admin"):
        raise forbidden("You can only invite guests for yourself")
    host = (await db.execute(select(User).where(User.id == host_id))).scalar_one_or_none()
    if host is None or not host.is_active or "host" not in host.roles:
        raise AppError(422, "invalid_host", "Choose an active host")
    site = (await db.execute(select(Site).where(Site.id == body.site_id))).scalar_one_or_none()
    if site is None or not site.is_active:
        raise AppError(422, "invalid_site", "Choose an active site")
    if (
        body.purpose_id
        and not (await db.execute(select(Purpose.id).where(Purpose.id == body.purpose_id))).first()
    ):
        raise AppError(422, "invalid_purpose", "Choose a purpose")

    start = datetime.combine(body.date, body.start_time, IST)
    last_day = body.end_date or body.date
    end = datetime.combine(last_day, body.end_time, IST)
    if end <= datetime.now(IST):
        raise AppError(422, "in_past", "This invite would already be over")
    multi = body.kind == "multi_day"
    invite = Invite(
        org_id=p.org_id,
        site_id=site.id,
        host_id=host.id,
        purpose_id=body.purpose_id,
        kind=body.kind,
        title=body.title,
        notes=body.notes,
        valid_from=start,
        valid_until=end,
        daily_start_time=body.start_time if multi else None,
        daily_end_time=body.end_time if multi else None,
        status="active",
        created_via="web",
        created_by=p.id,
    )
    db.add(invite)
    await db.flush()
    guests = await svc.add_guests(db, invite, [g.model_dump() for g in body.guests])
    after = AfterCommit()
    if body.send:
        org = await db.get(Organization, p.org_id)
        assert org is not None
        for g in guests:
            await svc.send_pass(db, org, invite, g, after)
    audit.record(
        db,
        p,
        "invite.create",
        "invite",
        invite.id,
        {"kind": body.kind, "guests": len(guests), "host_id": str(host.id)},
    )
    await db.commit()
    await after.run()
    return await _detail(db, invite)


@router.get("/{invite_id}", response_model=InviteOut)
async def get_invite(invite: InvitePath, p: StaffUser, db: TenantDB) -> InviteOut:
    return await _detail(db, _mine(p, invite))


@router.patch("/{invite_id}", response_model=InviteOut)
async def update_invite(
    invite: InvitePath, body: InviteUpdate, p: StaffUser, db: TenantDB
) -> InviteOut:
    _mine(p, invite)
    diff = audit.changes(invite, body.model_dump(exclude_unset=True))
    if diff:
        audit.record(db, p, "invite.update", "invite", invite.id, diff)
        await db.commit()
    return await _detail(db, invite)


@router.post("/{invite_id}/revoke", response_model=InviteOut)
async def revoke_invite(invite: InvitePath, p: StaffUser, db: TenantDB) -> InviteOut:
    _mine(p, invite)
    if invite.status != "active":
        raise AppError(409, "not_active", f"This invite is already {invite.status}")
    invite.status = "revoked"
    after = AfterCommit()
    guests = list(
        (await db.execute(select(InviteGuest).where(InviteGuest.invite_id == invite.id))).scalars()
    )
    for g in guests:
        if g.status == "active":
            g.status = "revoked"
            await svc.tell_cancelled(db, invite, g, after)
    await svc.cancel_open_visits(db, [g.id for g in guests], p.id, after)
    audit.record(db, p, "invite.revoke", "invite", invite.id)
    await db.commit()
    await after.run()
    return await _detail(db, invite)


async def _add(db, p: Principal, invite: Invite, guests: list[dict], send: bool):  # noqa: ANN001, ANN202
    if invite.status != "active":
        raise AppError(409, "not_active", f"This invite is {invite.status}")
    rows = await svc.add_guests(db, invite, guests)
    after = AfterCommit()
    if send:
        org = await db.get(Organization, p.org_id)
        assert org is not None
        for g in rows:
            await svc.send_pass(db, org, invite, g, after)
    if rows:
        audit.record(db, p, "invite.guests_add", "invite", invite.id, {"added": len(rows)})
    await db.commit()
    await after.run()
    return rows


@router.post("/{invite_id}/guests", response_model=InviteOut, status_code=201)
async def add_guests(invite: InvitePath, body: GuestsIn, p: StaffUser, db: TenantDB) -> InviteOut:
    _mine(p, invite)
    await _add(db, p, invite, [g.model_dump() for g in body.guests], body.send)
    return await _detail(db, invite)


@router.get("/guests/template.csv")
async def guests_template(p: StaffUser) -> Response:
    _can_invite(p)
    return Response(
        "full_name,phone,company\nAnita Rao,9876543210,Acme Pvt Ltd\n",
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="guests-template.csv"'},
    )


@router.post("/{invite_id}/guests/import", response_model=GuestImportResult)
async def import_guests(
    invite: InvitePath,
    p: StaffUser,
    db: TenantDB,
    file: Annotated[UploadFile, File()],
    send: bool = True,
) -> GuestImportResult:
    """CSV with ``full_name`` (or ``name``), ``phone`` and optional ``company``.
    Rows with problems are reported and skipped; the rest are added."""
    _mine(p, invite)
    rows = _parse(await file.read(2 * 1024 * 1024 + 1))
    good, errors = [], []
    for n, r in enumerate(rows, start=2):  # row 1 is the header
        try:
            g = GuestIn(
                name=r.get("full_name", ""),
                phone=r.get("phone", ""),
                company=r.get("company") or None,
            )
            good.append(g.model_dump())
        except ValidationError as e:
            errors.append(
                {"row": n, "errors": [x["msg"].replace("Value error, ", "") for x in e.errors()]}
            )
    added = await _add(db, p, invite, good, send) if good else []
    return GuestImportResult(added=len(added), skipped=len(good) - len(added), errors=errors)


@router.post("/{invite_id}/guests/{guest_id}/resend", response_model=GuestOut)
async def resend_pass(invite: InvitePath, guest: GuestPath, p: StaffUser, db: TenantDB) -> GuestOut:
    _guest_of(p, invite, guest)
    if guest.status != "active" or invite.status != "active":
        raise AppError(409, "not_active", "This pass is no longer active")
    if not get_settings().whatsapp_enabled:
        raise AppError(409, "whatsapp_off", "Share the pass from your own WhatsApp instead")
    await rate_limit.hit(f"invite-resend:{guest.id}", limit=3, window_seconds=600)
    org = await db.get(Organization, p.org_id)
    assert org is not None
    after = AfterCommit()
    await svc.send_pass(db, org, invite, guest, after)
    await db.commit()
    await after.run()
    return next(g for g in (await _detail(db, invite)).guests or [] if g.id == guest.id)


@router.post("/{invite_id}/guests/{guest_id}/revoke", response_model=GuestOut)
async def revoke_guest(
    invite: InvitePath, guest: GuestPath, p: StaffUser, db: TenantDB
) -> GuestOut:
    _guest_of(p, invite, guest)
    if guest.status == "active":
        guest.status = "revoked"
        after = AfterCommit()
        await svc.tell_cancelled(db, invite, guest, after)
        await svc.cancel_open_visits(db, [guest.id], p.id, after)
        audit.record(db, p, "invite.guest_revoke", "invite", invite.id, {"guest": guest.name})
        await db.commit()
        await after.run()
    return next(g for g in (await _detail(db, invite)).guests or [] if g.id == guest.id)
