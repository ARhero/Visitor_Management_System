from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin

VISIT_STATUSES = (
    "pending",
    "waiting",
    "approved",
    "rejected",
    "checked_in",
    "checked_out",
    "expired",
    "cancelled",
)
VISIT_SOURCES = ("qr_self", "guard_manual", "invite")
ID_TYPES = ("aadhaar", "pan", "driving_licence", "voter_id", "passport", "company_id", "other")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


def _fk(col: str, table: str, ondelete: str | None = None) -> ForeignKeyConstraint:
    """Composite FK so a row can only point at a parent in the same org."""
    return ForeignKeyConstraint(
        ["org_id", col], [f"{table}.org_id", f"{table}.id"], ondelete=ondelete
    )


class Visitor(TenantMixin, Base):
    """A person who visits. Per org: no recognition across tenants."""

    __tablename__ = "visitors"

    phone: Mapped[str | None] = mapped_column(String(20))  # NULL once anonymized
    full_name: Mapped[str | None] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(254))
    last_photo_key: Mapped[str | None] = mapped_column(String(300))
    preferred_locale: Mapped[str] = mapped_column(String(8), default="en")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_visit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    visit_count: Mapped[int] = mapped_column(default=0)
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __extra_table_args__ = (
        Index(
            "uq_visitors_org_phone",
            "org_id",
            "phone",
            unique=True,
            postgresql_where=text("phone IS NOT NULL"),
        ),
    )


class Visit(TenantMixin, Base):
    """One visit. Status only changes through app.services.visit_state."""

    __tablename__ = "visits"

    site_id: Mapped[UUID] = mapped_column()
    gate_id: Mapped[UUID | None] = mapped_column()
    host_id: Mapped[UUID] = mapped_column()
    visitor_id: Mapped[UUID] = mapped_column()
    source: Mapped[str] = mapped_column(String(20), default="qr_self")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    locale: Mapped[str] = mapped_column(String(8), default="en")

    # Snapshot of who came (the visitor record keeps only the latest details).
    visitor_name: Mapped[str | None] = mapped_column(String(200))
    visitor_company: Mapped[str | None] = mapped_column(String(200))
    visitor_phone: Mapped[str | None] = mapped_column(String(20))
    # False when the number was typed in without a code (no WhatsApp): the guard
    # checks the visitor's ID instead.
    phone_verified: Mapped[bool] = mapped_column(default=True, server_default=text("true"))

    purpose_id: Mapped[UUID | None] = mapped_column()
    purpose_note: Mapped[str | None] = mapped_column(String(500))
    accompanying_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    vehicle_number: Mapped[str | None] = mapped_column(String(20))
    custom_values: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    photo_key: Mapped[str | None] = mapped_column(String(300))
    id_type: Mapped[str | None] = mapped_column(String(20))
    id_last4: Mapped[str | None] = mapped_column(String(4))  # never the full number
    id_image_key: Mapped[str | None] = mapped_column(String(300))

    # Approval loop
    current_approver_id: Mapped[UUID | None] = mapped_column()
    # Everyone who was asked; any of them may answer.
    notified_approver_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), default=list
    )
    escalation_level: Mapped[int] = mapped_column(SmallInteger, default=0)
    next_escalation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # end of visit day
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_by: Mapped[UUID | None] = mapped_column()
    response_channel: Mapped[str | None] = mapped_column(String(20))  # whatsapp|web
    host_message: Mapped[str | None] = mapped_column(String(300))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # On site (Phase 3 fills these)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_in_by: Mapped[UUID | None] = mapped_column()
    checked_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_out_by: Mapped[UUID | None] = mapped_column()
    checkout_method: Mapped[str | None] = mapped_column(String(10))

    pass_jti: Mapped[str | None] = mapped_column(String(32), unique=True)
    invite_guest_id: Mapped[UUID | None] = mapped_column()
    blacklist_hit_id: Mapped[UUID | None] = mapped_column()
    # Why a guard let someone in without the host's answer (guard override).
    guard_note: Mapped[str | None] = mapped_column(String(300))
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __extra_table_args__ = (
        _fk("site_id", "sites"),
        _fk("gate_id", "gates", "SET NULL (gate_id)"),
        _fk("host_id", "users"),
        _fk("visitor_id", "visitors"),
        _fk("purpose_id", "purposes", "SET NULL (purpose_id)"),
        _fk("current_approver_id", "users", "SET NULL (current_approver_id)"),
        _fk("responded_by", "users", "SET NULL (responded_by)"),
        _fk("checked_in_by", "users", "SET NULL (checked_in_by)"),
        _fk("checked_out_by", "users", "SET NULL (checked_out_by)"),
        _fk("invite_guest_id", "invite_guests", "SET NULL (invite_guest_id)"),
        _fk("blacklist_hit_id", "blacklist_entries", "SET NULL (blacklist_hit_id)"),
        CheckConstraint(_in("status", VISIT_STATUSES), name="valid_status"),
        CheckConstraint(_in("source", VISIT_SOURCES), name="valid_source"),
        CheckConstraint(f"id_type IS NULL OR {_in('id_type', ID_TYPES)}", name="valid_id_type"),
        CheckConstraint("id_last4 IS NULL OR id_last4 ~ '^[0-9A-Za-z]{4}$'", name="id_last4"),
        CheckConstraint("accompanying_count BETWEEN 0 AND 20", name="accompanying"),
        Index("ix_visits_site_status", "org_id", "site_id", "status"),
        Index("ix_visits_org_requested", "org_id", text("requested_at DESC")),
        Index("ix_visits_host_requested", "org_id", "host_id", text("requested_at DESC")),
        Index("ix_visits_visitor", "org_id", "visitor_id"),
        Index(
            "ix_visits_invite_guest",
            "org_id",
            "invite_guest_id",
            postgresql_where=text("invite_guest_id IS NOT NULL"),
        ),
        Index(
            "ix_visits_checked_in_until",
            "valid_until",
            postgresql_where=text("status = 'checked_in'"),
        ),
        Index(
            "ix_visits_on_site",
            "org_id",
            "site_id",
            postgresql_where=text("status = 'checked_in'"),
        ),
        # The sweeper's queries: escalations due, and open visits past their day.
        Index(
            "ix_visits_escalation_due",
            "next_escalation_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_visits_open_until",
            "valid_until",
            postgresql_where=text("status IN ('pending','waiting','approved')"),
        ),
    )


class VisitEvent(TenantMixin, Base):
    """Every status change, for the timeline and approval-time metrics."""

    __tablename__ = "visit_events"

    visit_id: Mapped[UUID] = mapped_column()
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    actor_type: Mapped[str] = mapped_column(String(10))  # visitor|host|guard|admin|system
    actor_id: Mapped[UUID | None] = mapped_column()
    channel: Mapped[str] = mapped_column(String(10))  # web|whatsapp|system
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    __extra_table_args__ = (
        _fk("visit_id", "visits", "CASCADE"),
        Index("ix_visit_events_visit", "org_id", "visit_id"),
    )


class ConsentNotice(TenantMixin, Base):
    """Versioned privacy notice. A new version is a new row, so we can always show
    exactly what text a visitor agreed to."""

    __tablename__ = "consent_notices"

    version: Mapped[int] = mapped_column()
    locale: Mapped[str] = mapped_column(String(8))
    body: Mapped[str] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(default=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __extra_table_args__ = (
        Index("uq_consent_version", "org_id", "locale", "version", unique=True),
        Index(
            "uq_consent_current",
            "org_id",
            "locale",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )


class ConsentRecord(TenantMixin, Base):
    __tablename__ = "consent_records"

    visitor_id: Mapped[UUID] = mapped_column()
    visit_id: Mapped[UUID | None] = mapped_column()
    notice_id: Mapped[UUID] = mapped_column()
    locale: Mapped[str] = mapped_column(String(8))
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __extra_table_args__ = (
        _fk("visitor_id", "visitors", "CASCADE"),
        _fk("visit_id", "visits", "SET NULL (visit_id)"),
        _fk("notice_id", "consent_notices"),
    )
