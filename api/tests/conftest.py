"""Test harness: real PostgreSQL (RLS must be exercised for real) + in-memory Redis.

DB selection:
  * TEST_DATABASE_ADMIN_URL / TEST_DATABASE_URL set (Docker / CI) -> used as-is.
  * otherwise an embedded server is started via scripts/local_pg.py (no Docker needed).
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if "TEST_DATABASE_ADMIN_URL" not in os.environ:
    sys.path.insert(0, str(ROOT / "scripts"))
    from local_pg import ensure

    _hp = ensure()
    os.environ["TEST_DATABASE_ADMIN_URL"] = f"postgresql+asyncpg://vms:vms@{_hp}/vms_test"
    os.environ["TEST_DATABASE_URL"] = f"postgresql+asyncpg://vms_app:vms_app@{_hp}/vms_test"

os.environ.update(
    ENV="test",
    DATABASE_ADMIN_URL=os.environ["TEST_DATABASE_ADMIN_URL"],
    DATABASE_URL=os.environ["TEST_DATABASE_URL"],
    REDIS_URL="memory://",
    JWT_SECRET="test-secret-0123456789abcdef0123456789abcdef",
    STORAGE_BACKEND="local",
    LOCAL_MEDIA_DIR=str(ROOT / ".media-test"),
    WHATSAPP_PROVIDER="mock",
    WHATSAPP_APP_SECRET="test-app-secret",
    PUBLIC_WEB_URL="http://web.test",
)

subprocess.run(
    [sys.executable, "-m", "alembic", "upgrade", "head"],
    cwd=ROOT,
    check=True,
    env=os.environ.copy(),
)

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.db import admin_engine  # noqa: E402
from app.core.redis import get_redis  # noqa: E402
from app.main import app  # noqa: E402
from tests.factories import Factory  # noqa: E402


@pytest.fixture(autouse=True)
async def _clean_db():
    async with admin_engine().begin() as c:
        tables = (
            (
                await c.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                        "AND tablename <> 'alembic_version'"
                    )
                )
            )
            .scalars()
            .all()
        )
        await c.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))
    await get_redis().flushall()
    yield


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def f(client) -> Factory:
    return Factory(client)
