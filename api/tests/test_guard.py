"""Guard console: site scoping, scanning, check-in/out with idempotency, override,
walk-ins, blacklist and the end-of-day auto checkout."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update

from app.core.db import system_session
from app.models import Organization, Visit, VisitEvent
from app.services import guard as guard_svc
from tests.factories import bearer, messages, phone, png

API = "/api/v1"


class Gate:
    """One org, one site with a guard assigned and a host."""

    def __init__(self, client, f):
        self.c, self.f = client, f

    async def setup(self, **org_settings):
        self.o = await self.f.org()
        self.site = await self.f.site(self.o, "HQ")
        self.gate_token = self.site["gates"][0]["qr_token"]
        self.host = await self.f.user(self.o, full_name="Meera Iyer")
        self.host_h = bearer(UUID(self.host["id"]), self.o.id, ["host"])
        self.guard, self.gh = await self.f.guard(self.o)
        r = await self.c.put(
            f"{API}/users/{self.guard['id']}/sites",
            json={"site_ids": [self.site["id"]]},
            headers=self.o.h,
        )
        assert r.status_code == 200, r.text
        if org_settings:
            r = await self.c.patch(f"{API}/org", json={"settings": org_settings}, headers=self.o.h)
            assert r.status_code == 200, r.text
        return self

    async def visit(self, approve: bool = True, **body):
        v = await self.f.checkin(self.gate_token, self.host["id"], **body)
        assert v["status_code"] == 201, v
        if approve:
            r = await self.c.post(
                f"{API}/host/visits/{v['visit_id']}/respond",
                json={"action": "approve"},
                headers=self.host_h,
            )
            assert r.status_code == 200, r.text
            st = await self.c.get(
                f"{API}/public/visits/{v['visit_id']}",
                headers={"Authorization": f"Bearer {v['token']}"},
            )
            v["pass"] = st.json()["pass"]["token"]
        return v

    async def scan(self, payload: str, site_id: str | None = None):
        r = await self.c.post(
            f"{API}/guard/scan",
            json={"site_id": site_id or self.site["id"], "payload": payload},
            headers=self.gh,
        )
        assert r.status_code == 200, r.text
        return r.json()

    async def act(self, visit_id: str, action: str, key: str | None = None, **body):
        return await self.c.post(
            f"{API}/guard/visits/{visit_id}/{action}",
            json=body,
            headers=self.gh | {"Idempotency-Key": key or uuid.uuid4().hex},
        )

    async def queue(self):
        r = await self.c.get(f"{API}/guard/queue?site_id={self.site['id']}", headers=self.gh)
        assert r.status_code == 200, r.text
        return r.json()


async def events(visit_id: str) -> list[VisitEvent]:
    async with system_session() as s:
        return list(
            (
                await s.execute(
                    select(VisitEvent)
                    .where(VisitEvent.visit_id == UUID(visit_id))
                    .order_by(VisitEvent.created_at)
                )
            ).scalars()
        )


# ---------- Site scoping ----------


async def test_guard_only_sees_assigned_sites(client, f):
    g = await Gate(client, f).setup()
    other = await f.site(g.o, "Warehouse")
    sites = (await client.get(f"{API}/guard/sites", headers=g.gh)).json()
    assert [s["name"] for s in sites] == ["HQ"] and sites[0]["gates"][0]["name"] == "Main Gate"

    r = await client.get(f"{API}/guard/queue?site_id={other['id']}", headers=g.gh)
    assert r.status_code == 404
    r = await client.post(
        f"{API}/guard/scan", json={"site_id": other["id"], "payload": "x" * 20}, headers=g.gh
    )
    assert r.status_code == 404

    # A visit at the other site is invisible to this guard, and can't be acted on.
    other_v = await f.checkin(other["gates"][0]["qr_token"], g.host["id"])
    assert (await g.act(other_v["visit_id"], "check-in")).status_code == 404
    assert (
        await client.get(f"{API}/guard/visits/{other_v['visit_id']}", headers=g.gh)
    ).status_code == 404

    # Admins see every site; hosts can't use the console at all.
    assert len((await client.get(f"{API}/guard/sites", headers=g.o.h)).json()) == 2
    assert (await client.get(f"{API}/guard/sites", headers=g.host_h)).status_code == 403


# ---------- Scan → check in → check out ----------


async def test_scan_check_in_and_out(client, f):
    g = await Gate(client, f).setup()
    v = await g.visit()

    s = await g.scan(v["pass"])
    assert s["result"] == "ok" and s["visit"]["visitor_name"] == "Ravi Kumar"
    assert s["visit"]["host_name"] == "Meera Iyer" and s["visit"]["photo_url"]
    assert s["visit"]["phone_last4"] == v["phone"][-4:]
    # A pass link (as a handheld scanner might read it) works too.
    assert (await g.scan(f"http://web.test/p/{v['pass']}"))["result"] == "ok"

    q = await g.queue()
    assert [c["id"] for c in q["expected"]] == [v["visit_id"]] and not q["on_site"]

    r = await g.act(v["visit_id"], "check-in", key="k1")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "checked_in" and r.json()["checked_in_at"]
    arrived = (await messages(g.host["phone"], "visitor_arrived"))[0]
    assert arrived.payload["text"] == "Ravi Kumar (Acme Pvt Ltd) has checked in at HQ, Main Gate."

    assert (await g.scan(v["pass"]))["result"] == "inside"
    q = await g.queue()
    assert [c["id"] for c in q["on_site"]] == [v["visit_id"]] and q["people_on_site"] == 1

    r = await g.act(v["visit_id"], "check-out")
    assert r.status_code == 200 and r.json()["checkout_method"] == "guard"
    assert (await g.scan(v["pass"]))["result"] == "used"
    q = await g.queue()
    assert [c["id"] for c in q["left"]] == [v["visit_id"]] and not q["on_site"]

    # Visitor's own pass page says so too.
    page = (await client.get(f"{API}/public/passes/{v['pass']}")).json()
    assert page["state"] == "used" and page["qr_svg"] is None


async def test_check_in_is_idempotent(client, f):
    g = await Gate(client, f).setup()
    v = await g.visit()

    first = await g.act(v["visit_id"], "check-in", key="same-key")
    again = await g.act(v["visit_id"], "check-in", key="same-key")
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()
    assert len(await messages(g.host["phone"], "visitor_arrived")) == 1  # host told once
    assert [e.to_status for e in await events(v["visit_id"])].count("checked_in") == 1

    # A different key is a different action: the visit is already in.
    r = await g.act(v["visit_id"], "check-in", key="other-key")
    assert r.status_code == 409 and r.json()["error"]["details"]["current"] == "checked_in"

    r = await client.post(f"{API}/guard/visits/{v['visit_id']}/check-out", json={}, headers=g.gh)
    assert r.status_code == 400 and r.json()["error"]["code"] == "idempotency_key_required"


async def test_two_guards_checking_in_at_once(client, f):
    g = await Gate(client, f).setup()
    v = await g.visit()
    rs = await asyncio.gather(*(g.act(v["visit_id"], "check-in") for _ in range(4)))
    assert sorted(r.status_code for r in rs) == [200, 409, 409, 409]


async def test_offline_replay_keeps_tap_time_within_reason(client, f):
    g = await Gate(client, f).setup()
    v = await g.visit()
    tapped = datetime.now(UTC) + timedelta(seconds=1)
    r = await g.act(v["visit_id"], "check-in", occurred_at=tapped.isoformat())
    async with system_session() as s:
        row = await s.get(Visit, UUID(v["visit_id"]))
    assert row.checked_in_at <= datetime.now(UTC)  # never in the future
    assert row.checked_in_at >= row.approved_at  # never before the approval

    out = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    r = await g.act(v["visit_id"], "check-out", occurred_at=out)
    assert r.status_code == 200
    async with system_session() as s:
        row = await s.get(Visit, UUID(v["visit_id"]))
    assert row.checked_out_at >= row.checked_in_at


async def test_scan_rejects_bad_and_foreign_passes(client, f):
    g = await Gate(client, f).setup()
    v = await g.visit()
    assert (await g.scan("not-a-pass-at-all"))["result"] == "invalid"
    tampered = v["pass"][:-3] + ("AAA" if not v["pass"].endswith("AAA") else "BBB")
    assert (await g.scan(tampered))["result"] == "invalid"

    # Another org's guard scanning this org's pass learns nothing about it.
    g2 = await Gate(client, f).setup()
    s = await g2.scan(v["pass"])
    assert s["result"] == "invalid" and s["visit"] is None

    # Same org, other site.
    other = await f.site(g.o, "Warehouse")
    await client.put(
        f"{API}/users/{g.guard['id']}/sites",
        json={"site_ids": [g.site["id"], other["id"]]},
        headers=g.o.h,
    )
    s = await g.scan(v["pass"], site_id=other["id"])
    assert s["result"] == "wrong_site" and s["site_name"] == "HQ"


async def test_scan_pending_then_guard_override(client, f):
    g = await Gate(client, f).setup()
    v = await g.visit(approve=False)
    r = await g.act(v["visit_id"], "check-in")
    assert r.status_code == 409 and r.json()["error"]["code"] == "needs_approval"

    r = await g.act(v["visit_id"], "check-in", override_reason="Host confirmed on the phone")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "checked_in"
    assert r.json()["guard_note"] == "Host confirmed on the phone"
    ev = await events(v["visit_id"])
    override = next(e for e in ev if e.to_status == "approved")
    assert override.actor_type == "guard" and override.meta["override"] is True
    note = (await messages(g.host["phone"], "visitor_arrived"))[0]
    assert "Let in by security: Host confirmed on the phone" in note.payload["text"]
    # The host's WhatsApp buttons no longer apply.
    st = await client.get(
        f"{API}/public/visits/{v['visit_id']}", headers={"Authorization": f"Bearer {v['token']}"}
    )
    assert st.json()["status"] == "checked_in"


async def test_remind_host_is_rate_limited(client, f):
    g = await Gate(client, f).setup()
    v = await g.visit(approve=False)
    r = await client.post(f"{API}/guard/visits/{v['visit_id']}/notify-host", headers=g.gh)
    assert r.status_code == 200
    reminder = (await messages(g.host["phone"], "visit_reminder"))[0]
    assert "still waiting" in reminder.payload["text"] and reminder.payload["buttons"]
    r = await client.post(f"{API}/guard/visits/{v['visit_id']}/notify-host", headers=g.gh)
    assert r.status_code == 429


# ---------- Walk-ins ----------


async def _walk_in(client, g, **body):
    form = (await client.get(f"{API}/guard/form?site_id={g.site['id']}", headers=g.gh)).json()
    up = await client.post(
        f"{API}/guard/uploads", files={"file": ("p.png", png(), "image/png")}, headers=g.gh
    )
    assert up.status_code == 201, up.text
    payload = {
        "site_id": g.site["id"],
        "gate_id": g.site["gates"][0]["id"],
        "phone": phone(),
        "full_name": "Suresh Das",
        "host_id": g.host["id"],
        "purpose_id": form["purposes"][0]["id"],
        "photo_upload": up.json()["upload_token"],
        "consent_notice_id": form["notices"]["en"]["id"],
        "consent": True,
    } | body
    return await client.post(f"{API}/guard/visits", json=payload, headers=g.gh), payload


async def test_walk_in_asks_host(client, f):
    g = await Gate(client, f).setup()
    r, body = await _walk_in(client, g)
    assert r.status_code == 201, r.text
    card = r.json()
    assert card["status"] == "pending" and card["source"] == "guard_manual"
    assert card["gate_name"] == "Main Gate" and card["photo_url"]
    req = (await messages(g.host["phone"], "visit_request"))[0]
    assert "Suresh Das" in req.payload["text"]
    ev = await events(card["id"])
    assert ev[0].actor_type == "guard" and ev[0].actor_id == UUID(g.guard["id"])
    assert [c["id"] for c in (await g.queue())["awaiting"]] == [card["id"]]


async def test_walk_in_admitted_directly(client, f):
    g = await Gate(client, f).setup()
    r, _ = await _walk_in(client, g, admit=True)
    assert r.status_code == 422 and r.json()["error"]["code"] == "reason_required"

    r, _ = await _walk_in(client, g, admit=True, override_reason="Courier with signed delivery")
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "checked_in"
    assert not await messages(g.host["phone"], "visit_request")  # host isn't asked
    assert await messages(g.host["phone"], "visitor_arrived")  # but is told


async def test_walk_in_photo_token_is_per_guard(client, f):
    g = await Gate(client, f).setup()
    other_guard, other_h = await f.guard(g.o)
    up = await client.post(
        f"{API}/guard/uploads", files={"file": ("p.png", png(), "image/png")}, headers=other_h
    )
    r, _ = await _walk_in(client, g, photo_upload=up.json()["upload_token"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_upload"


async def test_walk_in_otp_when_org_requires_it(client, f):
    g = await Gate(client, f).setup(guard_manual_requires_otp=True)
    p = phone()
    r, _ = await _walk_in(client, g, phone=p)
    assert r.status_code == 422 and r.json()["error"]["code"] == "otp_required"

    r = await client.post(
        f"{API}/guard/otp/send", json={"site_id": g.site["id"], "phone": p}, headers=g.gh
    )
    assert r.status_code == 202
    code = (await messages(p, "otp"))[0].payload["params"]["code"]
    wrong = "000000" if code != "000000" else "111111"
    r, _ = await _walk_in(client, g, phone=p, otp_code=wrong)
    assert r.status_code == 400
    r, _ = await _walk_in(client, g, phone=p, otp_code=code)
    assert r.status_code == 201, r.text


# ---------- Blacklist ----------


async def _blacklist(client, g, p: str, action: str = "block", **kw):
    r = await client.post(
        f"{API}/blacklist",
        json={
            "phone": p,
            "name": "Known trouble",
            "reason": "Banned after incident",
            "action": action,
        }
        | kw,
        headers=g.o.h,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_blocked_visitor_cannot_check_in(client, f):
    g = await Gate(client, f).setup()
    p = phone()
    entry = await _blacklist(client, g, p)
    v = await f.checkin(g.gate_token, g.host["id"], phone_=p)
    assert v["status_code"] == 403 and v["error"]["code"] == "checkin_blocked"
    assert "Banned" not in v["error"]["message"]  # the visitor isn't told why
    assert not await messages(g.host["phone"], "visit_request")
    # The host was never asked, so it isn't in their list as "declined".
    assert (await client.get(f"{API}/host/visits/today", headers=g.host_h)).json() == []
    assert (await client.get(f"{API}/visits", headers=g.host_h)).json()["items"] == []

    q = await g.queue()
    assert len(q["alerts"]) == 1 and q["alerts"][0]["alert"] == {
        "action": "block",
        "reason": "Banned after incident",
    }
    listed = (await client.get(f"{API}/blacklist", headers=g.o.h)).json()["items"]
    assert listed[0]["id"] == entry["id"] and listed[0]["hits"] == 1

    # Walk-in at the desk: the guard is told why.
    r, _ = await _walk_in(client, g, phone=p)
    assert (
        r.status_code == 403 and r.json()["error"]["details"]["reason"] == "Banned after incident"
    )


async def test_alert_lets_visit_through_flagged(client, f):
    g = await Gate(client, f).setup()
    p = phone()
    await _blacklist(client, g, p, action="alert", reason="Ask for a second ID")
    v = await g.visit(phone_=p)
    s = await g.scan(v["pass"])
    assert s["result"] == "ok" and s["visit"]["alert"]["reason"] == "Ask for a second ID"
    assert (await g.act(v["visit_id"], "check-in")).status_code == 200


async def test_block_added_after_approval_stops_entry(client, f):
    g = await Gate(client, f).setup()
    v = await g.visit()
    await _blacklist(client, g, v["phone"])
    s = await g.scan(v["pass"])
    assert s["result"] == "blocked"
    r = await g.act(v["visit_id"], "check-in")
    assert r.status_code == 403 and r.json()["error"]["code"] == "blocked"


async def test_blacklist_entry_for_other_site_or_expired_does_not_apply(client, f):
    g = await Gate(client, f).setup()
    other = await f.site(g.o, "Warehouse")
    p1, p2 = phone(), phone()
    await _blacklist(client, g, p1, site_id=other["id"])
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    await _blacklist(client, g, p2, expires_at=past)
    assert (await f.checkin(g.gate_token, g.host["id"], phone_=p1))["status_code"] == 201
    assert (await f.checkin(g.gate_token, g.host["id"], phone_=p2))["status_code"] == 201


async def test_blacklist_is_admin_only(client, f):
    g = await Gate(client, f).setup()
    assert (await client.get(f"{API}/blacklist", headers=g.gh)).status_code == 403
    assert (await client.get(f"{API}/blacklist", headers=g.host_h)).status_code == 403
    e = await _blacklist(client, g, phone())
    r = await client.delete(f"{API}/blacklist/{e['id']}", headers=g.o.h)
    assert r.status_code == 204
    assert (await client.get(f"{API}/blacklist", headers=g.o.h)).json()["total"] == 0
    assert (await client.get(f"{API}/blacklist?active=false", headers=g.o.h)).json()["total"] == 1


# ---------- End of day ----------


async def test_auto_checkout_at_end_of_day(client, f):
    g = await Gate(client, f).setup()
    v = await g.visit()
    assert (await g.act(v["visit_id"], "check-in")).status_code == 200
    ended = datetime.now(UTC) - timedelta(minutes=1)
    async with system_session() as s:
        await s.execute(
            update(Visit).where(Visit.id == UUID(v["visit_id"])).values(valid_until=ended)
        )
        await s.commit()
    assert await guard_svc.auto_checkout_due() == 1
    async with system_session() as s:
        row = await s.get(Visit, UUID(v["visit_id"]))
    assert row.status == "checked_out" and row.checkout_method == "auto"
    assert abs((row.checked_out_at - ended).total_seconds()) < 1
    assert await guard_svc.auto_checkout_due() == 0


async def test_live_stream_reports_changes(client, f):
    """The SSE endpoint is subscribed to the site's channel (pub/sub is unit-tested
    via the visitor stream); here: auth and scoping of the stream."""
    g = await Gate(client, f).setup()
    other = await f.site(g.o, "Warehouse")
    r = await client.get(f"{API}/guard/stream?site_id={other['id']}", headers=g.gh)
    assert r.status_code == 404
    async with system_session() as s:
        assert await s.get(Organization, g.o.id)
