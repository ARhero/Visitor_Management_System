from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TenantMixin

ROLES = ("org_admin", "guard", "host")


class User(TenantMixin, Base):
    """Org staff: admins, guards and hosts. One person may hold several roles."""

    __tablename__ = "users"

    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(20))  # E.164
    password_hash: Mapped[str | None] = mapped_column(Text)
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(20)), default=list)
    department_id: Mapped[UUID | None] = mapped_column()
    designation: Mapped[str | None] = mapped_column(String(120))
    employee_code: Mapped[str | None] = mapped_column(String(50))
    primary_site_id: Mapped[UUID | None] = mapped_column()
    backup_host_id: Mapped[UUID | None] = mapped_column()
    is_active: Mapped[bool] = mapped_column(default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __extra_table_args__ = (
        # Composite FKs keep every reference inside the same org.
        ForeignKeyConstraint(
            ["org_id", "department_id"],
            ["departments.org_id", "departments.id"],
            ondelete="SET NULL (department_id)",
        ),
        ForeignKeyConstraint(
            ["org_id", "primary_site_id"],
            ["sites.org_id", "sites.id"],
            ondelete="SET NULL (primary_site_id)",
        ),
        ForeignKeyConstraint(
            ["org_id", "backup_host_id"],
            ["users.org_id", "users.id"],
            ondelete="SET NULL (backup_host_id)",
        ),
        CheckConstraint(
            "roles <@ ARRAY['org_admin','guard','host']::varchar[] AND cardinality(roles) > 0",
            name="valid_roles",
        ),
        CheckConstraint("NOT ('host' = ANY(roles)) OR phone IS NOT NULL", name="host_has_phone"),
        Index(
            "uq_users_org_email",
            "org_id",
            text("lower(email)"),
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
        ),
        Index(
            "uq_users_org_phone",
            "org_id",
            "phone",
            unique=True,
            postgresql_where=text("phone IS NOT NULL"),
        ),
        Index("ix_users_email_lower", text("lower(email)")),
        Index("ix_users_org_name_lower", "org_id", text("lower(full_name)")),
    )


class GuardSiteAssignment(OrgScoped, Base):
    __tablename__ = "guard_site_assignments"

    # org_id comes from OrgScoped; FK is declared below.
    user_id: Mapped[UUID] = mapped_column()
    site_id: Mapped[UUID] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        PrimaryKeyConstraint("user_id", "site_id"),
        ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["org_id", "user_id"], ["users.org_id", "users.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["org_id", "site_id"], ["sites.org_id", "sites.id"], ondelete="CASCADE"
        ),
    )
