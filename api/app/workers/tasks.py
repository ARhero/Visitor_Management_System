"""Background work. Run by the ARQ worker, or inside the API process when there is no
worker (REDIS_URL=memory://, see Settings.run_jobs_in_process)."""

import asyncio
import logging

from app.core.config import get_settings
from app.notifications import dispatcher
from app.services import exports, guard, invites, privacy, visits

log = logging.getLogger(__name__)


async def sweep() -> dict[str, int]:
    """Everything time-based, idempotent and safe to run from several processes:
    retry queued messages, escalate unanswered visits, expire visits whose day is over, check out
    people still inside at the end of the day, close invites that have ended, and apply
    each org's retention period (at most every 6 hours per org)."""
    return {
        "sent": await dispatcher.deliver_due(),
        "escalated": await visits.escalate_due(),
        "expired": await visits.expire_stale(),
        "auto_checked_out": await guard.auto_checkout_due(),
        "invites_expired": await invites.expire_due(),
        "exports_purged": await exports.purge_expired(),
        "retention": await privacy.retention_due(),
    }


async def run_forever() -> None:
    interval = get_settings().sweep_interval_seconds
    while True:
        try:
            await sweep()
        except Exception:  # noqa: BLE001
            log.exception("sweep failed")
        await asyncio.sleep(interval)
