"""Setup wizard: checklist, QR posters, logo upload and the test visit."""

from tests.factories import messages, phone, png
from tests.test_approval import tap

API = "/api/v1"


def steps(c: dict) -> dict[str, bool]:
    return {s["key"]: s["done"] for s in c["steps"]}


async def test_checklist_follows_the_setup(client, f):
    o = await f.org()
    c = (await client.get(f"{API}/onboarding/checklist", headers=o.h)).json()
    assert c["done"] == 0 and c["total"] == 7 and not c["complete"]

    site = await f.site(o, "HQ")
    await f.user(o, full_name="Meera")
    await f.guard(o)
    r = await client.post(f"{API}/onboarding/complete", json={"step": "org"}, headers=o.h)
    assert steps(r.json()) == {
        "org": True,
        "site": True,
        "hosts": True,
        "form": False,
        "posters": False,
        "test_visit": False,
        "guard": True,
    }
    await client.post(f"{API}/onboarding/complete", json={"step": "form"}, headers=o.h)
    r = await client.get(f"{API}/sites/{site['id']}/posters.pdf", headers=o.h)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    c = (await client.get(f"{API}/onboarding/checklist", headers=o.h)).json()
    assert steps(c)["posters"] and steps(c)["form"]
    assert (
        await client.post(f"{API}/onboarding/complete", json={"step": "nope"}, headers=o.h)
    ).status_code == 422

    r = await client.post(f"{API}/onboarding/dismiss", headers=o.h)
    assert r.json()["dismissed"] is True


async def test_posters(client, f):
    o = await f.org()
    site = await f.site(o, "HQ")
    gate = site["gates"][0]
    r = await client.get(f"{API}/gates/{gate['id']}/poster.pdf", headers=o.h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert "qr-posters-hq-" in r.headers["content-disposition"]
    await client.post(f"{API}/sites/{site['id']}/gates", json={"name": "Side gate"}, headers=o.h)
    r = await client.get(f"{API}/sites/{site['id']}/posters.pdf", headers=o.h)
    assert r.content.count(b"/Type /Page\n") + r.content.count(b"/Type /Page\r") == 2 or (
        r.content.count(b"/Type /Page") - r.content.count(b"/Type /Pages") == 2
    )
    # Hosts can't print posters.
    host = await f.user(o, full_name="Meera", password="correct-horse-battery")
    login = await client.post(
        f"{API}/auth/login",
        json={"identifier": host["phone"], "password": "correct-horse-battery"},
    )
    hh = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.get(f"{API}/gates/{gate['id']}/poster.pdf", headers=hh)).status_code == 403


async def test_logo_upload_and_branding(client, f):
    o = await f.org()
    r = await client.post(
        f"{API}/org/logo", files={"file": ("logo.png", png("orange"), "image/png")}, headers=o.h
    )
    assert r.status_code == 200, r.text
    key = r.json()["branding"]["logo_key"]
    assert key.startswith(f"orgs/{o.id}/branding/") and r.json()["logo_url"]

    # The logo can't be pointed at another file through the branding settings.
    r = await client.patch(
        f"{API}/org",
        json={"branding": {"primary_color": "#123456", "logo_key": "orgs/other/selfie/x.webp"}},
        headers=o.h,
    )
    assert r.json()["branding"]["logo_key"] == key
    assert r.json()["branding"]["primary_color"] == "#123456"

    site = await f.site(o, "HQ")
    gate = (await client.get(f"{API}/public/gates/{site['gates'][0]['qr_token']}")).json()
    assert gate["logo_url"] and gate["privacy_url"].endswith(f"/privacy/{o.slug}")
    pdf = await client.get(f"{API}/sites/{site['id']}/posters.pdf", headers=o.h)
    assert pdf.status_code == 200 and b"/Subtype /Image" in pdf.content

    r = await client.post(
        f"{API}/org/logo", files={"file": ("x.txt", b"not an image", "text/plain")}, headers=o.h
    )
    assert r.status_code == 422
    r = await client.delete(f"{API}/org/logo", headers=o.h)
    assert r.json()["branding"]["logo_key"] is None and r.json()["logo_url"] is None


async def test_test_visit_reaches_the_admin_on_whatsapp(client, f):
    o = await f.org()
    r = await client.post(f"{API}/onboarding/test-visit", json={}, headers=o.h)
    assert r.status_code == 422  # the admin has no phone yet
    await f.site(o, "HQ")
    me = phone()
    r = await client.post(f"{API}/onboarding/test-visit", json={"phone": me}, headers=o.h)
    assert r.status_code == 201, r.text

    msg = (await messages(me, "visit_request"))[0]
    assert "Test visitor" in msg.payload["text"]
    c = (await client.get(f"{API}/onboarding/checklist", headers=o.h)).json()
    assert c["test_visit"]["status"] == "pending" and not steps(c)["test_visit"]

    assert await tap(client, me, "approve") == "approve:approved"
    c = (await client.get(f"{API}/onboarding/checklist", headers=o.h)).json()
    assert steps(c)["test_visit"]
    assert await messages(me, "visit_approved")  # the "visitor" (also the admin) got a pass

    # Another person's number can't be taken over.
    other = await f.user(o, full_name="Meera")
    r = await client.post(
        f"{API}/onboarding/test-visit", json={"phone": other["phone"]}, headers=o.h
    )
    assert r.status_code == 409
