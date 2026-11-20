from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdTimestamps, TenantMixin


class NotificationLog(TenantMixin, Base):
    """Outbox + history of every WhatsApp/SMS message, in and out.

    Outgoing messages are written here (status ``queued``) in the same transaction as
    the change that caused them, then delivered after commit. The sweeper retries any
    that are still queued, so a crash between commit and send loses nothing.
    """

    __tablename__ = "notification_logs"

    visit_id: Mapped[UUID | None] = mapped_column()
    recipient_phone: Mapped[str | None] = mapped_column(String(20))  # NULL once anonymized
    recipient_user_id: Mapped[UUID | None] = mapped_column()
    channel: Mapped[str] = mapped_column(String(10), default="whatsapp")
    direction: Mapped[str] = mapped_column(String(3), default="out")  # out|in
    template_key: Mapped[str] = mapped_column(String(50))
    locale: Mapped[str] = mapped_column(String(8), default="en")
    provider: Mapped[str] = mapped_column(String(20))
    provider_message_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(10), default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    # {params, buttons, text}. ``text`` is the rendered message (shown in the dev inbox).
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "visit_id"],
            ["visits.org_id", "visits.id"],
            ondelete="SET NULL (visit_id)",
        ),
        ForeignKeyConstraint(
            ["org_id", "recipient_user_id"],
            ["users.org_id", "users.id"],
            ondelete="SET NULL (recipient_user_id)",
        ),
        CheckConstraint(
            "status IN ('queued','sent','delivered','read','failed','received','skipped')",
            name="valid_status",
        ),
        CheckConstraint("direction IN ('out','in')", name="valid_direction"),
        Index("ix_notifications_visit", "org_id", "visit_id"),
        Index("ix_notifications_phone", "org_id", "recipient_phone", "created_at"),
        Index(
            "ix_notifications_due",
            "next_attempt_at",
            postgresql_where=text("status = 'queued'"),
        ),
    )


class WebhookEvent(IdTimestamps, Base):
    """Platform table (no org): inbound webhook deliveries, deduplicated by provider id.
    The org is resolved from the payload while processing."""

    __tablename__ = "webhook_events"

    provider: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(160))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="received")
    result: Mapped[str | None] = mapped_column(String(200))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    __table_args__ = (Index("uq_webhook_provider_ext", "provider", "external_id", unique=True),)


class WhatsAppContact(IdTimestamps, Base):
    """Platform table (no org): opt-in / opt-out and the 24-hour window, per phone.

    There is one shared WhatsApp number for every org, so a person who sends STOP has
    blocked all of them; this is therefore per phone, not per org.
    """

    __tablename__ = "whatsapp_contacts"

    phone: Mapped[str] = mapped_column(String(20), unique=True)
    opted_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opt_in_source: Mapped[str | None] = mapped_column(String(30))
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PushSubscription(TenantMixin, Base):
    """A browser that asked for web push alerts for a staff member (hosts, mostly).

    One row per browser endpoint. Endpoints the push service reports as gone (404/410)
    are deleted on the next send.
    """

    __tablename__ = "push_subscriptions"

    user_id: Mapped[UUID] = mapped_column()
    endpoint: Mapped[str] = mapped_column(Text)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __extra_table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "user_id"], ["users.org_id", "users.id"], ondelete="CASCADE"
        ),
        Index("uq_push_endpoint", "endpoint", unique=True),
        Index("ix_push_user", "org_id", "user_id"),
    )
