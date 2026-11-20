from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin


class Site(TenantMixin, Base):
    __tablename__ = "sites"

    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    pincode: Mapped[str | None] = mapped_column(String(10))
    lat: Mapped[float | None] = mapped_column(Numeric(9, 6))
    lng: Mapped[float | None] = mapped_column(Numeric(9, 6))
    map_url: Mapped[str | None] = mapped_column(String(500))
    directions_text: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    settings_override: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # [{"name", "phone"}]: who gets the evacuation list on WhatsApp.
    safety_contacts: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(default=True)

    __extra_table_args__ = (Index("uq_sites_org_name", "org_id", text("lower(name)"), unique=True),)


class Gate(TenantMixin, Base):
    __tablename__ = "gates"

    site_id: Mapped[UUID] = mapped_column()
    name: Mapped[str] = mapped_column(String(100))
    # Public, random, rotatable token printed on the poster QR (not a secret signature).
    qr_token: Mapped[str] = mapped_column(String(32), unique=True)
    qr_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(default=True)

    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "site_id"], ["sites.org_id", "sites.id"], ondelete="CASCADE"
        ),
        Index("ix_gates_site", "org_id", "site_id"),
        Index("uq_gates_site_name", "org_id", "site_id", text("lower(name)"), unique=True),
    )


class Department(TenantMixin, Base):
    __tablename__ = "departments"

    name: Mapped[str] = mapped_column(String(120))

    __extra_table_args__ = (
        Index("uq_departments_org_name", "org_id", text("lower(name)"), unique=True),
    )
