import re
import secrets
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.ids import uuid7
from app.core.security import hash_password
from app.models import Gate, Organization, Purpose, User
from app.schemas.org import Branding, OrgSettings
from app.services.consent import default_notices

DEFAULT_PURPOSES: list[tuple[str, str]] = [
    ("Meeting", "बैठक"),
    ("Interview", "साक्षात्कार"),
    ("Vendor / Supplier", "विक्रेता / आपूर्तिकर्ता"),
    ("Delivery", "डिलीवरी"),
    ("Maintenance / Service", "रखरखाव / सेवा"),
    ("Personal", "व्यक्तिगत"),
]


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (s or "org")[:60]


async def unique_slug(db: AsyncSession, name: str) -> str:
    base = slugify(name)
    slug = base
    while (await db.execute(select(Organization.id).where(Organization.slug == slug))).first():
        slug = f"{base}-{secrets.token_hex(2)}"
    return slug


def new_qr_token() -> str:
    return secrets.token_urlsafe(12)  # 16 URL-safe chars, ~96 bits


def checkin_url(gate: Gate) -> str:
    return f"{get_settings().public_web_url.rstrip('/')}/v/{gate.qr_token}"


async def create_org_with_admin(
    db: AsyncSession,
    *,
    name: str,
    admin_name: str,
    admin_email: str,
    admin_password: str,
    admin_phone: str | None = None,
    status: str = "trial",
    data_region: str | None = None,
) -> tuple[Organization, User]:
    """Runs on the system session (the org doesn't exist yet, so no RLS context)."""
    s = get_settings()
    org = Organization(
        id=uuid7(),
        name=name,
        slug=await unique_slug(db, name),
        status=status,
        data_region=data_region or s.default_data_region,
        timezone=s.default_timezone,
        branding=Branding().model_dump(mode="json"),
        settings=OrgSettings().model_dump(mode="json"),
        onboarding={},
    )
    db.add(org)
    await db.flush()
    roles = ["org_admin", "host"] if admin_phone else ["org_admin"]
    admin = User(
        id=uuid7(),
        org_id=org.id,
        full_name=admin_name,
        email=admin_email.lower(),
        phone=admin_phone,
        password_hash=hash_password(admin_password),
        roles=roles,
    )
    db.add(admin)
    db.add_all(default_notices(org.id))
    for i, (en, hi) in enumerate(DEFAULT_PURPOSES):
        db.add(Purpose(org_id=org.id, label=en, label_i18n={"hi": hi}, sort_order=i))
    await db.flush()
    return org, admin


async def email_taken(db: AsyncSession, email: str, org_id: UUID | None = None) -> bool:
    from sqlalchemy import func

    q = select(User.id).where(func.lower(User.email) == email.lower())
    if org_id:
        q = q.where(User.org_id == org_id)
    return (await db.execute(q)).first() is not None
