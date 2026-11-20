"""Tenant isolation for the visitor-facing routes, which use signed tokens instead of
staff logins. A visitor at org A's gate must never see or touch org B's data."""

from uuid import UUID

from app.core import tokens
from app.notifications.inbound import process_payload
from tests.factories import bearer, messages, phone

API = "/api/v1/public"


async def _two_orgs(f):
    a = await f.populated("Org A")
    b = await f.populated("Org B")
    return a, b


async def _gate(client, o):
    site = (await client.get(f"/api/v1/sites/{o.ids['site_id']}", headers=o.h)).json()
    return site["gates"][0]["qr_token"]


async def test_visitor_at_a_cannot_reach_b(client, f):
    a, b = await _two_orgs(f)
    gate_a = await _gate(client, a)
    vt = await f.visitor_token(gate_a, phone())
    h = {"Authorization": f"Bearer {vt}"}

    # Host search only covers A ("Person" matches every factory host in both orgs).
    found = {x["id"] for x in (await client.get(f"{API}/hosts?q=person", headers=h)).json()}
    assert a.ids["user_id"] in found and b.ids["user_id"] not in found

    # Submitting at A's gate with B's host / purpose fails: they don't exist for A.
    r = await f.checkin(gate_a, b.ids["user_id"])
    assert r["status_code"] == 422 and r["error"]["code"] == "invalid_host"
    r = await f.checkin(gate_a, a.ids["user_id"], purpose_id=b.ids["purpose_id"])
    assert r["error"]["code"] == "invalid_purpose"


async def test_visit_tokens_are_bound_to_one_visit(client, f):
    a, b = await _two_orgs(f)
    va = await f.checkin(await _gate(client, a), a.ids["user_id"])
    h = {"Authorization": f"Bearer {va['token']}"}
    assert (await client.get(f"{API}/visits/{va['visit_id']}", headers=h)).status_code == 200
    for target in (b.ids["visit_id"], a.ids["visit_id"]):  # other org, and same org other visit
        assert (await client.get(f"{API}/visits/{target}", headers=h)).status_code == 404
        assert (await client.post(f"{API}/visits/{target}/cancel", headers=h)).status_code == 404
    # A visitor token or staff token is not a visit token.
    for wrong in (va["vtoken"], a.token):
        r = await client.get(
            f"{API}/visits/{va['visit_id']}", headers={"Authorization": f"Bearer {wrong}"}
        )
        assert r.status_code == 401


async def test_upload_from_one_org_cannot_be_used_in_another(client, f):
    a, b = await _two_orgs(f)
    p = phone()
    gate_a, gate_b = await _gate(client, a), await _gate(client, b)
    vt_a = await f.visitor_token(gate_a, p)
    from tests.factories import png

    up = await client.post(
        f"{API}/uploads",
        files={"file": ("me.png", png(), "image/png")},
        headers={"Authorization": f"Bearer {vt_a}"},
    )
    r = await f.checkin(gate_b, b.ids["user_id"], p, photo_upload=up.json()["upload_token"])
    assert r["status_code"] == 422 and r["error"]["code"] == "bad_upload"


async def test_forged_tokens_rejected(client, f):
    a, b = await _two_orgs(f)
    # Correct shape, wrong key: tokens are signed, so the org claim can't be changed.
    import jwt

    forged = jwt.encode(
        {"typ": "visit", "o": str(b.id), "v": b.ids["visit_id"], "exp": 9999999999},
        "x" * 40,
        "HS256",
    )
    r = await client.get(
        f"{API}/visits/{b.ids['visit_id']}", headers={"Authorization": f"Bearer {forged}"}
    )
    assert r.status_code == 401
    # A real respond token for A's visit says org A; it can't be pointed at B's visit.
    t = tokens.sign(
        "respond", {"o": str(a.id), "v": b.ids["visit_id"], "u": a.ids["user_id"]}, tokens_exp()
    )
    assert (await client.get(f"{API}/respond/{t}")).status_code == 404


def tokens_exp():
    from datetime import timedelta

    return timedelta(minutes=5)


async def test_host_of_b_cannot_answer_a_visit_on_whatsapp(client, f):
    a, b = await _two_orgs(f)
    host_a = (await client.get(f"/api/v1/users/{a.ids['user_id']}", headers=a.h)).json()
    host_b = (await client.get(f"/api/v1/users/{b.ids['user_id']}", headers=b.h)).json()
    msg = (await messages(host_a["phone"], "visit_request"))[0]
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "id": "wamid.B",
                                    "from": host_b["phone"][1:],
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
    assert await process_payload(payload) == ["ignored:unknown_sender"]


async def test_host_inbox_only_shows_own_org(client, f):
    a, b = await _two_orgs(f)
    h = bearer(UUID(b.ids["user_id"]), b.id, ["host"])
    items = (await client.get("/api/v1/host/visits", headers=h)).json()
    assert {i["id"] for i in items} == {b.ids["visit_id"]}
