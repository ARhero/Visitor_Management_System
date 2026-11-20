"""Blocked / watched people, matched by phone at check-in, scan and walk-in."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BlacklistEntry


async def match(db: AsyncSession, phone: str | None, site_id: UUID) -> BlacklistEntry | None:
    """The strongest active entry for this phone at this site (``block`` beats ``alert``)."""
    if not phone:
        return None
    now = datetime.now(UTC)
    return (
        await db.execute(
            select(BlacklistEntry)
            .where(
                BlacklistEntry.phone == phone,
                BlacklistEntry.is_active.is_(True),
                or_(BlacklistEntry.site_id.is_(None), BlacklistEntry.site_id == site_id),
                or_(BlacklistEntry.expires_at.is_(None), BlacklistEntry.expires_at > now),
            )
            .order_by(case((BlacklistEntry.action == "block", 0), else_=1))
            .limit(1)
        )
    ).scalar_one_or_none()
