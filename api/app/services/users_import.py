"""Bulk host import from CSV, with a dry-run preview.

Columns (header row required, case-insensitive, order free):
  full_name*, phone*, email, department, designation, employee_code, site, roles, backup_host_phone

* ``roles``: separated by ``|`` or ``;`` e.g. ``host|guard``. Defaults to ``host``.
* Rows are matched to existing users by phone, then by email: matched rows are updated.
* Unknown departments are created (listed in the preview). Unknown sites are errors.
* Admin/guard roles are not granted by import (they need a password). Use the UI.
"""

import csv
import io
from dataclasses import dataclass, field
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.phone import normalize_phone
from app.models import Department, Site, User
from app.schemas.users import ImportResult, ImportRowResult

MAX_ROWS = 5000
MAX_BYTES = 2 * 1024 * 1024
COLUMNS = [
    "full_name",
    "phone",
    "email",
    "department",
    "designation",
    "employee_code",
    "site",
    "roles",
    "backup_host_phone",
]
ALIASES = {
    "name": "full_name",
    "mobile": "phone",
    "mobile_number": "phone",
    "phone_number": "phone",
    "dept": "department",
    "emp_code": "employee_code",
    "employee_id": "employee_code",
}
IMPORTABLE_ROLES = {"host"}

TEMPLATE_CSV = (
    ",".join(COLUMNS)
    + "\nPriya Sharma,9876543210,priya@example.com,Finance,Manager,EMP001,Head Office,host,\n"
)


@dataclass
class _Row:
    n: int
    data: dict[str, str]
    errors: list[str] = field(default_factory=list)
    phone: str | None = None
    email: str | None = None
    existing: User | None = None


def _parse(raw: bytes) -> list[dict[str, str]]:
    if len(raw) > MAX_BYTES:
        raise AppError(413, "file_too_large", "CSV must be under 2 MB")
    text = None
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise AppError(422, "bad_encoding", "Save the CSV as UTF-8 and try again")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise AppError(422, "empty_csv", "The CSV has no header row")
    headers = {}
    for h in reader.fieldnames:
        key = (h or "").strip().lower().replace(" ", "_")
        headers[h] = ALIASES.get(key, key)
    if "full_name" not in headers.values() or "phone" not in headers.values():
        raise AppError(
            422, "missing_columns", "The CSV needs at least 'full_name' and 'phone' columns"
        )
    rows = []
    for r in reader:
        rows.append({headers[k]: (v or "").strip() for k, v in r.items() if k in headers})
        if len(rows) > MAX_ROWS:
            raise AppError(413, "too_many_rows", f"Import at most {MAX_ROWS} rows at a time")
    return rows


async def run_import(
    db: AsyncSession, org_id: UUID, raw: bytes, *, dry_run: bool
) -> tuple[ImportResult, list[User]]:
    records = _parse(raw)
    users = (await db.execute(select(User))).scalars().all()
    by_phone = {u.phone: u for u in users if u.phone}
    by_email = {u.email.lower(): u for u in users if u.email}
    depts = {d.name.lower(): d for d in (await db.execute(select(Department))).scalars()}
    sites = {s.name.lower(): s for s in (await db.execute(select(Site))).scalars()}

    rows: list[_Row] = []
    seen_phone: dict[str, int] = {}
    seen_email: dict[str, int] = {}
    new_depts: dict[str, str] = {}

    for i, data in enumerate(records, start=2):  # row 1 is the header
        row = _Row(i, data)
        rows.append(row)
        if not any(data.values()):
            continue
        name = data.get("full_name", "")
        if not name:
            row.errors.append("full_name is required")
        elif len(name) > 200:
            row.errors.append("full_name is too long")
        try:
            row.phone = normalize_phone(data.get("phone", ""))
        except ValueError as e:
            row.errors.append(f"phone: {e}")
        if data.get("email"):
            try:
                row.email = validate_email(
                    data["email"], check_deliverability=False
                ).normalized.lower()
            except EmailNotValidError:
                row.errors.append("email is invalid")
        if row.phone:
            if row.phone in seen_phone:
                row.errors.append(f"phone repeats row {seen_phone[row.phone]}")
            seen_phone.setdefault(row.phone, i)
        if row.email:
            if row.email in seen_email:
                row.errors.append(f"email repeats row {seen_email[row.email]}")
            seen_email.setdefault(row.email, i)

        roles_raw = data.get("roles", "").replace(";", "|")
        roles = {r.strip().lower() for r in roles_raw.split("|") if r.strip()} or {"host"}
        if roles - IMPORTABLE_ROLES:
            row.errors.append(
                "only the 'host' role can be imported; add admins and guards in Settings"
            )

        if data.get("site") and data["site"].lower() not in sites:
            row.errors.append(f"site '{data['site']}' does not exist")
        dept = data.get("department", "")
        if dept and dept.lower() not in depts:
            new_depts.setdefault(dept.lower(), dept[:120])

        by_p = by_phone.get(row.phone) if row.phone else None
        by_e = by_email.get(row.email) if row.email else None
        if by_p and by_e and by_p.id != by_e.id:
            row.errors.append("phone and email belong to two different existing people")
        row.existing = by_p or by_e

    # Backup hosts may reference rows in the same file.
    file_phones = {r.phone for r in rows if r.phone and not r.errors}
    for row in rows:
        bp = row.data.get("backup_host_phone")
        if bp and not row.errors:
            try:
                bpn = normalize_phone(bp)
                if bpn == row.phone:
                    row.errors.append("backup host cannot be the same person")
                elif bpn not in by_phone and bpn not in file_phones:
                    row.errors.append("backup_host_phone does not match any host")
            except ValueError:
                row.errors.append("backup_host_phone is invalid")

    results: list[ImportRowResult] = []
    created = updated = errors = 0
    for row in rows:
        if not any(row.data.values()):
            results.append(ImportRowResult(row=row.n, action="skip"))
            continue
        action = "error" if row.errors else ("update" if row.existing else "create")
        created += action == "create"
        updated += action == "update"
        errors += action == "error"
        results.append(
            ImportRowResult(
                row=row.n,
                action=action,
                full_name=row.data.get("full_name"),
                email=row.email,
                phone=row.phone,
                errors=row.errors,
            )
        )

    summary = ImportResult(
        dry_run=dry_run,
        total=len([r for r in rows if any(r.data.values())]),
        created=created,
        updated=updated,
        errors=errors,
        new_departments=sorted(new_depts.values()),
        rows=results,
    )
    if dry_run or errors:
        # All-or-nothing: commit only a file with zero errors.
        summary.dry_run = True
        return summary, []

    for key, name in new_depts.items():
        d = Department(org_id=org_id, name=name)
        db.add(d)
        depts[key] = d
    await db.flush()

    touched: list[User] = []
    for row in rows:
        if not any(row.data.values()):
            continue
        d = row.data
        fields = {
            "full_name": d["full_name"],
            "phone": row.phone,
            "designation": d.get("designation") or None,
            "employee_code": d.get("employee_code") or None,
            "department_id": depts[d["department"].lower()].id if d.get("department") else None,
            "primary_site_id": sites[d["site"].lower()].id if d.get("site") else None,
        }
        if row.email:
            fields["email"] = row.email
        if row.existing:
            u = row.existing
            for k, v in fields.items():
                setattr(u, k, v)
            if "host" not in u.roles:
                u.roles = sorted({*u.roles, "host"})
            u.is_active = True
        else:
            u = User(org_id=org_id, roles=["host"], **fields)
            db.add(u)
            by_phone[row.phone] = u  # type: ignore[index]
        touched.append(u)
    await db.flush()

    for row in rows:
        bp = row.data.get("backup_host_phone")
        if bp and row.phone:
            by_phone[row.phone].backup_host_id = by_phone[normalize_phone(bp)].id
    await db.flush()
    summary.dry_run = False
    return summary, touched
