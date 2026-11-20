from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal
from app.models import AuditLog


def _jsonable(v: Any) -> Any:
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple | set | frozenset):
        return [_jsonable(x) for x in v]
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def changes(obj: Any, data: dict[str, Any]) -> dict[str, Any]:
    """Apply ``data`` to ``obj`` and return {field: [old, new]} for changed fields."""
    diff: dict[str, Any] = {}
    for k, new in data.items():
        old = getattr(obj, k)
        if old != new:
            diff[k] = [_jsonable(old), _jsonable(new)]
            setattr(obj, k, new)
    return diff


def record(
    db: AsyncSession,
    actor: Principal,
    action: str,
    entity_type: str,
    entity_id: UUID | None,
    diff: dict[str, Any] | None = None,
    org_id: UUID | None = None,
) -> None:
    """Add an audit entry to the current transaction (committed with the change)."""
    db.add(
        AuditLog(
            org_id=org_id or actor.org_id,
            actor_user_id=actor.id,
            actor_type="platform" if actor.is_platform else "user",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            diff=_jsonable(diff or {}),
            ip=actor.ip,
            user_agent=actor.user_agent,
        )
    )
