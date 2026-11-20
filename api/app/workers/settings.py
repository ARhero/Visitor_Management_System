"""ARQ worker: ``arq app.workers.settings.WorkerSettings`` (needs a real Redis)."""

from uuid import UUID

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.notifications import dispatcher
from app.workers.tasks import sweep


async def heartbeat(ctx: dict) -> str:  # noqa: ARG001
    return "ok"


async def deliver_notifications(ctx: dict, ids: list[str]) -> int:  # noqa: ARG001
    return await dispatcher.deliver([UUID(i) for i in ids])


async def run_export(ctx: dict, job_id: str) -> str:  # noqa: ARG001
    from app.services.exports import run_job

    return await run_job(UUID(job_id))


async def sweep_job(ctx: dict) -> dict[str, int]:  # noqa: ARG001
    return await sweep()


_url = get_settings().redis_url
if _url.startswith("memory://"):
    raise RuntimeError("The worker needs a real Redis (REDIS_URL=redis://...), not memory://")


class WorkerSettings:
    functions = [heartbeat, deliver_notifications, run_export]
    cron_jobs = [cron(sweep_job, second={0, 15, 30, 45}, run_at_startup=True, unique=True)]
    redis_settings = RedisSettings.from_dsn(_url)
