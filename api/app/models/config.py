from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin

FIELD_TYPES = ("text", "number", "select", "checkbox", "declaration")


class Purpose(TenantMixin, Base):
    __tablename__ = "purposes"

    label: Mapped[str] = mapped_column(String(100))
    label_i18n: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)  # {"hi": "बैठक"}
    requires_id_proof: Mapped[bool] = mapped_column(default=False)
    sort_order: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)


class CustomField(TenantMixin, Base):
    """Extra check-in fields, org-wide (site_id NULL) or per site."""

    __tablename__ = "custom_fields"

    site_id: Mapped[UUID | None] = mapped_column()
    key: Mapped[str] = mapped_column(String(50))
    label: Mapped[str] = mapped_column(String(200))
    label_i18n: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    help_i18n: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    type: Mapped[str] = mapped_column(String(20))
    options: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    required: Mapped[bool] = mapped_column(default=False)
    applies_to: Mapped[str] = mapped_column(String(10), default="checkin")  # checkin|invite|both
    sort_order: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)

    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "site_id"], ["sites.org_id", "sites.id"], ondelete="CASCADE"
        ),
        CheckConstraint(
            "type IN ('text','number','select','checkbox','declaration')", name="valid_type"
        ),
        CheckConstraint("applies_to IN ('checkin','invite','both')", name="valid_applies_to"),
        Index(
            "uq_custom_fields_scope_key",
            "org_id",
            text("coalesce(site_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            "key",
            unique=True,
        ),
    )
