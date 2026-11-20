"""DPDP: retention purge, a person's data (lookup / export / erase), visitor self-service
erasure requests and versioned privacy notices."""

import io
import json
import os
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.core.db import system_session
from app.core.redis import get_redis
from app.models import (
    AuditLog,
    ConsentRecord,
    NotificationLog,
    PrivacyRequest,
    Visit,
    Visitor,
)
from app.services import privacy
from tests.factories import messages, phone, png

API = "/api/v1"


def media(key: str) -> Path:
    return Path(get_settings().local_media_dir) / key


async def _setup(f):
    o = await f.org()
    site = await f.site(o, "HQ")
    host = await f.user(o, full_name="Meera")
    return o, site, host


async def _age(visit_id: str, days: int, status: str = "checked_out") -> None:
    async with system_session() as db:
        await db.execute(
            update(Visit)
            .where(Visit.id == UUID(visit_id))
            .values(requested_at=datetime.now(UTC) - timedelta(days=days), status=status)
        )
        v = await db.get(Visit, UUID(visit_id))
        await db.execute(
            update(Visitor)
            .where(Visitor.id == v.visitor_id)
            .values(
                first_seen_at=datetime.now(UTC) - timedelta(days=days),
                last_visit_at=datetime.now(UTC) - timedelta(days=days),
            )
        )
        await db.commit()


async def _visit(vid: str) -> Visit:
    async with system_session() as db:
        return await db.get(Visit, UUID(vid))


async def test_retention_anonymizes_old_visits_and_keeps_counts(client, f):
    o, site, host = await _setup(f)
    gate = site["gates"][0]["qr_token"]
    old = await f.checkin(gate, host["id"], vehicle_number="OD02AB1234")
    recent = await f.checkin(gate, host["id"])
    live = await f.checkin(gate, host["id"])
    await _age(old["visit_id"], 100)
    await _age(live["visit_id"], 100, status="checked_in")  # still on site: kept
    photo = (await _visit(old["visit_id"])).photo_key
    assert media(photo).exists()

    counts = await privacy.retention_run(o.id)
    assert counts["visits"] == 1 and counts["visitors"] == 1  # that visitor had only this visit

    v = await _visit(old["visit_id"])
    assert v.anonymized_at and v.visitor_name is None and v.visitor_phone is None
    assert v.vehicle_number is None and v.photo_key is None and v.custom_values == {}
    assert v.site_id and v.host_id and v.status == "checked_out"  # reports still work
    assert not media(photo).exists()
    assert (await _visit(recent["visit_id"])).visitor_name == "Ravi Kumar"
    assert (await _visit(live["visit_id"])).anonymized_at is None

    async with system_session() as db:
        texts = (
            await db.execute(
                select(NotificationLog.payload).where(
                    NotificationLog.visit_id == UUID(old["visit_id"])
                )
            )
        ).scalars()
        assert all(t["text"] == "[removed]" for t in texts)
        visitor = await db.get(Visitor, v.visitor_id)
        assert visitor.anonymized_at and visitor.phone is None and visitor.full_name is None
        rec = (
            await db.execute(select(ConsentRecord).where(ConsentRecord.visitor_id == v.visitor_id))
        ).scalar_one()
        assert rec.ip is None and rec.consented_at  # proof of consent stays
        audit = (
            await db.execute(select(AuditLog).where(AuditLog.action == "retention.purge"))
        ).scalar_one()
        assert audit.diff["visits"] == 1 and audit.actor_type == "system"

    r = await client.get(f"{API}/reports/traffic", headers=o.h, params={"days": 365})
    assert r.status_code == 200

    # Idempotent: nothing more to do.
    again = await privacy.retention_run(o.id)
    assert again["visits"] == 0 and again["visitors"] == 0


async def test_retention_removes_abandoned_uploads(client, f):
    o, site, host = await _setup(f)
    gate = site["gates"][0]["qr_token"]
    v = await f.checkin(gate, host["id"])
    vt = await f.visitor_token(gate, phone())
    r = await client.post(
        f"{API}/public/uploads",
        files={"file": ("me.png", png(), "image/png")},
        data={"kind": "selfie"},
        headers={"Authorization": f"Bearer {vt}"},
    )
    assert r.status_code == 201
    files = list(media(f"orgs/{o.id}/selfie").rglob("*.webp"))
    used = media((await _visit(v["visit_id"])).photo_key)
    orphan = next(p for p in files if p != used)
    two_days = time.time() - 2 * 86400
    for p in (orphan, used):
        os.utime(p, (two_days, two_days))

    counts = await privacy.retention_run(o.id)
    assert counts["files"] == 1
    assert not orphan.exists() and used.exists()


async def test_retention_due_runs_each_org_once_per_window(f):
    o, site, host = await _setup(f)
    v = await f.checkin(site["gates"][0]["qr_token"], host["id"])
    await _age(v["visit_id"], 100)
    assert await privacy.retention_due() >= 1
    assert (await _visit(v["visit_id"])).anonymized_at
    last = json.loads(await get_redis().get(f"retention:last:{o.id}"))
    assert last["visits"] == 1
    assert await privacy.retention_due() == 0  # locked for 6 hours


async def test_admin_lookup_export_and_erase(client, f):
    o, site, host = await _setup(f)
    gate = site["gates"][0]["qr_token"]
    p = phone()
    v1 = await f.checkin(gate, host["id"], phone_=p)
    await _age(v1["visit_id"], 3)  # an earlier visit
    v2 = await f.checkin(gate, host["id"], phone_=p)
    assert v2["status_code"] == 201, v2
    other = await f.checkin(gate, host["id"])

    r = await client.get(f"{API}/privacy/lookup", params={"phone": p}, headers=o.h)
    data = r.json()
    assert r.status_code == 200 and len(data["visits"]) == 2
    assert data["visitor"]["name"] == "Ravi Kumar" and data["consents"]
    assert any(m["kind"] == "otp" and m["text"] == "[verification code]" for m in data["messages"])

    r = await client.get(f"{API}/privacy/export", params={"phone": p}, headers=o.h)
    assert r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert "data.json" in names and sum(n.startswith("photos/") for n in names) == 2
    assert json.loads(z.read("data.json"))["phone"] == p

    # In progress: the second visit is still pending.
    r = await client.post(
        f"{API}/privacy/erase", json={"phone": p, "confirm_phone": p}, headers=o.h
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "visit_in_progress"
    await _age(v2["visit_id"], 1, status="checked_out")

    r = await client.post(
        f"{API}/privacy/erase", json={"phone": p, "confirm_phone": phone()}, headers=o.h
    )
    assert r.status_code == 422
    r = await client.post(
        f"{API}/privacy/erase",
        json={"phone": p, "confirm_phone": p, "note": "Asked at reception"},
        headers=o.h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["visits"] == 2 and r.json()["visitors"] == 1 and r.json()["files"] == 2

    assert (await _visit(v1["visit_id"])).visitor_name is None
    assert (await _visit(other["visit_id"])).visitor_name == "Ravi Kumar"
    assert await messages(p) == []  # no message keeps the number
    assert (await client.get(f"{API}/dev/whatsapp/messages")).status_code == 200
    data = (await client.get(f"{API}/privacy/lookup", params={"phone": p}, headers=o.h)).json()
    assert data["visitor"] is None and data["visits"] == []
    async with system_session() as db:
        a = (
            await db.execute(select(AuditLog).where(AuditLog.action == "privacy.erase"))
        ).scalar_one()
        assert p not in json.dumps(a.diff) and a.diff["phone"].endswith(p[-4:])


async def _privacy_token(client, slug: str, p: str) -> dict[str, str]:
    r = await client.post(f"{API}/public/privacy/{slug}/otp/send", json={"phone": p})
    assert r.status_code == 202, r.text
    code = (await messages(p, "otp"))[0].payload["params"]["code"]
    r = await client.post(
        f"{API}/public/privacy/{slug}/otp/verify", json={"phone": p, "code": code}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_visitor_self_service_and_admin_resolution(client, f):
    o, site, host = await _setup(f)
    gate = site["gates"][0]["qr_token"]
    p = phone()
    v = await f.checkin(gate, host["id"], phone_=p)

    page = (await client.get(f"{API}/public/privacy/{o.slug}")).json()
    assert page["retention_days"] == 90 and f"/privacy/{o.slug}" in page["notices"]["en"]

    h = await _privacy_token(client, o.slug, p)
    me = (await client.get(f"{API}/public/privacy/{o.slug}/me", headers=h)).json()
    assert len(me["data"]["visits"]) == 1 and me["open_request"] is None
    assert "blacklist_entries" not in me["data"]
    r = await client.get(f"{API}/public/privacy/{o.slug}/me/export", headers=h)
    assert r.status_code == 200 and zipfile.ZipFile(io.BytesIO(r.content)).namelist()

    r = await client.post(
        f"{API}/public/privacy/{o.slug}/me/erasure",
        json={"reason": "I no longer work with them", "locale": "hi"},
        headers=h,
    )
    assert r.status_code == 201 and r.json()["status"] == "open"
    again = await client.post(f"{API}/public/privacy/{o.slug}/me/erasure", json={}, headers=h)
    assert again.json()["id"] == r.json()["id"]  # one open request per person

    reqs = (await client.get(f"{API}/privacy/requests?status=open", headers=o.h)).json()
    assert len(reqs) == 1 and reqs[0]["phone"] == p and reqs[0]["active_visit"] is True
    ov = (await client.get(f"{API}/privacy/overview", headers=o.h)).json()
    assert ov["open_requests"] == 1

    rid = reqs[0]["id"]
    r = await client.post(f"{API}/privacy/requests/{rid}/erase", json={}, headers=o.h)
    assert r.status_code == 409  # still pending at the gate
    await _age(v["visit_id"], 0, status="checked_out")
    r = await client.post(f"{API}/privacy/requests/{rid}/erase", json={}, headers=o.h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed" and r.json()["phone"] is None
    done = (await messages(p, "privacy_erased"))[0]
    assert done.locale == "hi" and "हटा दिया" in done.payload["text"]
    r = await client.post(f"{API}/privacy/requests/{rid}/erase", json={}, headers=o.h)
    assert r.status_code == 409

    # Nothing left: a new request is refused.
    r = await client.post(f"{API}/public/privacy/{o.slug}/me/erasure", json={}, headers=h)
    assert r.status_code == 404


async def test_rejecting_a_request_tells_the_visitor(client, f):
    o, site, host = await _setup(f)
    p = phone()
    await f.checkin(site["gates"][0]["qr_token"], host["id"], phone_=p)
    h = await _privacy_token(client, o.slug, p)
    rid = (
        await client.post(f"{API}/public/privacy/{o.slug}/me/erasure", json={}, headers=h)
    ).json()["id"]
    r = await client.post(f"{API}/privacy/requests/{rid}/reject", json={}, headers=o.h)
    assert r.status_code == 422  # a reason is required
    r = await client.post(
        f"{API}/privacy/requests/{rid}/reject",
        json={"note": "A security incident on that day is under investigation"},
        headers=o.h,
    )
    assert r.json()["status"] == "rejected"
    msg = (await messages(p, "privacy_rejected"))[0]
    assert "under investigation." in msg.payload["text"]
    async with system_session() as db:
        row = await db.get(PrivacyRequest, UUID(rid))
        assert row.phone is None and row.phone_masked.endswith(p[-4:])


async def test_check_in_and_privacy_codes_are_separate(client, f):
    """Right after checking in, the visitor can get a privacy code (no shared cooldown),
    and a check-in code doesn't open the privacy page."""
    o, site, host = await _setup(f)
    p = phone()
    gate = site["gates"][0]["qr_token"]
    await f.checkin(gate, host["id"], phone_=p)
    await client.post(f"{API}/public/otp/send", json={"gate_token": gate, "phone": p})
    r = await client.post(f"{API}/public/privacy/{o.slug}/otp/send", json={"phone": p})
    assert r.status_code == 202, r.text
    checkin_codes = [m.payload["params"]["code"] for m in await messages(p, "otp")]
    privacy_code = checkin_codes.pop(0)  # newest first
    for code in checkin_codes:
        if code != privacy_code:
            r = await client.post(
                f"{API}/public/privacy/{o.slug}/otp/verify", json={"phone": p, "code": code}
            )
            assert r.status_code == 400

    r = await client.post(
        f"{API}/public/privacy/{o.slug}/otp/verify", json={"phone": p, "code": privacy_code}
    )
    assert r.status_code == 200


async def test_privacy_token_is_bound_to_its_org(client, f):
    a, site, host = await _setup(f)
    b = await f.org()
    p = phone()
    await f.checkin(site["gates"][0]["qr_token"], host["id"], phone_=p)
    h = await _privacy_token(client, a.slug, p)
    r = await client.get(f"{API}/public/privacy/{b.slug}/me", headers=h)
    assert r.status_code == 401
    r = await client.get(f"{API}/public/privacy/{a.slug}/me")
    assert r.status_code == 401


async def test_privacy_page_works_while_the_org_is_suspended(client, f):
    o, site, host = await _setup(f)
    p = phone()
    await f.checkin(site["gates"][0]["qr_token"], host["id"], phone_=p)
    sa = await f.platform_admin()
    r = await client.post(f"{API}/platform/orgs/{o.id}/suspend", headers=sa)
    assert r.status_code == 200
    assert (await client.get(f"{API}/public/privacy/{o.slug}")).status_code == 200
    h = await _privacy_token(client, o.slug, p)
    me = (await client.get(f"{API}/public/privacy/{o.slug}/me", headers=h)).json()
    assert len(me["data"]["visits"]) == 1


async def test_publishing_a_notice_creates_a_new_version(client, f):
    o, site, host = await _setup(f)
    gate = site["gates"][0]["qr_token"]
    first = (await client.get(f"{API}/public/gates/{gate}")).json()["notices"]["en"]
    await f.checkin(gate, host["id"])

    text = (
        "{org} records your name, number, photo and who you are visiting, only to manage "
        "visits and safety. Kept {days} days. See or erase it: {privacy}"
    )
    r = await client.post(
        f"{API}/privacy/notices", json={"locale": "en", "body": text}, headers=o.h
    )
    assert r.status_code == 201 and r.json()["version"] == 2
    assert "Kept 90 days" in r.json()["preview"]
    r = await client.post(
        f"{API}/privacy/notices", json={"locale": "en", "body": text}, headers=o.h
    )
    assert r.status_code == 422

    notices = (await client.get(f"{API}/privacy/notices", headers=o.h)).json()
    en = [n for n in notices if n["locale"] == "en"]
    assert [(n["version"], n["is_current"]) for n in en] == [(2, True), (1, False)]
    assert en[1]["acceptances"] == 1

    now = (await client.get(f"{API}/public/gates/{gate}")).json()["notices"]["en"]
    assert now["id"] != first["id"] and now["version"] == 2
    async with system_session() as db:
        assert (await db.execute(select(func.count()).select_from(ConsentRecord))).scalar() == 1
