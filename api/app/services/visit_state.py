"""The ONLY place a visit's status changes.

                 ┌──────── waiting ────────┐
                 ▼                          ▼
 [submit] → pending ──approve──► approved ──check-in──► checked_in ──checkout──► checked_out
              │ └──reject──► rejected      │
              ├──(no answer)──► expired ◄──┘ (day over, never arrived)
              └──(visitor cancels)──► cancelled

Each transition locks the row (SELECT … FOR UPDATE), checks the current status and
writes a visit_events row in the same transaction. Two hosts tapping Approve and
Reject at the same moment, or a webhook delivered twice, can never both apply: the
second one sees the new status and gets ``InvalidTransition``.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.models import Visit, VisitEvent

ALLOWED_FROM: dict[str, frozenset[str]] = {
    "waiting": frozenset({"pending"}),
    "approved": frozenset({"pending", "waiting"}),
    "rejected": frozenset({"pending", "waiting"}),
    "expired": frozenset({"pending", "waiting", "approved"}),
    "cancelled": frozenset({"pending", "waiting", "approved"}),
    "checked_in": frozenset({"approved"}),
    "checked_out": frozenset({"checked_in"}),
}
OPEN = frozenset({"pending", "waiting"})  # still waiting for the host
FINAL = frozenset({"rejected", "expired", "cancelled", "checked_out"})


class InvalidTransition(AppError):
    def __init__(self, current: str, to: str) -> None:
        super().__init__(
            409,
            "invalid_transition",
            f"This visit is already {current.replace('_', ' ')}",
            {"current": current, "requested": to},
        )
        self.current = current


async def lock(db: AsyncSession, visit_id: UUID) -> Visit:
    v = (
        await db.execute(
            select(Visit)
            .where(Visit.id == visit_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if v is None:
        raise not_found("Visit")
    return v


async def transition(
    db: AsyncSession,
    visit_id: UUID,
    to: str,
    *,
    actor_type: str,
    channel: str,
    actor_id: UUID | None = None,
    meta: dict[str, Any] | None = None,
    **changes: Any,
) -> Visit:
    v = await lock(db, visit_id)
    if v.status not in ALLOWED_FROM[to]:
        raise InvalidTransition(v.status, to)
    db.add(
        VisitEvent(
            org_id=v.org_id,
            visit_id=v.id,
            from_status=v.status,
            to_status=to,
            actor_type=actor_type,
            actor_id=actor_id,
            channel=channel,
            meta=meta or {},
        )
    )
    v.status = to
    for k, val in changes.items():
        setattr(v, k, val)
    await db.flush()
    return v
