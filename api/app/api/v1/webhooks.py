"""WhatsApp webhooks (Meta Cloud API format) and the dev-only mock inbox."""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import system_session
from app.core.errors import AppError, not_found
from app.models import NotificationLog, Organization
from app.notifications.inbound import process_payload
from app.notifications.providers import verify_meta_signature

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
dev_router = APIRouter(prefix="/dev", tags=["dev"])


@router.get("/whatsapp", include_in_schema=False)
async def verify_subscription(
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
) -> Response:
    if mode == "subscribe" and token == get_settings().whatsapp_verify_token:
        return Response(challenge, media_type="text/plain")
    raise AppError(403, "forbidden", "Verification failed")


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request) -> dict[str, Any]:
    body = await request.body()
    if not verify_meta_signature(body, request.headers.get("x-hub-signature-256")):
        raise AppError(401, "bad_signature", "Invalid signature")
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise AppError(400, "bad_json", "Invalid JSON") from exc
    return {"results": await process_payload(payload)}


# ---------- Dev: mock WhatsApp inbox (ENV=dev/test only) ----------


class DevMessage(BaseModel):
    id: UUID
    org_name: str
    direction: str
    phone: str
    template: str
    text: str
    buttons: list[dict[str, str]]
    status: str
    error: str | None = None
    created_at: datetime
    visit_id: UUID | None


class DevReplyIn(BaseModel):
    button_id: str


class DevInboundIn(BaseModel):
    phone: str
    text: str


@dev_router.get("/whatsapp/messages", response_model=list[DevMessage])
async def dev_messages(
    phone: str | None = None, limit: int = Query(100, le=500)
) -> list[DevMessage]:
    async with system_session() as db:
        q = (
            select(NotificationLog, Organization.name)
            .join(Organization, Organization.id == NotificationLog.org_id)
            .where(NotificationLog.recipient_phone.is_not(None))  # erased: nobody to show
            .order_by(NotificationLog.created_at.desc())
            .limit(limit)
        )
        if phone:
            q = q.where(NotificationLog.recipient_phone == phone)
        rows = (await db.execute(q)).all()
    return [
        DevMessage(
            id=n.id,
            org_name=org,
            direction=n.direction,
            phone=n.recipient_phone,
            template=n.template_key,
            text=(n.payload or {}).get("text", ""),
            buttons=(n.payload or {}).get("buttons", []),
            status=n.status,
            error=n.error,
            created_at=n.created_at,
            visit_id=n.visit_id,
        )
        for n, org in rows
    ]


@dev_router.post("/whatsapp/messages/{message_id}/reply")
async def dev_reply(message_id: UUID, body: DevReplyIn) -> dict[str, Any]:
    """Simulate the recipient tapping a button: builds the webhook payload Meta would
    send and runs it through the same processing as the real webhook."""
    async with system_session() as db:
        n = await db.get(NotificationLog, message_id)
    if n is None or n.direction != "out":
        raise not_found("Message")
    button = next(
        (b for b in (n.payload or {}).get("buttons", []) if b["id"] == body.button_id), None
    )
    if button is None:
        raise AppError(422, "unknown_button", "That message has no such button")
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messages": [
                                {
                                    "id": f"wamid.mock-{uuid4().hex}",
                                    "from": n.recipient_phone.lstrip("+"),
                                    "timestamp": str(int(datetime.now(UTC).timestamp())),
                                    "type": "button",
                                    "button": {"payload": button["id"], "text": button["title"]},
                                }
                            ]
                        },
                    }
                ]
            }
        ],
    }
    return {"results": await process_payload(payload)}


@dev_router.post("/whatsapp/inbound")
async def dev_inbound(body: DevInboundIn) -> dict[str, Any]:
    """Simulate someone typing a message to the business number (e.g. STOP / START)."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messages": [
                                {
                                    "id": f"wamid.mock-{uuid4().hex}",
                                    "from": body.phone.lstrip("+"),
                                    "timestamp": str(int(datetime.now(UTC).timestamp())),
                                    "type": "text",
                                    "text": {"body": body.text},
                                }
                            ]
                        },
                    }
                ]
            }
        ],
    }
    return {"results": await process_payload(payload)}
