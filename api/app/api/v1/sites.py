from datetime import UTC, datetime

from fastapi import APIRouter, Response
from sqlalchemy import func, select

from app.core.deps import AdminUser, StaffUser, TenantDB
from app.core.errors import AppError, conflict
from app.models import Department, Gate, Organization, Site, User
from app.schemas.sites import (
    DepartmentIn,
    DepartmentOut,
    GateIn,
    GateOut,
    GateUpdate,
    SiteCreate,
    SiteOut,
    SiteUpdate,
)
from app.services import audit, consent, onboarding, posters, storage
from app.services.loaders import DepartmentPath, GatePath, SitePath
from app.services.orgs import checkin_url, new_qr_token

router = APIRouter(tags=["sites"])


def _gate_out(g: Gate) -> GateOut:
    out = GateOut.model_validate(g)
    out.checkin_url = checkin_url(g)
    return out


async def _site_out(db, site: Site) -> SiteOut:  # noqa: ANN001
    gates = (
        (await db.execute(select(Gate).where(Gate.site_id == site.id).order_by(Gate.created_at)))
        .scalars()
        .all()
    )
    out = SiteOut.model_validate(site)
    out.gates = [_gate_out(g) for g in gates]
    return out


async def _name_free(db, model, name: str, exclude=None, **scope) -> None:  # noqa: ANN001
    q = select(model.id).where(func.lower(model.name) == name.lower())
    for col, val in scope.items():  # e.g. site_id=... for gates
        q = q.where(getattr(model, col) == val)
    if exclude is not None:
        q = q.where(model.id != exclude)
    if (await db.execute(q)).first():
        raise conflict(f"'{name}' already exists")


async def _set_gates_active(db, site: Site, active: bool) -> None:  # noqa: ANN001
    for g in (await db.execute(select(Gate).where(Gate.site_id == site.id))).scalars():
        g.is_active = active


# ---------- Sites ----------


@router.get("/sites", response_model=list[SiteOut])
async def list_sites(_: StaffUser, db: TenantDB, include_inactive: bool = False) -> list[SiteOut]:
    q = select(Site).order_by(Site.name)
    if not include_inactive:
        q = q.where(Site.is_active.is_(True))
    return [await _site_out(db, s) for s in (await db.execute(q)).scalars().all()]


@router.post("/sites", response_model=SiteOut, status_code=201)
async def create_site(body: SiteCreate, p: AdminUser, db: TenantDB) -> SiteOut:
    await _name_free(db, Site, body.name)
    data = body.model_dump(mode="json", exclude={"default_gate_name"})
    site = Site(org_id=p.org_id, **data)
    db.add(site)
    await db.flush()
    if body.default_gate_name:
        db.add(
            Gate(
                org_id=p.org_id,
                site_id=site.id,
                name=body.default_gate_name,
                qr_token=new_qr_token(),
            )
        )
    audit.record(db, p, "site.create", "site", site.id, data)
    await db.commit()
    return await _site_out(db, site)


@router.get("/sites/{site_id}", response_model=SiteOut)
async def get_site(_: StaffUser, site: SitePath, db: TenantDB) -> SiteOut:
    return await _site_out(db, site)


@router.patch("/sites/{site_id}", response_model=SiteOut)
async def update_site(p: AdminUser, site: SitePath, body: SiteUpdate, db: TenantDB) -> SiteOut:
    data = body.model_dump(exclude_unset=True, mode="json")
    if "name" in data:
        await _name_free(db, Site, data["name"], exclude=site.id)
    diff = audit.changes(site, data)
    if diff:
        if "is_active" in diff:  # gates follow their site, both ways
            await _set_gates_active(db, site, site.is_active)
        audit.record(db, p, "site.update", "site", site.id, diff)
        await db.commit()
        await db.refresh(site)
    return await _site_out(db, site)


@router.delete("/sites/{site_id}", status_code=204)
async def deactivate_site(p: AdminUser, site: SitePath, db: TenantDB) -> Response:
    """Sites are deactivated, never hard-deleted: visit history points at them."""
    site.is_active = False
    await _set_gates_active(db, site, False)
    audit.record(db, p, "site.deactivate", "site", site.id)
    await db.commit()
    return Response(status_code=204)


# ---------- Gates ----------


@router.post("/sites/{site_id}/gates", response_model=GateOut, status_code=201)
async def create_gate(p: AdminUser, site: SitePath, body: GateIn, db: TenantDB) -> GateOut:
    await _name_free(db, Gate, body.name, site_id=site.id)
    gate = Gate(
        org_id=p.org_id,
        site_id=site.id,
        name=body.name,
        is_active=body.is_active,
        qr_token=new_qr_token(),
    )
    db.add(gate)
    await db.flush()
    audit.record(db, p, "gate.create", "gate", gate.id, {"site_id": site.id, "name": body.name})
    await db.commit()
    return _gate_out(gate)


@router.get("/gates/{gate_id}", response_model=GateOut)
async def get_gate(_: StaffUser, gate: GatePath) -> GateOut:
    return _gate_out(gate)


@router.patch("/gates/{gate_id}", response_model=GateOut)
async def update_gate(p: AdminUser, gate: GatePath, body: GateUpdate, db: TenantDB) -> GateOut:
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        await _name_free(db, Gate, data["name"], exclude=gate.id, site_id=gate.site_id)
    diff = audit.changes(gate, data)
    if diff:
        audit.record(db, p, "gate.update", "gate", gate.id, diff)
        await db.commit()
        await db.refresh(gate)
    return _gate_out(gate)


@router.post("/gates/{gate_id}/rotate-qr", response_model=GateOut)
async def rotate_gate_qr(p: AdminUser, gate: GatePath, db: TenantDB) -> GateOut:
    """Issue a new poster token. Old posters stop working immediately."""
    gate.qr_token = new_qr_token()
    gate.qr_rotated_at = datetime.now(UTC)
    audit.record(db, p, "gate.rotate_qr", "gate", gate.id)
    await db.commit()
    await db.refresh(gate)
    return _gate_out(gate)


@router.delete("/gates/{gate_id}", status_code=204)
async def deactivate_gate(p: AdminUser, gate: GatePath, db: TenantDB) -> Response:
    gate.is_active = False
    audit.record(db, p, "gate.deactivate", "gate", gate.id)
    await db.commit()
    return Response(status_code=204)


# ---------- QR posters ----------


async def _poster(db, org_id, site: Site, gates: list[Gate]) -> Response:  # noqa: ANN001
    if not gates:
        raise AppError(409, "no_gates", "This site has no active gates")
    org = await db.get(Organization, org_id)
    assert org is not None
    branding = org.branding or {}
    logo = None
    if branding.get("logo_key"):
        try:
            logo = await storage.read(branding["logo_key"])
        except Exception:  # noqa: BLE001
            logo = None  # a poster without a logo beats no poster
    pdf = posters.build(
        org.name,
        branding,
        logo,
        [posters.PosterGate(site.name, g.name, checkin_url(g)) for g in gates],
        int((org.settings or {}).get("retention_days", 90)),
        consent.privacy_url(org),
    )
    await onboarding.mark(db, org, "posters")
    await db.commit()
    name = f"qr-posters-{site.name}" + (f"-{gates[0].name}" if len(gates) == 1 else "")
    safe = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe}.pdf"'},
    )


@router.get("/sites/{site_id}/posters.pdf")
async def site_posters(p: AdminUser, site: SitePath, db: TenantDB) -> Response:
    """One A4 poster per active gate of the site."""
    gates = (
        await db.execute(
            select(Gate)
            .where(Gate.site_id == site.id, Gate.is_active.is_(True))
            .order_by(Gate.name)
        )
    ).scalars()
    return await _poster(db, p.org_id, site, list(gates))


@router.get("/gates/{gate_id}/poster.pdf")
async def gate_poster(p: AdminUser, gate: GatePath, db: TenantDB) -> Response:
    site = await db.get(Site, gate.site_id)
    assert site is not None
    if not gate.is_active:
        raise AppError(409, "gate_inactive", "This gate is deactivated")
    return await _poster(db, p.org_id, site, [gate])


# ---------- Departments ----------


@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(_: StaffUser, db: TenantDB) -> list[DepartmentOut]:
    counts = (
        select(User.department_id, func.count().label("n"))
        .where(User.is_active.is_(True))
        .group_by(User.department_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(Department, func.coalesce(counts.c.n, 0))
            .outerjoin(counts, counts.c.department_id == Department.id)
            .order_by(Department.name)
        )
    ).all()
    out = []
    for d, n in rows:
        o = DepartmentOut.model_validate(d)
        o.user_count = n
        out.append(o)
    return out


@router.post("/departments", response_model=DepartmentOut, status_code=201)
async def create_department(body: DepartmentIn, p: AdminUser, db: TenantDB) -> Department:
    await _name_free(db, Department, body.name)
    d = Department(org_id=p.org_id, name=body.name)
    db.add(d)
    await db.flush()
    audit.record(db, p, "department.create", "department", d.id, {"name": body.name})
    await db.commit()
    return d


@router.patch("/departments/{department_id}", response_model=DepartmentOut)
async def update_department(
    p: AdminUser, dept: DepartmentPath, body: DepartmentIn, db: TenantDB
) -> Department:
    await _name_free(db, Department, body.name, exclude=dept.id)
    diff = audit.changes(dept, {"name": body.name})
    if diff:
        audit.record(db, p, "department.update", "department", dept.id, diff)
        await db.commit()
        await db.refresh(dept)
    return dept


@router.delete("/departments/{department_id}", status_code=204)
async def delete_department(p: AdminUser, dept: DepartmentPath, db: TenantDB) -> Response:
    """Users in the department keep working; their department becomes empty."""
    audit.record(db, p, "department.delete", "department", dept.id, {"name": dept.name})
    await db.delete(dept)
    await db.commit()
    return Response(status_code=204)
