"""Host approval loop: WhatsApp buttons, web link, escalation, expiry, passes, webhooks."""

import asyncio
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.db import system_session
from app.models import NotificationLog, Visit, VisitEvent, WebhookEvent
from app.notifications import dispatcher, providers
from app.services import visits as visit_svc
from tests.factories import messages

API = "/api/v1"


async def _visit(client, f, *, backup: bool = False, **body):
    o = await f.org()
    site = await f.site(o, "HQ")
    b = await f.user(o, full_name="Backup Host") if backup else None
    host = await f.user(o, full_name="Meera", **({"backup_host_id": b["id"]} if b else {}))
    v = await f.checkin(site["gates"][0]["qr_token"], host["id"], **body)
    assert v["status_code"] == 201, v
    return o, host, v, b


async def tap(client, phone: str, action: str, template: str = "visit_request"):
    """Simulate the host tapping a button on their latest request message."""
    msg = (await messages(phone, template))[0]
    btn = next(b for b in msg.payload["buttons"] if b["id"].endswith("|" + action))
    r = await client.post(
        f"{API}/dev/whatsapp/messages/{msg.id}/reply", json={"button_id": btn["id"]}
    )
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


async def status(client, v):
    r = await client.get(
        f"{API}/public/visits/{v['visit_id']}", headers={"Authorization": f"Bearer {v['token']}"}
    )
    return r.json()


async def test_approve_on_whatsapp_issues_pass(client, f):
    o, host, v, _ = await _visit(client, f)
    assert await tap(client, host["phone"], "approve") == "approve:approved"

    st = await status(client, v)
    assert st["status"] == "approved" and st["pass"]["url"].startswith("http://web.test/p/")
    sent = (await messages(v["phone"], "visit_approved"))[0]
    assert st["pass"]["url"] in sent.payload["text"] and "Meera" in sent.payload["text"]
    assert (await messages(host["phone"], "response_ack"))[0].payload[
        "text"
    ] == "Done: Ravi Kumar approved."

    page = (await client.get(f"{API}/public/passes/{st['pass']['token']}")).json()
    assert (
        page["state"] == "valid"
        and page["visitor_name"] == "Ravi Kumar"
        and page["host_name"] == "Meera"
    )
    assert page["qr_svg"].startswith("<svg") and page["photo_url"]

    async with system_session() as s:
        events = (
            (
                await s.execute(
                    select(VisitEvent)
                    .where(VisitEvent.visit_id == v["visit_id"])
                    .order_by(VisitEvent.created_at)
                )
            )
            .scalars()
            .all()
        )
    assert [(e.from_status, e.to_status, e.channel) for e in events] == [
        (None, "pending", "web"),
        ("pending", "approved", "whatsapp"),
    ]


async def test_pass_tampering_and_states(client, f):
    o, host, v, _ = await _visit(client, f)
    await tap(client, host["phone"], "approve")
    tok = (await status(client, v))["pass"]["token"]
    head, body, sig = tok.split(".")
    forged = f"{head}.{body}.{sig[:-2]}AA"
    assert (await client.get(f"{API}/public/passes/{forged}")).status_code == 404
    assert (await client.get(f"{API}/public/passes/not.a.pass")).status_code == 404
    # A pass signed with a different key is rejected.
    import jwt
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    other = jwt.encode({"jti": "x", "exp": 9999999999}, Ed25519PrivateKey.generate(), "EdDSA")
    assert (await client.get(f"{API}/public/passes/{other}")).status_code == 404

    # Day over: the sweeper expires it and the pass page says so (no QR).
    async with system_session() as s:
        await s.execute(
            update(Visit)
            .where(Visit.id == v["visit_id"])
            .values(valid_until=datetime.now(UTC) - timedelta(minutes=1))
        )
        await s.commit()
    assert await visit_svc.expire_stale() == 1
    page = (await client.get(f"{API}/public/passes/{tok}")).json()
    assert page["state"] == "expired" and page["qr_svg"] is None


async def test_reject_and_wait_via_web_link(client, f):
    o, host, v, _ = await _visit(client, f)
    link = (await messages(host["phone"], "visit_request"))[0].payload["params"]["link"]
    tok = link.rsplit("/", 1)[1]
    view = (await client.get(f"{API}/public/respond/{tok}")).json()
    assert view["can_respond"] and view["visitor_name"] == "Ravi Kumar"

    r = await client.post(
        f"{API}/public/respond/{tok}", json={"action": "wait", "message": "In a meeting, 10 min"}
    )
    assert r.json()["status"] == "waiting"
    assert (
        "In a meeting, 10 min" in (await messages(v["phone"], "visit_waiting"))[0].payload["text"]
    )
    assert (await status(client, v))["host_message"] == "In a meeting, 10 min"

    r = await client.post(f"{API}/public/respond/{tok}", json={"action": "reject"})
    assert r.json()["status"] == "rejected" and not r.json()["can_respond"]
    assert await messages(v["phone"], "visit_rejected")
    r = await client.post(f"{API}/public/respond/{tok}", json={"action": "approve"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"
    assert (await client.get(f"{API}/public/respond/{tok}x")).status_code == 401


async def test_duplicate_webhook_delivery_applies_once(client, f):
    o, host, v, _ = await _visit(client, f)
    msg = (await messages(host["phone"], "visit_request"))[0]
    btn = msg.payload["buttons"][0]["id"]
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "wamid.SAME",
                                    "from": host["phone"][1:],
                                    "type": "button",
                                    "button": {"payload": btn, "text": "Approve"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"test-app-secret", body, hashlib.sha256).hexdigest()
    h = {"x-hub-signature-256": sig, "content-type": "application/json"}
    r1 = await client.post(f"{API}/webhooks/whatsapp", content=body, headers=h)
    r2 = await client.post(f"{API}/webhooks/whatsapp", content=body, headers=h)
    assert r1.json()["results"] == ["approve:approved"] and r2.json()["results"] == ["duplicate"]
    assert len(await messages(v["phone"], "visit_approved")) == 1
    async with system_session() as s:
        n = (
            (
                await s.execute(
                    select(WebhookEvent).where(WebhookEvent.external_id == "msg:wamid.SAME")
                )
            )
            .scalars()
            .all()
        )
    assert len(n) == 1 and n[0].status == "processed"


async def test_webhook_signature_required(client, f):
    body = b'{"entry": []}'
    r = await client.post(f"{API}/webhooks/whatsapp", content=body)
    assert r.status_code == 401
    r = await client.post(
        f"{API}/webhooks/whatsapp",
        content=body,
        headers={"x-hub-signature-256": "sha256=" + "0" * 64},
    )
    assert r.status_code == 401
    ok = await client.get(
        f"{API}/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "dev-verify-token",
            "hub.challenge": "42",
        },
    )
    assert ok.text == "42"
    assert (
        await client.get(
            f"{API}/webhooks/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "no", "hub.challenge": "42"},
        )
    ).status_code == 403


async def test_status_callbacks_update_outbox(client, f):
    o, host, v, _ = await _visit(client, f)
    msg = (await messages(host["phone"], "visit_request"))[0]
    payload = {
        "entry": [
            {
                "changes": [
                    {"value": {"statuses": [{"id": msg.provider_message_id, "status": "read"}]}}
                ]
            }
        ]
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"test-app-secret", body, hashlib.sha256).hexdigest()
    r = await client.post(
        f"{API}/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": sig}
    )
    assert r.json()["results"] == ["status:read"]
    assert (await messages(host["phone"], "visit_request"))[0].status == "read"


async def test_concurrent_approve_and_reject_one_wins(client, f):
    o, host, v, _ = await _visit(client, f)
    msg = (await messages(host["phone"], "visit_request"))[0]
    ids = {b["id"].rsplit("|", 1)[1]: b["id"] for b in msg.payload["buttons"]}
    r = await asyncio.gather(
        client.post(
            f"{API}/dev/whatsapp/messages/{msg.id}/reply", json={"button_id": ids["approve"]}
        ),
        client.post(
            f"{API}/dev/whatsapp/messages/{msg.id}/reply", json={"button_id": ids["reject"]}
        ),
    )
    results = sorted(x.json()["results"][0] for x in r)
    assert len([x for x in results if x.startswith(("approve:", "reject:"))]) == 1
    assert len([x for x in results if x.startswith("too_late:")]) == 1
    async with system_session() as s:
        events = (
            (
                await s.execute(
                    select(VisitEvent).where(
                        VisitEvent.visit_id == v["visit_id"], VisitEvent.from_status == "pending"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(events) == 1


async def test_late_tap_gets_closed_message(client, f):
    o, host, v, _ = await _visit(client, f)
    r = await client.post(
        f"{API}/public/visits/{v['visit_id']}/cancel",
        headers={"Authorization": f"Bearer {v['token']}"},
    )
    assert r.json()["status"] == "cancelled"
    assert await tap(client, host["phone"], "approve") == "too_late:cancelled"
    note = (await messages(host["phone"], "response_too_late"))[0]
    assert "cancelled by the visitor" in note.payload["text"]


async def test_only_asked_people_can_answer(client, f):
    o, host, v, _ = await _visit(client, f)
    other = await f.user(o)
    # Forge a tap from a different employee's phone on Meera's message.
    msg = (await messages(host["phone"], "visit_request"))[0]
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "wamid.X",
                                    "from": other["phone"][1:],
                                    "type": "button",
                                    "button": {"payload": msg.payload["buttons"][0]["id"]},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    from app.notifications.inbound import process_payload

    assert await process_payload(payload) == ["ignored:not_found"]
    assert (await status(client, v))["status"] == "pending"


async def test_escalation_to_backup_then_expiry(client, f):
    o, host, v, backup = await _visit(client, f, backup=True)

    async def make_due():
        async with system_session() as s:
            await s.execute(
                update(Visit)
                .where(Visit.id == v["visit_id"])
                .values(next_escalation_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await s.commit()

    assert await visit_svc.escalate_due() == 0  # not due yet
    await make_due()
    assert await visit_svc.escalate_due() == 1
    esc = (await messages(backup["phone"], "visit_escalated"))[0]
    assert "Meera has not responded" in esc.payload["text"]
    st = await status(client, v)
    assert st["status"] == "pending" and st["escalated"]

    # The backup has no backup of their own: the next timeout expires the visit.
    await make_due()
    assert await visit_svc.escalate_due() == 1
    assert (await status(client, v))["status"] == "expired"
    assert (
        "could not reach Meera" in (await messages(v["phone"], "visit_expired"))[0].payload["text"]
    )


async def test_backup_and_original_host_can_both_answer(client, f):
    o, host, v, backup = await _visit(client, f, backup=True)
    async with system_session() as s:
        await s.execute(
            update(Visit)
            .where(Visit.id == v["visit_id"])
            .values(next_escalation_at=datetime.now(UTC))
        )
        await s.commit()
    await visit_svc.escalate_due()
    assert await tap(client, backup["phone"], "approve", "visit_escalated") == "approve:approved"
    assert await tap(client, host["phone"], "reject") == "too_late:approved"


async def test_host_web_inbox(client, f):
    from tests.factories import bearer

    o, host, v, _ = await _visit(client, f)
    from uuid import UUID

    h = bearer(UUID(host["id"]), o.id, ["host"])
    items = (await client.get(f"{API}/host/visits", headers=h)).json()
    assert [i["id"] for i in items] == [v["visit_id"]]
    r = await client.post(
        f"{API}/host/visits/{v['visit_id']}/respond", json={"action": "approve"}, headers=h
    )
    assert r.json()["status"] == "approved"
    assert (await client.get(f"{API}/host/visits", headers=h)).json() == []
    # Someone who wasn't asked can't answer.
    other = await f.user(o)
    h2 = bearer(UUID(other["id"]), o.id, ["host"])
    r = await client.post(
        f"{API}/host/visits/{v['visit_id']}/respond", json={"action": "reject"}, headers=h2
    )
    assert r.status_code == 404


async def test_failed_sends_are_retried(client, f, monkeypatch):
    calls = {"n": 0}

    async def flaky(self, msg):  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("network down")
        return f"mock-ok-{calls['n']}"

    monkeypatch.setattr(providers.MockWhatsAppProvider, "send", flaky)
    o, host, v, _ = await _visit(client, f)
    async with system_session() as s:
        otp = (
            await s.execute(select(NotificationLog).where(NotificationLog.template_key == "otp"))
        ).scalar_one()
    assert otp.status == "queued" and otp.attempts == 1 and "network down" in otp.error
    # The check-in still went through; the sweeper retries the OTP log row later.
    async with system_session() as s:
        await s.execute(
            update(NotificationLog)
            .where(NotificationLog.id == otp.id)
            .values(next_attempt_at=datetime.now(UTC))
        )
        await s.commit()
    assert await dispatcher.deliver_due() == 1
    async with system_session() as s:
        row = await s.get(NotificationLog, otp.id)
    assert row.status == "sent" and row.attempts == 2


async def test_sse_stream_sends_current_status(client, f):
    o, host, v, _ = await _visit(client, f)
    await tap(client, host["phone"], "reject")  # final: the stream sends one event and ends
    async with client.stream(
        "GET",
        f"{API}/public/visits/{v['visit_id']}/events",
        headers={"Authorization": f"Bearer {v['token']}"},
    ) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = (await r.aread()).decode()
    assert body.startswith("event: status\ndata: ") and '"status":"rejected"' in body


def test_day_end_in_ist():
    s = {"auto_checkout_time": "20:00:00"}
    morning = datetime(2026, 11, 19, 4, 0, tzinfo=UTC)  # 09:30 IST
    assert visit_svc.day_end(s, morning) == datetime(2026, 11, 19, 14, 30, tzinfo=UTC)  # 20:00 IST
    late = datetime(2026, 11, 19, 14, 0, tzinfo=UTC)  # 19:30 IST: less than an hour left
    assert visit_svc.day_end(s, late) == late + timedelta(hours=4)
