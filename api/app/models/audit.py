from typing import Any
from uuid import UUID

from sqlalchemy import Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin


class AuditLog(TenantMixin, Base):
    """Append-only: the app DB role has only INSERT/SELECT on this table."""

    __tablename__ = "audit_logs"

    actor_user_id: Mapped[UUID | None] = mapped_column()
    actor_type: Mapped[str] = mapped_column(String(20))  # user|platform|system
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[UUID | None] = mapped_column()
    diff: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))

    __extra_table_args__ = (Index("ix_audit_org_created", "org_id", "created_at"),)
