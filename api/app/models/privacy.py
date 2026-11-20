from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin
from app.models.visit import _fk, _in

PRIVACY_REQUEST_STATUSES = ("open", "completed", "rejected")


class PrivacyRequest(TenantMixin, Base):
    """A visitor asking for their data to be erased (DPDP s.12).

    Visitors make these themselves on the privacy page (after a WhatsApp OTP); admins
    resolve them. Once resolved the phone is replaced by a masked copy and a hash, so the
    request stays on record without keeping the number.
    """

    __tablename__ = "privacy_requests"

    kind: Mapped[str] = mapped_column(String(10), default="erasure")
    phone: Mapped[str | None] = mapped_column(String(20))  # NULL once resolved
    phone_masked: Mapped[str] = mapped_column(String(20))
    phone_hash: Mapped[str] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(200))
    reason: Mapped[str | None] = mapped_column(String(500))
    locale: Mapped[str] = mapped_column(String(8), default="en")
    status: Mapped[str] = mapped_column(String(10), default="open")
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[UUID | None] = mapped_column()

    __extra_table_args__ = (
        _fk("resolved_by", "users", "SET NULL (resolved_by)"),
        CheckConstraint(_in("status", PRIVACY_REQUEST_STATUSES), name="valid_status"),
        CheckConstraint("kind IN ('erasure')", name="valid_kind"),
        Index(
            "ix_privacy_requests_open",
            "org_id",
            "created_at",
            postgresql_where=text("status = 'open'"),
        ),
        Index(
            "uq_privacy_requests_one_open",
            "org_id",
            "phone_hash",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )
