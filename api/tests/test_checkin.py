"""Visitor check-in: gate page, OTP, uploads, submission and its validation."""

import io

from PIL import Image
from sqlalchemy import select

from app.core.db import system_session
from app.core.redis import get_redis
from app.models import ConsentRecord, Visit, Visitor
from app.services import storage
from tests.factories import messages, phone, png

API = "/api/v1/public"


async def _setup(client, f):
    o = await f.org("Kalinga Test")
    site = await f.site(o, "HQ")
    host = await f.user(o, full_name="Meera Pattnaik")
    gate = site["gates"][0]["qr_token"]
    return o, site, host, gate


async def test_gate_info(client, f):
    o, site, host, gate = await _setup(client, f)
    g = (await client.get(f"{API}/gates/{gate}")).json()
    assert g["site_name"] == "HQ" and g["gate_name"] == "Main Gate"
    assert len(g["purposes"]) == 6 and g["purposes"][0]["label_i18n"]["hi"]
    assert set(g["notices"]) == {"en", "hi"}
    assert "Kalinga Test" in g["notices"]["en"]["body"] and "90 days" in g["notices"]["en"]["body"]
    assert g["require_selfie"] is True

    assert (await client.get(f"{API}/gates/not-a-token")).status_code == 404
    # A rotated poster and a deactivated gate stop working.
    gid = site["gates"][0]["id"]
    await client.post(f"/api/v1/gates/{gid}/rotate-qr", headers=o.h)
    assert (await client.get(f"{API}/gates/{gate}")).status_code == 404
    new = (await client.get(f"/api/v1/gates/{gid}", headers=o.h)).json()["qr_token"]
    await client.delete(f"/api/v1/gates/{gid}", headers=o.h)
    r = await client.get(f"{API}/gates/{new}")
    assert r.status_code == 404 and "no longer active" in r.json()["error"]["message"]


async def test_otp_flow_and_limits(client, f):
    _, _, _, gate = await _setup(client, f)
    p = phone()
    r = await client.post(f"{API}/otp/send", json={"gate_token": gate, "phone": p[3:]})
    assert r.status_code == 202 and r.json()["sent_to"].endswith(p[-4:])
    msg = (await messages(p, "otp"))[0]
    code = msg.payload["params"]["code"]
    assert msg.status == "sent" and code in msg.payload["text"]

    # Immediate resend is refused (cooldown).
    r = await client.post(f"{API}/otp/send", json={"gate_token": gate, "phone": p})
    assert r.status_code == 429 and r.json()["error"]["code"] == "otp_cooldown"

    wrong = "000000" if code != "000000" else "111111"
    r = await client.post(f"{API}/otp/verify", json={"gate_token": gate, "phone": p, "code": wrong})
    assert r.status_code == 400 and r.json()["error"]["details"]["attempts_left"] == 4
    r = await client.post(f"{API}/otp/verify", json={"gate_token": gate, "phone": p, "code": code})
    assert r.status_code == 200 and r.json()["token"] and r.json()["returning"] is None
    # Single use.
    r = await client.post(f"{API}/otp/verify", json={"gate_token": gate, "phone": p, "code": code})
    assert r.status_code == 400 and r.json()["error"]["code"] == "otp_expired"


async def test_otp_wrong_attempts_lock_the_code(client, f):
    _, _, _, gate = await _setup(client, f)
    p = phone()
    await client.post(f"{API}/otp/send", json={"gate_token": gate, "phone": p})
    code = (await messages(p, "otp"))[0].payload["params"]["code"]
    wrong = "000000" if code != "000000" else "111111"
    codes = []
    for _ in range(5):
        r = await client.post(
            f"{API}/otp/verify", json={"gate_token": gate, "phone": p, "code": wrong}
        )
        codes.append(r.status_code)
    assert codes == [400, 400, 400, 400, 429]
    r = await client.post(f"{API}/otp/verify", json={"gate_token": gate, "phone": p, "code": code})
    assert r.status_code == 400  # the right code no longer works either


async def test_otp_send_rate_limited_per_phone(client, f):
    _, _, _, gate = await _setup(client, f)
    p = phone()
    statuses = []
    for _ in range(4):
        await get_redis().delete(*[k async for k in get_redis().scan_iter("otp-cd:*")] or ["x"])
        r = await client.post(f"{API}/otp/send", json={"gate_token": gate, "phone": p})
        statuses.append(r.status_code)
    assert statuses == [202, 202, 202, 429]


async def test_visitor_token_required(client, f):
    o, site, host, gate = await _setup(client, f)
    assert (await client.get(f"{API}/hosts?q=me")).status_code == 401
    r = await client.get(f"{API}/hosts?q=me", headers={"Authorization": "Bearer junk"})
    assert r.status_code == 401
    # A staff access token is not a visitor token.
    assert (await client.get(f"{API}/hosts?q=me", headers=o.h)).status_code == 401


async def test_host_search(client, f):
    o, site, host, gate = await _setup(client, f)
    await f.guard(o)  # guards are not hosts
    vt = await f.visitor_token(gate, phone())
    h = {"Authorization": f"Bearer {vt}"}
    assert (await client.get(f"{API}/hosts?q=m", headers=h)).json() == []
    res = (await client.get(f"{API}/hosts?q=MEERA", headers=h)).json()
    assert [x["full_name"] for x in res] == ["Meera Pattnaik"]
    assert "phone" not in res[0] and "email" not in res[0]
    res = (await client.get(f"{API}/hosts?q=person", headers=h)).json()
    assert all("Person" in x["full_name"] for x in res)
    ids = {x["id"] for x in res}
    guards = (await client.get("/api/v1/users?role=guard", headers=o.h)).json()["items"]
    assert not ids & {g["id"] for g in guards}


async def test_submit_notifies_host_and_records_consent(client, f):
    o, site, host, gate = await _setup(client, f)
    v = await f.checkin(
        gate,
        host["id"],
        purpose_note="Quarterly review",
        accompanying_count=2,
        vehicle_number="od 02 ab 1234",
    )
    assert v["status_code"] == 201 and v["status"] == "pending"

    req = (await messages(host["phone"], "visit_request"))[0]
    assert req.status == "sent"
    text = req.payload["text"]
    assert "Ravi Kumar" in text and "Acme Pvt Ltd" in text and "Quarterly review" in text
    assert "With 2 more" in text and "OD02AB1234" in text and "http://web.test/r/" in text
    assert [b["title"] for b in req.payload["buttons"]] == ["Approve", "Ask to wait", "Reject"]

    async with system_session() as s:
        visit = await s.get(Visit, v["visit_id"])
        assert visit.photo_key and visit.visitor_phone == v["phone"]
        assert (
            await s.execute(select(ConsentRecord).where(ConsentRecord.visit_id == visit.id))
        ).scalar_one()
        visitor = await s.get(Visitor, visit.visitor_id)
        assert visitor.visit_count == 1

    st = (
        await client.get(
            f"{API}/visits/{v['visit_id']}", headers={"Authorization": f"Bearer {v['token']}"}
        )
    ).json()
    assert st["status"] == "pending" and st["host_name"] == "Meera Pattnaik" and st["pass"] is None


async def test_resubmit_returns_same_visit(client, f):
    o, site, host, gate = await _setup(client, f)
    p = phone()
    a = await f.checkin(gate, host["id"], p)
    b = await f.checkin(gate, host["id"], p)
    assert b["status_code"] == 200 and b["visit_id"] == a["visit_id"]
    assert len(await messages(host["phone"], "visit_request")) == 1


async def test_returning_visitor_prefill(client, f):
    o, site, host, gate = await _setup(client, f)
    p = phone()
    await f.checkin(gate, host["id"], p, company="Tata Steel")
    await get_redis().flushall()
    await client.post(f"{API}/otp/send", json={"gate_token": gate, "phone": p})
    code = (await messages(p, "otp"))[0].payload["params"]["code"]
    r = await client.post(f"{API}/otp/verify", json={"gate_token": gate, "phone": p, "code": code})
    ret = r.json()["returning"]
    assert ret["full_name"] == "Ravi Kumar" and ret["company"] == "Tata Steel"
    assert ret["has_photo"] and ret["last_host"]["full_name"] == "Meera Pattnaik"


async def test_submit_validation(client, f):
    o, site, host, gate = await _setup(client, f)
    guard, _ = await f.guard(o)
    await client.post(
        "/api/v1/custom-fields",
        json={"key": "laptop", "label": "Laptop serial", "type": "text", "required": True},
        headers=o.h,
    )
    await client.post(
        "/api/v1/custom-fields",
        json={"key": "floor", "label": "Floor", "type": "select", "options": ["1", "2"]},
        headers=o.h,
    )
    await client.post(
        "/api/v1/custom-fields",
        json={"key": "nda", "label": "I accept the NDA", "type": "declaration"},
        headers=o.h,
    )

    r = await f.checkin(gate, host["id"])
    assert r["status_code"] == 422 and {d["field"] for d in r["error"]["details"]} == {
        "laptop",
        "nda",
    }
    r = await f.checkin(gate, host["id"], custom_values={"laptop": "X1", "nda": True, "floor": "9"})
    assert r["status_code"] == 422 and r["error"]["details"] == [
        {"field": "floor", "msg": "Choose one of the options"}
    ]
    r = await f.checkin(gate, host["id"], custom_values={"laptop": "X1", "nda": True, "evil": 1})
    assert r["status_code"] == 422
    ok = await f.checkin(
        gate, host["id"], custom_values={"laptop": "X1", "nda": True, "floor": "2"}
    )
    assert ok["status_code"] == 201
    async with system_session() as s:
        cv = (await s.get(Visit, ok["visit_id"])).custom_values
    assert cv == {
        "laptop": "X1",
        "floor": "2",
        "nda": {"accepted": True, "text": "I accept the NDA"},
    }

    fields = {"custom_values": {"laptop": "X1", "nda": True}}
    assert (await f.checkin(gate, guard["id"], **fields))["error"]["code"] == "invalid_host"
    r = await f.checkin(gate, host["id"], consent=False, **fields)
    assert r["status_code"] == 422
    r = await f.checkin(gate, host["id"], photo_upload=None, **fields)
    assert r["error"]["code"] == "photo_required"


async def test_id_proof_only_last4(client, f):
    o, site, host, gate = await _setup(client, f)
    purposes = (await client.get("/api/v1/purposes", headers=o.h)).json()
    await client.patch(
        f"/api/v1/purposes/{purposes[0]['id']}", json={"requires_id_proof": True}, headers=o.h
    )
    r = await f.checkin(gate, host["id"])
    assert r["error"]["code"] == "id_required"
    r = await f.checkin(gate, host["id"], id_type="aadhaar", id_last4="123456789012")
    assert r["status_code"] == 422  # a full Aadhaar number is refused outright
    r = await f.checkin(gate, host["id"], id_type="aadhaar", id_last4="9012")
    assert r["status_code"] == 201
    async with system_session() as s:
        v = await s.get(Visit, r["visit_id"])
    assert (v.id_type, v.id_last4) == ("aadhaar", "9012")


async def test_changed_notice_must_be_reaccepted(client, f):
    o, site, host, gate = await _setup(client, f)
    r = await f.checkin(gate, host["id"], consent_notice_id="00000000-0000-0000-0000-000000000000")
    assert r["status_code"] == 409 and r["error"]["code"] == "notice_changed"


async def test_upload_strips_metadata_and_rejects_non_images(client, f):
    o, site, host, gate = await _setup(client, f)
    vt = await f.visitor_token(gate, phone())
    h = {"Authorization": f"Bearer {vt}"}
    r = await client.post(
        f"{API}/uploads", files={"file": ("x.png", b"not an image", "image/png")}, headers=h
    )
    assert r.status_code == 422

    img = Image.new("RGB", (2000, 1000), "red")
    exif = Image.Exif()
    exif[0x010F] = "SpyCam"  # Make
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    r = await client.post(
        f"{API}/uploads", files={"file": ("x.jpg", buf.getvalue(), "image/jpeg")}, headers=h
    )
    assert r.status_code == 201
    from app.core import tokens

    key = tokens.verify("upload", r.json()["upload_token"])["k"]
    stored = Image.open(io.BytesIO(storage.backend().read(key)))
    assert stored.format == "WEBP" and max(stored.size) == 640
    assert not stored.getexif()


async def test_photo_link_is_signed(client, f):
    o, site, host, gate = await _setup(client, f)
    await f.checkin(gate, host["id"])
    link = (await messages(host["phone"], "visit_request"))[0].payload["params"]["link"]
    view = (await client.get(f"{API}/respond/{link.rsplit('/', 1)[1]}")).json()
    assert view["photo_url"].startswith("/api/v1/public/media/")
    img = await client.get(view["photo_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/webp"
    assert (await client.get(view["photo_url"] + "x")).status_code == 401
    assert (await client.get(f"{API}/media/{png().hex()}")).status_code == 401
