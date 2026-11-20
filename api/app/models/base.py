from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, MetaData, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.core.ids import uuid7

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    # Fetch server-generated values (created_at/updated_at) via RETURNING right away,
    # so async code never triggers an implicit lazy load.
    __mapper_args__ = {"eager_defaults": True}


class IdTimestamps:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class OrgScoped:
    """Marker: rows belong to one org. Tenant sessions automatically add
    ``WHERE org_id = :current_org`` to every ORM query on these classes."""

    org_id: Mapped[UUID] = mapped_column(nullable=False)


class TenantMixin(OrgScoped, IdTimestamps):
    """Tenant-owned row. RLS policy is created in the migration for every table using this.

    ``(org_id, id)`` is unique so child tables can use composite FKs: the database
    then refuses to link a row to a parent in a different organization.
    """

    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )

    @declared_attr.directive
    def __table_args__(cls):  # noqa: N805
        extra = getattr(cls, "__extra_table_args__", ())
        return (UniqueConstraint("org_id", "id"), *extra)


TENANT_TABLES: list[str] = []  # filled by app.models.__init__
