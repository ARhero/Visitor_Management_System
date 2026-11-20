"""Database engines and sessions.

Tenant isolation has two layers:

1. Application: every tenant query goes through a session bound to one org
   (``session.info["org_id"]``) and handlers load resources via helpers that
   filter by org.
2. Database: Row-Level Security on every tenant table. The policy compares the
   row's ``org_id`` with the transaction-local setting ``app.org_id``. The
   ``after_begin`` hook below re-applies that setting at the start of *every*
   transaction on the session, so it survives intermediate commits. If it is
   missing, the policy evaluates to NULL and no rows are visible (fails closed).
"""

from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.core.config import get_settings

_app_engine: AsyncEngine | None = None
_admin_engine: AsyncEngine | None = None


def app_engine() -> AsyncEngine:
    global _app_engine
    if _app_engine is None:
        s = get_settings()
        _app_engine = create_async_engine(s.database_url, echo=s.db_echo, pool_pre_ping=True)
    return _app_engine


def admin_engine() -> AsyncEngine:
    global _admin_engine
    if _admin_engine is None:
        s = get_settings()
        _admin_engine = create_async_engine(
            s.database_admin_url, echo=s.db_echo, pool_pre_ping=True
        )
    return _admin_engine


async def dispose_engines() -> None:
    global _app_engine, _admin_engine
    for eng in (_app_engine, _admin_engine):
        if eng is not None:
            await eng.dispose()
    _app_engine = _admin_engine = None


@event.listens_for(Session, "after_begin")
def _apply_tenant(session: Session, transaction, connection) -> None:  # noqa: ANN001
    org_id = session.info.get("org_id")
    if org_id is not None:
        connection.execute(
            text("SELECT set_config('app.org_id', :org, true)"), {"org": str(org_id)}
        )


@event.listens_for(Session, "do_orm_execute")
def _scope_queries(state: ORMExecuteState) -> None:
    """Layer 1: every ORM SELECT/UPDATE/DELETE on an org-scoped model in a tenant
    session gets ``org_id = <current org>`` added automatically (including joins
    and relationship loads), so a handler cannot forget the filter."""
    org_id = state.session.info.get("org_id")
    if org_id is None or not (state.is_select or state.is_update or state.is_delete):
        return
    from app.models.base import OrgScoped

    state.statement = state.statement.options(
        with_loader_criteria(OrgScoped, lambda cls: cls.org_id == org_id, include_aliases=True)
    )


def tenant_session(org_id: UUID) -> AsyncSession:
    """Session on the restricted role, bound to a single org (RLS enforced)."""
    maker = async_sessionmaker(app_engine(), expire_on_commit=False)
    session = maker()
    session.info["org_id"] = org_id
    return session


def system_session() -> AsyncSession:
    """Session on the owner role (bypasses RLS). Use only where cross-tenant
    access is inherent: login lookup, signup, platform admin, background jobs."""
    maker = async_sessionmaker(admin_engine(), expire_on_commit=False)
    return maker()


async def iter_system_session() -> AsyncIterator[AsyncSession]:
    async with system_session() as s:
        yield s
