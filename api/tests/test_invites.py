"""Pre-approved invites (VIP passes) and host sign-in links."""

import re
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.db import system_session
from app.models import ConsentRecord, Visit
from tests.factories import bearer, messages, phone
from tests.test_guard import Gate

API = "/api/v1"
IST = ZoneInfo("Asia/Kolkata")


def pass_token(msg_text: str) -> str:
    return re.search(r"/p/(\S+)", msg_text).group(1)  # type: ignore[union-attr]


async def make(client, g, as_host: bool = True, **body):
    payload = {
        "site_id": g.site["id"],
        "kind": "single",
        "title": "Quarterly review",
        "date": datetime.now(IST).date().isoformat(),
        "start_time": "00:00",
        "end_time": "23:59",
        "guests": [{"name": "Anita Rao", "phone": phone(), "company": "Partner Co"}],
    } | body
    r = await client.post(f"{API}/invites", json=payload, headers=g.host_h if as_host else g.o.h)
    return r


async def test_host_invites_guest_who_gets_pass(client, f):
    g = await Gate(client, f).setup()
    r = await make(client, g)
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["host_name"] == "Meera Iyer" and inv["guest_count"] == 1
    guest = inv["guests"][0]
    assert guest["sent_at"] and guest["pass_url"].startswith("http://web.test/p/")
    msg = (await messages(guest["phone"], "invite"))[0]
    assert "Meera Iyer has invited you" in msg.payload["text"]
    assert "Quarterly review" in msg.payload["text"]

    # Before accepting the privacy notice, the pass shows no QR.
    tok = pass_token(msg.payload["text"])
    page = (await client.get(f"{API}/public/passes/{tok}")).json()
    assert page["kind"] == "invite" and page["state"] == "valid"
    assert page["needs_consent"] and page["qr_svg"] is None and page["notices"]["en"]["body"]
    r = await client.post(
        f"{API}/public/passes/{tok}/consent",
        json={"notice_id": page["notices"]["hi"]["id"], "locale": "hi"},
    )
    assert r.status_code == 200
    page = r.json()
    assert not page["needs_consent"] and page["qr_svg"].startswith("<svg")
    async with system_session() as s:
        rec = (await s.execute(select(ConsentRecord))).scalars().all()
    assert len(rec) == 1 and rec[0].locale == "hi" and rec[0].visit_id is None


async def test_single_invite_scan_check_in_once(client, f):
    g = await Gate(client, f).setup()
    inv = (await make(client, g)).json()
    tok = pass_token((await messages(inv["guests"][0]["phone"], "invite"))[0].payload["text"])

    s = await g.scan(tok)
    assert s["result"] == "ok" and s["guest"]["name"] == "Anita Rao"
    assert s["visit"]["status"] == "approved" and s["visit"]["source"] == "invite"
    assert s["visit"]["invite_title"] == "Quarterly review"
    # Scanning twice before check-in doesn't make a second visit.
    assert (await g.scan(tok))["visit"]["id"] == s["visit"]["id"]

    r = await g.act(s["visit"]["id"], "check-in")
    assert r.status_code == 200
    assert await messages(g.host["phone"], "visitor_arrived")
    assert (await g.scan(tok))["result"] == "inside"
    await g.act(s["visit"]["id"], "check-out")
    assert (await g.scan(tok))["result"] == "used"

    detail = (await client.get(f"{API}/invites/{inv['id']}", headers=g.host_h)).json()
    assert detail["arrived_count"] == 1 and detail["guests"][0]["status"] == "used"
    assert detail["guests"][0]["pass_url"] is None
    page = (await client.get(f"{API}/public/passes/{tok}")).json()
    assert page["state"] == "used" and page["qr_svg"] is None


async def test_multi_day_invite_once_a_day_inside_hours(client, f):
    g = await Gate(client, f).setup()
    now = datetime.now(IST)
    start = (now - timedelta(days=1)).date().isoformat()
    end = (now + timedelta(days=3)).date().isoformat()
    inv = (
        await make(
            client,
            g,
            kind="multi_day",
            date=start,
            end_date=end,
            start_time="00:00",
            end_time="23:59",
        )
    ).json()
    guest = inv["guests"][0]
    assert guest["max_uses"] is None
    tok = pass_token((await messages(guest["phone"], "invite"))[0].payload["text"])
    s = await g.scan(tok)
    assert s["result"] == "ok"
    await g.act(s["visit"]["id"], "check-in")
    await g.act(s["visit"]["id"], "check-out")
    assert (await g.scan(tok))["result"] == "left"  # come back tomorrow
    page = (await client.get(f"{API}/public/passes/{tok}")).json()
    assert page["state"] == "not_yet"

    # Outside the daily window.
    h = now.hour
    window = ("00:00", "00:15") if h >= 1 else ("22:00", "23:00")
    inv2 = (
        await make(
            client,
            g,
            kind="multi_day",
            date=start,
            end_date=end,
            start_time=window[0],
            end_time=window[1],
        )
    ).json()
    tok2 = pass_token((await messages(inv2["guests"][0]["phone"], "invite"))[0].payload["text"])
    assert (await g.scan(tok2))["result"] == "outside_hours"


async def test_future_invite_not_yet(client, f):
    g = await Gate(client, f).setup()
    later = (datetime.now(IST) + timedelta(days=2)).date().isoformat()
    inv = (await make(client, g, date=later)).json()
    tok = pass_token((await messages(inv["guests"][0]["phone"], "invite"))[0].payload["text"])
    assert (await g.scan(tok))["result"] == "not_yet"
    assert not (await g.queue())["invites"]  # not expected today


async def test_revoke_invite_stops_pass_and_tells_guest(client, f):
    g = await Gate(client, f).setup()
    inv = (await make(client, g)).json()
    p = inv["guests"][0]["phone"]
    tok = pass_token((await messages(p, "invite"))[0].payload["text"])
    s = await g.scan(tok)  # visit created, guest not yet checked in
    r = await client.post(f"{API}/invites/{inv['id']}/revoke", headers=g.host_h)
    assert r.status_code == 200 and r.json()["status"] == "revoked"
    assert await messages(p, "invite_cancelled")
    assert (await g.scan(tok))["result"] == "revoked"
    async with system_session() as sess:
        assert (await sess.get(Visit, UUID(s["visit"]["id"]))).status == "cancelled"
    r = await g.act(s["visit"]["id"], "check-in")
    assert r.status_code == 409
    page = (await client.get(f"{API}/public/passes/{tok}")).json()
    assert page["state"] == "revoked" and page["qr_svg"] is None


async def test_group_invite_guests_csv_and_expected_list(client, f):
    g = await Gate(client, f).setup()
    inv = (
        await make(
            client,
            g,
            kind="group",
            title="Vendor day",
            send=False,
            guests=[{"name": "A One", "phone": phone()}, {"name": "B Two", "phone": phone()}],
        )
    ).json()
    assert inv["guest_count"] == 2 and not inv["guests"][0]["sent_at"]
    csv = f"full_name,phone,company\nC Three,{phone()[3:]},X Ltd\nBad Row,12,\n,{phone()}\n"
    r = await client.post(
        f"{API}/invites/{inv['id']}/guests/import",
        files={"file": ("g.csv", csv.encode(), "text/csv")},
        headers=g.host_h,
    )
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["added"] == 1 and [e["row"] for e in res["errors"]] == [3, 4]

    q = await g.queue()
    assert sorted(x["name"] for x in q["invites"]) == ["A One", "B Two", "C Three"]

    # Picked from the list without a QR: the guard confirms the privacy notice.
    gid = next(x["guest_id"] for x in q["invites"] if x["name"] == "A One")
    url = f"{API}/guard/invite-guests/{gid}/arrive"
    r = await client.post(url, json={"site_id": g.site["id"]}, headers=g.gh)
    assert r.status_code == 409 and r.json()["error"]["code"] == "consent_required"
    r = await client.post(url, json={"site_id": g.site["id"], "consent": True}, headers=g.gh)
    assert r.status_code == 200 and r.json()["result"] == "ok"
    await g.act(r.json()["visit"]["id"], "check-in")
    q = await g.queue()
    assert "A One" not in [x["name"] for x in q["invites"]] and len(q["on_site"]) == 1


async def test_invite_permissions(client, f):
    g = await Gate(client, f).setup()
    other_host = await f.user(g.o, full_name="Other Host")
    oh = bearer(UUID(other_host["id"]), g.o.id, ["host"])

    # A host can't invite on someone else's behalf; an admin can.
    r = await make(client, g, host_id=other_host["id"])
    assert r.status_code == 403
    r = await make(client, g, as_host=False, host_id=other_host["id"])
    assert r.status_code == 201 and r.json()["host_name"] == "Other Host"
    admin_made = r.json()

    mine = (await make(client, g)).json()
    assert (await client.get(f"{API}/invites/{mine['id']}", headers=oh)).status_code == 404
    assert (await client.post(f"{API}/invites/{mine['id']}/revoke", headers=oh)).status_code == 404
    listed = (await client.get(f"{API}/invites", headers=oh)).json()
    assert [i["id"] for i in listed["items"]] == [admin_made["id"]]
    assert (await client.get(f"{API}/invites", headers=g.o.h)).json()["total"] == 2
    # Guards don't manage invites.
    assert (await client.get(f"{API}/invites", headers=g.gh)).status_code == 403


async def test_invite_validation(client, f):
    g = await Gate(client, f).setup()
    two = [{"name": "A", "phone": phone()}, {"name": "B", "phone": phone()}]
    assert (await make(client, g, guests=two)).status_code == 422  # single = one guest
    past = (datetime.now(IST) - timedelta(days=1)).date().isoformat()
    r = await make(client, g, date=past)
    assert r.status_code == 422 and r.json()["error"]["code"] == "in_past"
    assert (await make(client, g, kind="multi_day")).status_code == 422  # no end date
    assert (await make(client, g, start_time="18:00", end_time="09:00")).status_code == 422


# ---------- Sign-in link ----------


async def test_host_signs_in_with_whatsapp_link(client, f):
    g = await Gate(client, f).setup()
    r = await client.post(f"{API}/auth/magic-link", json={"phone": g.host["phone"]})
    assert r.status_code == 202
    msg = (await messages(g.host["phone"], "login_link"))[0]
    tok = re.search(r"/m/(\S+)", msg.payload["text"]).group(1)  # type: ignore[union-attr]

    r = await client.post(f"{API}/auth/magic", json={"token": tok})
    assert r.status_code == 200, r.text
    me = await client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}
    )
    assert me.json()["full_name"] == "Meera Iyer"
    again = await client.post(f"{API}/auth/magic", json={"token": tok})
    assert again.status_code == 401 and again.json()["error"]["code"] == "link_used"

    # Unknown numbers get the same answer and no message.
    stranger = phone()
    assert (
        await client.post(f"{API}/auth/magic-link", json={"phone": stranger})
    ).status_code == 202
    assert not await messages(stranger)

    # Other token types can't be used as a sign-in link.
    bad = await client.post(f"{API}/auth/magic", json={"token": g.gate_token * 2})
    assert bad.status_code == 401


async def test_host_today_lists_visits(client, f):
    g = await Gate(client, f).setup()
    v = await g.visit()
    await g.act(v["visit_id"], "check-in")
    rows = (await client.get(f"{API}/host/visits/today", headers=g.host_h)).json()
    assert rows[0]["id"] == v["visit_id"] and rows[0]["checked_in_at"]
