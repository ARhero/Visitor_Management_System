from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin
from app.models.visit import _fk, _in

EXPORT_KINDS = ("visits_csv", "visits_xlsx", "visits_pdf", "report_pdf")
EXPORT_STATUSES = ("queued", "running", "done", "failed", "expired")


class ExportJob(TenantMixin, Base):
    """A file built in the background (visit log as CSV / Excel / PDF, report PDF).
    Files live in object storage and are deleted when the job expires."""

    __tablename__ = "export_jobs"

    requested_by: Mapped[UUID | None] = mapped_column()
    kind: Mapped[str] = mapped_column(String(20))
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="queued")
    file_key: Mapped[str | None] = mapped_column(String(300))
    file_name: Mapped[str | None] = mapped_column(String(200))
    row_count: Mapped[int | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __extra_table_args__ = (
        _fk("requested_by", "users", "SET NULL (requested_by)"),
        CheckConstraint(_in("kind", EXPORT_KINDS), name="valid_kind"),
        CheckConstraint(_in("status", EXPORT_STATUSES), name="valid_status"),
        Index("ix_export_jobs_user", "org_id", "requested_by", text("created_at DESC")),
        Index("ix_export_jobs_expiry", "expires_at", postgresql_where=text("status = 'done'")),
    )
