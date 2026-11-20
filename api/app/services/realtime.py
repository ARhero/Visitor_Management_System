"""Live updates over Redis pub/sub, consumed by SSE endpoints.

Messages are tiny change notices ({"visit": id, "status": ...}); subscribers re-read
the current state from the database, so a missed message is never a stale screen.
"""

import json
import logging
from uuid import UUID

from app.core.redis import get_redis

log = logging.getLogger(__name__)


def visit_channel(visit_id: UUID | str) -> str:
    return f"rt:visit:{visit_id}"


def site_channel(site_id: UUID | str) -> str:
    return f"rt:site:{site_id}"


def org_channel(org_id: UUID | str) -> str:
    return f"rt:org:{org_id}"


async def publish_visit(org_id: UUID, site_id: UUID, visit_id: UUID, status: str) -> None:
    msg = json.dumps({"visit": str(visit_id), "status": status})
    try:
        r = get_redis()
        for ch in (visit_channel(visit_id), site_channel(site_id), org_channel(org_id)):
            await r.publish(ch, msg)
    except Exception:  # noqa: BLE001  (live updates are best-effort; clients also poll)
        log.exception("realtime publish failed")
