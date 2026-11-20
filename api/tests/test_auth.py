from tests.factories import PASSWORD, phone

API = "/api/v1"


async def _login(client, identifier, password=PASSWORD, **kw):
    return await client.post(
        f"{API}/auth/login", json={"identifier": identifier, "password": password, **kw}
    )


async def test_signup_creates_org_admin_and_defaults(client):
    r = await client.post(
        f"{API}/auth/signup",
        json={
            "org_name": "Acme Infotech Pvt Ltd",
            "admin_name": "Ravi Kumar",
            "email": "Ravi@Acme.in",
            "password": "longpassword1",
            "phone": "98765 43210",
        },
    )
    assert r.status_code == 201, r.text
    assert "vms_refresh" in r.cookies
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await client.get(f"{API}/auth/me", headers=h)).json()
    assert me["email"] == "ravi@acme.in"
    assert me["phone"] == "+919876543210"
    assert set(me["roles"]) == {"org_admin", "host"}
    assert me["org"]["slug"] == "acme-infotech-pvt-ltd"
    purposes = (await client.get(f"{API}/purposes", headers=h)).json()
    assert [p["label"] for p in purposes][:2] == ["Meeting", "Interview"]
    assert purposes[0]["label_i18n"]["hi"] == "बैठक"
    org = (await client.get(f"{API}/org", headers=h)).json()
    assert org["data_region"] == "ap-south-1" and org["timezone"] == "Asia/Kolkata"
    assert org["settings"]["approval_timeout_min"] == 5


async def test_signup_duplicate_email(client, f):
    o = await f.org()
    r = await client.post(
        f"{API}/auth/signup",
        json={
            "org_name": "X",
            "admin_name": "Y",
            "email": o.admin_email.upper(),
            "password": "longpassword1",
        },
    )
    assert r.status_code == 409


async def test_login_by_email_and_phone(client, f):
    o = await f.org()
    assert (await _login(client, o.admin_email)).status_code == 200
    g, _ = await f.guard(o)
    r = await _login(client, g["phone"].replace("+91", ""))  # local format works
    assert r.status_code == 200, r.text


async def test_login_wrong_password_and_unknown_user(client, f):
    o = await f.org()
    r1 = await _login(client, o.admin_email, "nope-nope-nope")
    r2 = await _login(client, "ghost@example.com")
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["error"]["code"] == r2.json()["error"]["code"] == "invalid_credentials"


async def test_login_rate_limited(client, f):
    o = await f.org()
    for _ in range(10):
        await _login(client, o.admin_email, "wrong-password!")
    r = await _login(client, o.admin_email)  # even the right password is blocked now
    assert r.status_code == 429
    assert "Retry-After" in r.headers


async def test_rate_limit_counts_phone_formats_together(client, f):
    o = await f.org()
    g = await f.user(o, roles=["guard"], password=PASSWORD, phone=phone())
    local = g["phone"][3:]  # +91XXXXXXXXXX -> XXXXXXXXXX
    variants = [local, g["phone"], f"0{local}", f"{local[:5]} {local[5:]}", f"+91 {local}"]
    for i in range(10):
        await _login(client, variants[i % len(variants)], "wrong-password!")
    assert (await _login(client, f"91{local}")).status_code == 429


async def test_host_without_password_cannot_login(client, f):
    o = await f.org()
    host = await f.user(o)
    assert (await _login(client, host["phone"], "anything-at-all")).status_code == 401


async def test_same_email_in_two_orgs_requires_choice(client, f):
    a, b = await f.org(), await f.org()
    email = "shared@example.com"
    for o in (a, b):
        await f.user(o, email=email, roles=["guard"], password=PASSWORD, phone=phone())
    r = await _login(client, email)
    assert r.status_code == 409
    assert {d["slug"] for d in r.json()["error"]["details"]} == {a.slug, b.slug}
    r = await _login(client, email, org_slug=b.slug)
    assert r.status_code == 200
    me = (
        await client.get(
            f"{API}/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}
        )
    ).json()
    assert me["org"]["id"] == str(b.id)


async def test_refresh_rotates_and_detects_reuse(client, f):
    o = await f.org()
    r = await _login(client, o.admin_email)
    first = r.cookies["vms_refresh"]

    r2 = client.cookies.set("vms_refresh", first) or await client.post(f"{API}/auth/refresh")
    assert r2.status_code == 200
    second = r2.cookies["vms_refresh"]
    assert second != first

    # Replaying the first (rotated) token later revokes the whole family ...
    await _backdate_rotation(first)
    client.cookies.clear()
    assert (
        client.cookies.set("vms_refresh", first) or await client.post(f"{API}/auth/refresh")
    ).status_code == 401
    # ... so even the newest token is dead now.
    client.cookies.clear()
    assert (
        client.cookies.set("vms_refresh", second) or await client.post(f"{API}/auth/refresh")
    ).status_code == 401


async def _backdate_rotation(raw: str, seconds: int = 60) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from app.core.db import system_session
    from app.models import RefreshToken
    from app.services.auth import hash_token

    async with system_session() as db:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == hash_token(raw))
            .values(revoked_at=datetime.now(UTC) - timedelta(seconds=seconds))
        )
        await db.commit()


async def test_two_tabs_refreshing_at_once_stay_signed_in(client, f):
    """Both tabs send the same cookie: the second, a moment later, isn't theft."""
    o = await f.org()
    first = (await _login(client, o.admin_email)).cookies["vms_refresh"]
    tabs = []
    for _ in range(2):
        client.cookies.clear()
        r = client.cookies.set("vms_refresh", first) or await client.post(f"{API}/auth/refresh")
        assert r.status_code == 200
        tabs.append(r.cookies["vms_refresh"])
    assert len(set(tabs)) == 2
    for tok in tabs:  # both new tokens keep working
        client.cookies.clear()
        r = client.cookies.set("vms_refresh", tok) or await client.post(f"{API}/auth/refresh")
        assert r.status_code == 200


async def test_logout_revokes_refresh(client, f):
    o = await f.org()
    tok = (await _login(client, o.admin_email)).cookies["vms_refresh"]
    client.cookies.clear()
    assert (
        client.cookies.set("vms_refresh", tok) or await client.post(f"{API}/auth/logout")
    ).status_code == 204
    client.cookies.clear()
    assert (
        client.cookies.set("vms_refresh", tok) or await client.post(f"{API}/auth/refresh")
    ).status_code == 401


async def test_deactivated_user_is_locked_out_immediately(client, f):
    o = await f.org()
    g, gh = await f.guard(o)
    assert (await client.get(f"{API}/auth/me", headers=gh)).status_code == 200
    assert (await client.delete(f"{API}/users/{g['id']}", headers=o.h)).status_code == 204
    assert (await client.get(f"{API}/auth/me", headers=gh)).status_code == 401


async def test_suspended_org(client, f):
    o = await f.org()
    sa = await f.platform_admin()
    assert (await client.post(f"{API}/platform/orgs/{o.id}/suspend", headers=sa)).status_code == 200
    assert (await client.get(f"{API}/sites", headers=o.h)).status_code == 403
    assert (await _login(client, o.admin_email)).status_code == 403
    await client.post(f"{API}/platform/orgs/{o.id}/reactivate", headers=sa)
    assert (await client.get(f"{API}/sites", headers=o.h)).status_code == 200


async def test_bad_tokens(client):
    assert (await client.get(f"{API}/auth/me")).status_code == 401
    assert (
        await client.get(f"{API}/auth/me", headers={"Authorization": "Bearer junk"})
    ).status_code == 401
