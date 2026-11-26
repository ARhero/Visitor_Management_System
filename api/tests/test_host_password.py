"""Hosts can be given a password, as a second way to sign in next to sign-in links."""

API = "/api/v1"


async def _link_sign_in(client, o, host) -> str:
    r = await client.post(f"{API}/users/{host['id']}/sign-in-link", headers=o.h)
    tok = r.json()["url"].rsplit("/", 1)[1]
    r = await client.post(f"{API}/auth/magic", json={"token": tok})
    assert r.status_code == 200, r.text
    return r.cookies["vms_refresh"]


async def _refresh(client, cookie):
    client.cookies.clear()
    client.cookies.set("vms_refresh", cookie)
    r = await client.post(f"{API}/auth/refresh")
    client.cookies.clear()
    return r


async def test_first_password_keeps_the_host_signed_in(client, f):
    o = await f.org("Password Hosts Ltd")
    host = await f.user(o, full_name="Ravi Sahu")
    cookie = await _link_sign_in(client, o, host)

    r = await client.patch(
        f"{API}/users/{host['id']}",
        headers=o.h,
        json={"full_name": host["full_name"], "roles": ["host"], "password": "host-password-1"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["has_password"] is True and r.json()["roles"] == ["host"]

    # The phone signed in by link stays signed in.
    r = await _refresh(client, cookie)
    assert r.status_code == 200, r.text
    cookie = r.cookies["vms_refresh"]

    # And the mobile number plus password now work too.
    r = await client.post(
        f"{API}/auth/login",
        json={"identifier": host["phone"][-10:], "password": "host-password-1"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]

    # Changing an existing password still signs them out everywhere.
    r = await client.patch(
        f"{API}/users/{host['id']}", headers=o.h, json={"password": "host-password-2"}
    )
    assert r.status_code == 200, r.text
    assert (await _refresh(client, cookie)).status_code == 401
