from datetime import datetime, time
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, String, Time, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin
from app.models.visit import _fk, _in

INVITE_KINDS = ("single", "multi_day", "group")
INVITE_STATUSES = ("active", "revoked", "expired")
GUEST_STATUSES = ("active", "revoked", "used")
BLACKLIST_ACTIONS = ("block", "alert")


class Invite(TenantMixin, Base):
    """A pre-approved visit set up by a host (or an admin on their behalf).

    single: one guest, one entry. group: many guests, one entry each.
    multi_day: entry once per day between valid_from and valid_until, inside the
    daily window. Guests show their pass at the gate; no host approval is needed.
    """

    __tablename__ = "invites"

    site_id: Mapped[UUID] = mapped_column()
    host_id: Mapped[UUID] = mapped_column()
    purpose_id: Mapped[UUID | None] = mapped_column()
    kind: Mapped[str] = mapped_column(String(10))
    title: Mapped[str | None] = mapped_column(String(200))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    daily_start_time: Mapped[time | None] = mapped_column(Time)  # IST, multi_day only
    daily_end_time: Mapped[time | None] = mapped_column(Time)
    notes: Mapped[str | None] = mapped_column(String(500))  # shown to the guard
    status: Mapped[str] = mapped_column(String(10), default="active")
    created_via: Mapped[str] = mapped_column(String(10), default="web")  # web|csv
    created_by: Mapped[UUID | None] = mapped_column()

    __extra_table_args__ = (
        _fk("site_id", "sites"),
        _fk("host_id", "users"),
        _fk("purpose_id", "purposes", "SET NULL (purpose_id)"),
        _fk("created_by", "users", "SET NULL (created_by)"),
        CheckConstraint(_in("kind", INVITE_KINDS), name="valid_kind"),
        CheckConstraint(_in("status", INVITE_STATUSES), name="valid_status"),
        CheckConstraint("valid_until > valid_from", name="valid_window"),
        CheckConstraint(
            "(daily_start_time IS NULL) = (daily_end_time IS NULL)", name="daily_window_pair"
        ),
        Index("ix_invites_host", "org_id", "host_id", text("valid_from DESC")),
        Index("ix_invites_site_window", "org_id", "site_id", "valid_until"),
        Index("ix_invites_active_until", "valid_until", postgresql_where=text("status = 'active'")),
    )


class InviteGuest(TenantMixin, Base):
    __tablename__ = "invite_guests"

    invite_id: Mapped[UUID] = mapped_column()
    visitor_id: Mapped[UUID | None] = mapped_column()
    name: Mapped[str | None] = mapped_column(String(200))  # NULL once anonymized
    phone: Mapped[str | None] = mapped_column(String(20))  # NULL once anonymized
    company: Mapped[str | None] = mapped_column(String(200))
    pass_jti: Mapped[str] = mapped_column(String(32), unique=True)
    max_uses: Mapped[int | None] = mapped_column()  # NULL = once per day (multi_day)
    use_count: Mapped[int] = mapped_column(default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), default="active")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __extra_table_args__ = (
        _fk("invite_id", "invites", "CASCADE"),
        _fk("visitor_id", "visitors", "SET NULL (visitor_id)"),
        CheckConstraint(_in("status", GUEST_STATUSES), name="valid_status"),
        Index("uq_invite_guest_phone", "org_id", "invite_id", "phone", unique=True),
        Index("ix_invite_guests_invite", "org_id", "invite_id"),
    )


class BlacklistEntry(TenantMixin, Base):
    """People who must not be let in (``block``) or whose arrival should alert the
    guard (``alert``). Matched by phone, at one site or (site_id NULL) all sites."""

    __tablename__ = "blacklist_entries"

    phone: Mapped[str] = mapped_column(String(20))
    name: Mapped[str | None] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(String(500))
    action: Mapped[str] = mapped_column(String(10), default="block")
    site_id: Mapped[UUID | None] = mapped_column()
    added_by: Mapped[UUID | None] = mapped_column()
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(default=True)

    __extra_table_args__ = (
        _fk("site_id", "sites", "CASCADE"),
        _fk("added_by", "users", "SET NULL (added_by)"),
        CheckConstraint(_in("action", BLACKLIST_ACTIONS), name="valid_action"),
        Index("ix_blacklist_phone", "org_id", "phone", postgresql_where=text("is_active")),
    )
