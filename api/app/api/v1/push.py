"""Web push alerts: a staff member's browser subscribes here (see app/notifications/push.py)."""

from typing import Annotated

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import delete, func, select

from app.core.deps import StaffUser, SystemDB
from app.models import PushSubscription
from app.notifications import push

router = APIRouter(prefix="/push", tags=["push"])


class PushKeys(BaseModel):
    p256dh: Annotated[str, Field(min_length=20, max_length=200)]
    auth: Annotated[str, Field(min_length=8, max_length=100)]


class SubscriptionIn(BaseModel):
    endpoint: HttpUrl
    keys: PushKeys


class EndpointIn(BaseModel):
    endpoint: HttpUrl


class PushInfo(BaseModel):
    public_key: str
    devices: int


async def _count(db: SystemDB, p: StaffUser) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(PushSubscription)
            .where(PushSubscription.user_id == p.id, PushSubscription.org_id == p.org_id)
        )
        or 0
    )


@router.get("", response_model=PushInfo)
async def push_info(p: StaffUser, db: SystemDB) -> PushInfo:
    return PushInfo(public_key=push.public_key(), devices=await _count(db, p))


@router.post("/subscriptions", response_model=PushInfo, status_code=201)
async def subscribe(body: SubscriptionIn, p: StaffUser, db: SystemDB, request: Request) -> PushInfo:
    # System session: one browser endpoint belongs to whoever subscribed it last, even
    # if that was someone in another org (a shared desk computer).
    endpoint = str(body.endpoint)
    await db.execute(delete(PushSubscription).where(PushSubscription.endpoint == endpoint))
    db.add(
        PushSubscription(
            org_id=p.org_id,
            user_id=p.id,
            endpoint=endpoint,
            p256dh=body.keys.p256dh,
            auth=body.keys.auth,
            user_agent=(request.headers.get("user-agent") or "")[:300],
        )
    )
    await db.commit()
    return PushInfo(public_key=push.public_key(), devices=await _count(db, p))


@router.post("/unsubscribe", response_model=PushInfo)
async def unsubscribe(body: EndpointIn, p: StaffUser, db: SystemDB) -> PushInfo:
    await db.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint == str(body.endpoint), PushSubscription.user_id == p.id
        )
    )
    await db.commit()
    return PushInfo(public_key=push.public_key(), devices=await _count(db, p))


@router.post("/test", response_model=PushInfo)
async def test_push(p: StaffUser, db: SystemDB) -> PushInfo:
    """Send a test alert to all of my browsers."""
    await push.to_user(
        db,
        p.id,
        {
            "title": "Alerts are working",
            "body": "Visitor requests will show up like this.",
            "url": "/host",
            "tag": "test",
        },
    )
    await db.commit()
    return PushInfo(public_key=push.public_key(), devices=await _count(db, p))
