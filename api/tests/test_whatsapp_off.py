"""Running without WhatsApp (WHATSAPP_PROVIDER=off): visitors check in without a code,
hosts are alerted by web push, and links are shared by people from their own WhatsApp."""

import json
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import system_session
from app.models import NotificationLog, PushSubscription, Visit
from app.notifications import push
from app.notifications.providers import get_provider
from tests.factories import bearer, messages, phone

API = "/api/v1"
SUB = {
    "endpoint": "https://push.example.test/send/abc123",
    "keys": {"p256dh": "B" + "x" * 86, "auth": "a" * 22},
}


@pytest.fixture
def wa_off(monkeypatch):
    monkeypatch.setattr(get_settings(), "whatsapp_provider", "off")
    get_provider.cache_clear()
    yield
    get_provider.cache_clear()


@pytest.fixture
def pushes(monkeypatch):
    sent: list[tuple[str, dict]] = []

    async def fake(sub, data):
        if "gone" in sub["endpoint"]:
            raise push.Gone()
        sent.append((sub["endpoint"], json.loads(data)))

    monkeypatch.setattr(push, "send_raw", fake)
    return sent


async def _setup(f):
    o = await f.org("No WhatsApp Ltd")
    site = await f.site(o, "HQ")
    host = await f.user(o, full_name="Meera Pattnaik")
    return o, site, host, site["gates"][0]["qr_token"]


async def test_features_and_gate_say_no_codes(client, f, wa_off):
    o, site, host, gate = await _setup(f)
    assert (await client.get(f"{API}/public/features")).json()["whatsapp"] is False
    info = (await client.get(f"{API}/public/gates/{gate}")).json()
    assert info["verify_phone"] is False
    r = await client.post(f"{API}/public/otp/send", json={"gate_token": gate, "phone": phone()})
    assert r.status_code == 409 and r.json()["error"]["code"] == "otp_off"


async def test_checkin_without_code_is_marked_unverified(client, f, wa_off):
    o, site, host, gate = await _setup(f)
    v = await f.checkin(gate, host["id"])
    assert v["status_code"] == 201, v
    async with system_session() as s:
        visit = await s.get(Visit, UUID(v["visit_id"]))
        assert visit.phone_verified is False
    # No browser subscribed and no WhatsApp: the host request is skipped, not stuck.
    (req,) = await messages(host["phone"], "visit_request")
    assert req.status == "skipped" and req.error == "WhatsApp is off"

    guard, gh = await f.guard(o)
    await client.put(
        f"{API}/users/{guard['id']}/sites", json={"site_ids": [site["id"]]}, headers=o.h
    )
    q = (await client.get(f"{API}/guard/queue", params={"site_id": site["id"]}, headers=gh)).json()
    card = next(c for c in q["awaiting"] if c["id"] == v["visit_id"])
    assert card["phone_verified"] is False


async def test_unverified_number_gets_nothing_back(client, f, wa_off):
    """Anyone can type any number, so nothing stored under it is handed out."""
    o, site, host, gate = await _setup(f)
    p = phone()
    first = await f.checkin(gate, host["id"], p, company="Tata Steel")
    assert first["status_code"] == 201
    r = await client.post(f"{API}/public/start", json={"gate_token": gate, "phone": p})
    assert r.json()["returning"] is None
    # The open request (and its pass, once approved) is not given to a second device.
    again = await f.checkin(gate, host["id"], p)
    assert again["status_code"] == 409 and again["error"]["code"] == "already_requested"
    # Nor is the earlier photo.
    other = await f.user(o)
    vt = r.json()["token"]
    info = (await client.get(f"{API}/public/gates/{gate}")).json()
    r = await client.post(
        f"{API}/public/visits",
        json={
            "full_name": "Someone Else",
            "host_id": other["id"],
            "purpose_id": info["purposes"][0]["id"],
            "use_previous_photo": True,
            "consent_notice_id": info["notices"]["en"]["id"],
            "consent": True,
        },
        headers={"Authorization": f"Bearer {vt}"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "photo_required"


async def test_codes_stay_when_whatsapp_is_on_unless_the_org_turns_them_off(client, f):
    o, site, host, gate = await _setup(f)
    r = await client.post(f"{API}/public/start", json={"gate_token": gate, "phone": phone()})
    assert r.status_code == 409 and r.json()["error"]["code"] == "otp_required"
    r = await client.patch(
        f"{API}/org", json={"settings": {"verify_visitor_phone": False}}, headers=o.h
    )
    assert r.status_code == 200, r.text
    assert (await client.get(f"{API}/public/gates/{gate}")).json()["verify_phone"] is False
    v = await f.checkin(gate, host["id"])
    assert v["status_code"] == 201
    # WhatsApp is still on: the host still gets the WhatsApp message.
    assert (await messages(host["phone"], "visit_request"))[0].status == "sent"


async def test_host_alerted_by_web_push(client, f, wa_off, pushes):
    o, site, host, gate = await _setup(f)
    hh = bearer(UUID(host["id"]), o.id, ["host"])
    info = (await client.get(f"{API}/push", headers=hh)).json()
    assert info["devices"] == 0 and len(info["public_key"]) > 80
    r = await client.post(f"{API}/push/subscriptions", json=SUB, headers=hh)
    assert r.status_code == 201 and r.json()["devices"] == 1

    v = await f.checkin(gate, host["id"], purpose_note="Audit")
    ((endpoint, data),) = pushes
    assert endpoint == SUB["endpoint"]
    assert data["title"] == "Visitor for you: Ravi Kumar"
    assert data["url"].startswith("http://web.test/r/") and data["respond_token"]
    assert [a["action"] for a in data["actions"]] == ["approve", "reject"]
    (req,) = await messages(host["phone"], "visit_request")
    assert req.status == "sent" and req.payload["pushed"] == 1

    # The notification's Approve button answers through the respond link.
    r = await client.post(
        f"{API}/public/respond/{data['respond_token']}", json={"action": "approve"}
    )
    assert r.status_code == 200 and r.json()["status"] == "approved"
    st = (
        await client.get(
            f"{API}/public/visits/{v['visit_id']}",
            headers={"Authorization": f"Bearer {v['token']}"},
        )
    ).json()
    assert st["status"] == "approved" and st["pass"]["url"]


async def test_dead_push_subscriptions_are_dropped(client, f, wa_off, pushes):
    o, site, host, gate = await _setup(f)
    hh = bearer(UUID(host["id"]), o.id, ["host"])
    dead = SUB | {"endpoint": "https://push.example.test/gone/1"}
    await client.post(f"{API}/push/subscriptions", json=dead, headers=hh)
    await f.checkin(gate, host["id"])
    async with system_session() as s:
        assert not (await s.execute(select(PushSubscription))).scalars().all()
        row = (
            await s.execute(
                select(NotificationLog).where(NotificationLog.template_key == "visit_request")
            )
        ).scalar_one()
        assert row.status == "skipped"


async def test_push_endpoint_moves_to_the_last_person(client, f, pushes):
    o, site, host, gate = await _setup(f)
    o2 = await f.org()
    other = await f.user(o2)
    await client.post(
        f"{API}/push/subscriptions", json=SUB, headers=bearer(UUID(host["id"]), o.id, ["host"])
    )
    oh = bearer(UUID(other["id"]), o2.id, ["host"])
    await client.post(f"{API}/push/subscriptions", json=SUB, headers=oh)
    async with system_session() as s:
        (row,) = (await s.execute(select(PushSubscription))).scalars().all()
        assert row.user_id == UUID(other["id"])
    r = await client.post(f"{API}/push/unsubscribe", json={"endpoint": SUB["endpoint"]}, headers=oh)
    assert r.json()["devices"] == 0


async def test_sign_in_links_are_handed_over_by_the_admin(client, f, wa_off):
    o, site, host, gate = await _setup(f)
    r = await client.post(f"{API}/auth/magic-link", json={"phone": host["phone"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "whatsapp_off"

    r = await client.post(f"{API}/users/{host['id']}/sign-in-link", headers=o.h)
    assert r.status_code == 200, r.text
    link = r.json()
    assert link["url"].startswith("http://web.test/m/") and link["phone"] == host["phone"]
    tok = link["url"].rsplit("/", 1)[1]
    r = await client.post(f"{API}/auth/magic", json={"token": tok})
    assert r.status_code == 200 and r.json()["access_token"]
    r = await client.post(f"{API}/auth/magic", json={"token": tok})
    assert r.status_code == 401 and r.json()["error"]["code"] == "link_used"
    me = (
        await client.get(f"{API}/auth/me", headers=bearer(UUID(host["id"]), o.id, ["host"]))
    ).json()
    assert me["whatsapp_enabled"] is False


async def test_invite_passes_are_shared_by_the_host(client, f, wa_off):
    o, site, host, gate = await _setup(f)
    inv = await f.invite(o, site["id"], host["id"])
    detail = (await client.get(f"{API}/invites/{inv['id']}", headers=o.h)).json()
    guest = detail["guests"][0]
    assert guest["sent_at"] is None
    assert guest["pass_url"] in guest["share_text"] and "Board meeting" in guest["share_text"]
    assert not await messages(guest["phone"], "invite")
    r = await client.post(f"{API}/invites/{inv['id']}/guests/{guest['id']}/resend", headers=o.h)
    assert r.status_code == 409


async def test_privacy_page_points_to_the_contact(client, f, wa_off):
    o, site, host, gate = await _setup(f)
    page = (await client.get(f"{API}/public/privacy/{o.slug}")).json()
    assert page["self_serve"] is False
    r = await client.post(f"{API}/public/privacy/{o.slug}/otp/send", json={"phone": phone()})
    assert r.status_code == 409


async def test_evacuation_list_is_shared_by_hand(client, f, wa_off):
    o, site, host, gate = await _setup(f)
    await f.checkin(gate, host["id"])
    r = await client.post(f"{API}/evacuation/share", json={"site_id": site["id"]}, headers=o.h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sent"] == 0 and "EVACUATION: HQ" in body["share_text"]
    assert "http://web.test/e/" in body["share_text"]


async def test_public_signup_can_be_closed(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_signup", False)
    assert (await client.get(f"{API}/public/features")).json()["signup"] is False
    r = await client.post(
        f"{API}/auth/signup",
        json={
            "org_name": "Strangers Ltd",
            "admin_name": "Someone",
            "email": "someone@example.com",
            "password": "a-long-password-123",
        },
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "signup_closed"
