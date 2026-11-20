"""Check-in form configuration: purposes and custom fields."""

from fastapi import APIRouter, Response
from sqlalchemy import func, select

from app.core.deps import AdminUser, StaffUser, TenantDB
from app.core.errors import AppError, conflict
from app.models import CustomField, Purpose, Site
from app.schemas.common import ReorderIn
from app.schemas.config import (
    CustomFieldIn,
    CustomFieldOut,
    CustomFieldUpdate,
    PurposeIn,
    PurposeOut,
    PurposeUpdate,
)
from app.services import audit
from app.services.loaders import FieldPath, PurposePath, load

router = APIRouter(tags=["form config"])


async def _reorder(db, model, ids) -> None:  # noqa: ANN001
    rows = {r.id: r for r in (await db.execute(select(model).where(model.id.in_(ids)))).scalars()}
    if len(rows) != len(set(ids)):
        raise AppError(422, "validation_error", "Unknown id in the list")
    for i, rid in enumerate(ids):
        rows[rid].sort_order = i


# ---------- Purposes ----------


@router.get("/purposes", response_model=list[PurposeOut])
async def list_purposes(
    _: StaffUser, db: TenantDB, include_inactive: bool = False
) -> list[Purpose]:
    q = select(Purpose).order_by(Purpose.sort_order, Purpose.label)
    if not include_inactive:
        q = q.where(Purpose.is_active.is_(True))
    return list((await db.execute(q)).scalars())


@router.post("/purposes", response_model=PurposeOut, status_code=201)
async def create_purpose(body: PurposeIn, p: AdminUser, db: TenantDB) -> Purpose:
    nxt = (
        await db.execute(select(func.coalesce(func.max(Purpose.sort_order), -1) + 1))
    ).scalar_one()
    obj = Purpose(org_id=p.org_id, sort_order=nxt, **body.model_dump())
    db.add(obj)
    await db.flush()
    audit.record(db, p, "purpose.create", "purpose", obj.id, body.model_dump())
    await db.commit()
    return obj


@router.put("/purposes/order", response_model=list[PurposeOut])
async def reorder_purposes(body: ReorderIn, p: AdminUser, db: TenantDB) -> list[Purpose]:
    await _reorder(db, Purpose, body.ids)
    audit.record(db, p, "purpose.reorder", "purpose", None, {"ids": body.ids})
    await db.commit()
    return await list_purposes(p, db, include_inactive=True)


@router.patch("/purposes/{purpose_id}", response_model=PurposeOut)
async def update_purpose(
    p: AdminUser, obj: PurposePath, body: PurposeUpdate, db: TenantDB
) -> Purpose:
    diff = audit.changes(obj, body.model_dump(exclude_unset=True))
    if diff:
        audit.record(db, p, "purpose.update", "purpose", obj.id, diff)
        await db.commit()
        await db.refresh(obj)
    return obj


@router.delete("/purposes/{purpose_id}", status_code=204)
async def deactivate_purpose(p: AdminUser, obj: PurposePath, db: TenantDB) -> Response:
    obj.is_active = False
    audit.record(db, p, "purpose.deactivate", "purpose", obj.id)
    await db.commit()
    return Response(status_code=204)


# ---------- Custom fields ----------


@router.get("/custom-fields", response_model=list[CustomFieldOut])
async def list_fields(
    _: StaffUser, db: TenantDB, include_inactive: bool = False
) -> list[CustomField]:
    q = select(CustomField).order_by(CustomField.sort_order, CustomField.label)
    if not include_inactive:
        q = q.where(CustomField.is_active.is_(True))
    return list((await db.execute(q)).scalars())


@router.post("/custom-fields", response_model=CustomFieldOut, status_code=201)
async def create_field(body: CustomFieldIn, p: AdminUser, db: TenantDB) -> CustomField:
    if body.site_id:
        await load(db, Site, body.site_id, "Site")
    clash = select(CustomField.id).where(CustomField.key == body.key)
    clash = clash.where(
        CustomField.site_id.is_(None)
        if body.site_id is None
        else CustomField.site_id == body.site_id
    )
    if (await db.execute(clash)).first():
        raise conflict(f"A field with key '{body.key}' already exists here")
    nxt = (
        await db.execute(select(func.coalesce(func.max(CustomField.sort_order), -1) + 1))
    ).scalar_one()
    obj = CustomField(org_id=p.org_id, sort_order=nxt, **body.model_dump())
    db.add(obj)
    await db.flush()
    audit.record(db, p, "custom_field.create", "custom_field", obj.id, body.model_dump())
    await db.commit()
    return obj


@router.put("/custom-fields/order", response_model=list[CustomFieldOut])
async def reorder_fields(body: ReorderIn, p: AdminUser, db: TenantDB) -> list[CustomField]:
    await _reorder(db, CustomField, body.ids)
    audit.record(db, p, "custom_field.reorder", "custom_field", None, {"ids": body.ids})
    await db.commit()
    return await list_fields(p, db, include_inactive=True)


@router.patch("/custom-fields/{field_id}", response_model=CustomFieldOut)
async def update_field(
    p: AdminUser, obj: FieldPath, body: CustomFieldUpdate, db: TenantDB
) -> CustomField:
    data = body.model_dump(exclude_unset=True)
    if obj.type == "select" and "options" in data and len(data["options"] or []) < 2:
        raise AppError(422, "validation_error", "A dropdown needs at least two options")
    if obj.type != "select":
        data.pop("options", None)
    if obj.type == "declaration":
        data.pop("required", None)
    diff = audit.changes(obj, data)
    if diff:
        audit.record(db, p, "custom_field.update", "custom_field", obj.id, diff)
        await db.commit()
        await db.refresh(obj)
    return obj


@router.delete("/custom-fields/{field_id}", status_code=204)
async def deactivate_field(p: AdminUser, obj: FieldPath, db: TenantDB) -> Response:
    obj.is_active = False
    audit.record(db, p, "custom_field.deactivate", "custom_field", obj.id)
    await db.commit()
    return Response(status_code=204)
