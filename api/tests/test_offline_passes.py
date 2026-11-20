"""Checking passes with no connection: the offline pack the guard's device keeps, and the
scan + check-in that replays an offline check-in once the connection is back."""

import base64
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import update

from app.core.db import system_session
from app.models import Visit
from tests.factories import messages
from tests.test_guard import Gate
from tests.test_invites import pass_token

API = "/api/v1"


def h(token: str) -> str:
    jti = jwt.decode(token, options={"verify_signature": False})["jti"]
    return hashlib.sha256(jti.encode()).hexdigest()


async def pack(g: Gate, site_id: str | None = None):
    return await g.c.get(
        f"{API}/guard/offline-pack", params={"site_id": site_id or g.site["id"]}, headers=g.gh
    )


async def pass_check_in(g: Gate, payload: str, key: str | None = None, **body):
    return await g.c.post(
        f"{API}/guard/pass-check-in",
        json={"site_id": g.site["id"], "payload": payload, **body},
        headers=g.gh | {"Idempotency-Key": key or uuid.uuid4().hex},
    )


async def test_pack_has_todays_passes_and_a_key_that_verifies_them(client, f):
    g = await Gate(client, f).setup()
    approved = await g.visit(vehicle_number="OD02AB1234")
    pending = await g.visit(approve=False)
    inv = await f.invite(g.o, g.site["id"], g.host["id"])
    guest_tok = pass_token((await messages(inv["guests"][0]["phone"], "invite"))[0].payload["text"])

    r = await pack(g)
    assert r.status_code == 200, r.text
    p = r.json()
    by_hash = {e["h"]: e for e in p["entries"]}
    v = by_hash[h(approved["pass"])]
    assert v["kind"] == "visit" and v["name"] == "Ravi Kumar" and v["host_name"] == "Meera Iyer"
    assert v["state"] == "approved" and v["ref_id"] == approved["visit_id"]
    gst = by_hash[h(guest_tok)]
    assert gst["kind"] == "invite" and gst["name"] == "Vikram Seth" and gst["consented"] is False
    assert not any(e["ref_id"] == pending["visit_id"] for e in p["entries"])  # no pass yet
    # Nothing in the pack is a usable pass: hashes only, never the jti itself.
    assert "jti" not in r.text and approved["pass"].split(".")[1] not in r.text

    # The key is the one that signs passes: a device can verify with it alone.
    raw = base64.urlsafe_b64decode(p["key"]["x"] + "==")
    key = Ed25519PublicKey.from_public_bytes(raw)
    claims = jwt.decode(approved["pass"], key, algorithms=["EdDSA"])
    assert claims["jti"]
    assert datetime.fromisoformat(p["use_until"]) > datetime.now(UTC)


async def test_pack_is_limited_to_the_guards_sites(client, f):
    g = await Gate(client, f).setup()
    other = await f.site(g.o, "Annex")
    assert (await pack(g, other["id"])).status_code == 404
    hosts = await client.get(
        f"{API}/guard/offline-pack", params={"site_id": g.site["id"]}, headers=g.host_h
    )
    assert hosts.status_code == 403


async def test_offline_check_in_is_replayed_once(client, f):
    g = await Gate(client, f).setup()
    v = await g.visit()
    async with system_session() as s:  # approved an hour ago; the gate went offline since
        await s.execute(
            update(Visit)
            .where(Visit.id == uuid.UUID(v["visit_id"]))
            .values(approved_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await s.commit()
    tapped = datetime.now(UTC) - timedelta(minutes=20)
    key = uuid.uuid4().hex
    r = await pass_check_in(g, v["pass"], key, occurred_at=tapped.isoformat())
    assert r.status_code == 200, r.text
    card = r.json()["visit"]
    assert card["status"] == "checked_in"
    assert abs(datetime.fromisoformat(card["checked_in_at"]) - tapped) < timedelta(seconds=1)

    # The outbox retrying with the same key gets the same answer, applied once.
    again = await pass_check_in(g, v["pass"], key, occurred_at=tapped.isoformat())
    assert again.json() == r.json()
    # Another device that also checked them in offline: already inside, not an error.
    other = await pass_check_in(g, v["pass"])
    assert other.status_code == 200 and other.json()["result"] == "inside"


async def test_offline_check_in_is_refused_when_the_server_says_no(client, f):
    g = await Gate(client, f).setup()
    v = await g.visit()
    # The host cancelled while the gate was offline...
    async with system_session() as s:
        await s.execute(
            update(Visit).where(Visit.id == uuid.UUID(v["visit_id"])).values(status="cancelled")
        )
        await s.commit()
    r = await pass_check_in(g, v["pass"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "pass_revoked"
    assert r.json()["error"]["details"]["name"] == "Ravi Kumar"

    # ... or the person was blacklisted since the device last refreshed its list.
    v2 = await g.visit()
    await client.post(
        f"{API}/blacklist",
        json={"phone": v2["phone"], "reason": "Banned after incident", "action": "block"},
        headers=g.o.h,
    )
    r = await pass_check_in(g, v2["pass"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "pass_blocked"
    # A forged token never gets anywhere.
    r = await pass_check_in(g, v2["pass"][:-4] + "AAAA")
    assert r.status_code == 409 and r.json()["error"]["code"] == "pass_invalid"


async def test_invite_guest_checked_in_offline(client, f):
    g = await Gate(client, f).setup()
    inv = await f.invite(g.o, g.site["id"], g.host["id"])
    tok = pass_token((await messages(inv["guests"][0]["phone"], "invite"))[0].payload["text"])
    r = await pass_check_in(g, tok)
    assert r.status_code == 200, r.text
    assert r.json()["visit"]["status"] == "checked_in" and r.json()["visit"]["source"] == "invite"
    # Single-use: gone from the next pack's invites, present as "inside".
    p = (await pack(g)).json()
    states = [e["state"] for e in p["entries"] if e["h"] == h(tok)]
    assert states == ["checked_in"]
