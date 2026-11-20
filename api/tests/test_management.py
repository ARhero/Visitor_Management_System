from tests.factories import PASSWORD

API = "/api/v1"


async def test_site_crud_with_default_gate(client, f):
    o = await f.org()
    s = await f.site(o, "Bhubaneswar Plant")
    assert len(s["gates"]) == 1 and s["gates"][0]["name"] == "Main Gate"
    assert s["gates"][0]["checkin_url"].endswith(f"/v/{s['gates'][0]['qr_token']}")
    assert (
        await client.post(f"{API}/sites", json={"name": "bhubaneswar plant"}, headers=o.h)
    ).status_code == 409

    r = await client.patch(
        f"{API}/sites/{s['id']}", json={"city": "Bhubaneswar", "pincode": "751024"}, headers=o.h
    )
    assert r.status_code == 200 and r.json()["city"] == "Bhubaneswar"
    bad = await client.patch(f"{API}/sites/{s['id']}", json={"pincode": "7510"}, headers=o.h)
    assert bad.status_code == 422

    g = await client.post(f"{API}/sites/{s['id']}/gates", json={"name": "Gate 2"}, headers=o.h)
    assert g.status_code == 201
    assert (await client.delete(f"{API}/sites/{s['id']}", headers=o.h)).status_code == 204
    assert (await client.get(f"{API}/sites", headers=o.h)).json() == []
    allsites = (await client.get(f"{API}/sites?include_inactive=true", headers=o.h)).json()
    assert all(not g["is_active"] for g in allsites[0]["gates"])

    # Reactivating the site brings its gates back; PATCH is_active=false cascades too.
    r = await client.patch(f"{API}/sites/{s['id']}", json={"is_active": True}, headers=o.h)
    assert r.json()["is_active"] and all(g["is_active"] for g in r.json()["gates"])
    r = await client.patch(f"{API}/sites/{s['id']}", json={"is_active": False}, headers=o.h)
    assert all(not g["is_active"] for g in r.json()["gates"])


async def test_gate_names_unique_per_site(client, f):
    o = await f.org()
    s1, s2 = await f.site(o, "Site One"), await f.site(o, "Site Two")
    dup = await client.post(
        f"{API}/sites/{s1['id']}/gates", json={"name": "main gate"}, headers=o.h
    )
    assert dup.status_code == 409
    g2 = await client.post(f"{API}/sites/{s1['id']}/gates", json={"name": "Gate 2"}, headers=o.h)
    ren = await client.patch(
        f"{API}/gates/{g2.json()['id']}", json={"name": "Main Gate"}, headers=o.h
    )
    assert ren.status_code == 409
    # The same name at a different site is fine.
    ok = await client.post(f"{API}/sites/{s2['id']}/gates", json={"name": "Gate 2"}, headers=o.h)
    assert ok.status_code == 201


async def test_rotate_qr_changes_token_and_is_audited(client, f):
    o = await f.org()
    s = await f.site(o)
    gate = s["gates"][0]
    r = await client.post(f"{API}/gates/{gate['id']}/rotate-qr", headers=o.h)
    assert r.status_code == 200
    assert r.json()["qr_token"] != gate["qr_token"]
    logs = (await client.get(f"{API}/audit-logs?action=gate.rotate_qr", headers=o.h)).json()
    assert logs["total"] == 1 and logs["items"][0]["entity_id"] == gate["id"]
    me = (await client.get(f"{API}/auth/me", headers=o.h)).json()
    assert logs["items"][0]["actor_name"] == me["full_name"]


async def test_user_rules(client, f):
    o = await f.org()
    no_phone = await client.post(
        f"{API}/users", json={"full_name": "A", "email": "a@x.com", "roles": ["host"]}, headers=o.h
    )
    assert no_phone.status_code == 422
    guard_no_pw = await client.post(
        f"{API}/users",
        json={"full_name": "G", "phone": "9000000001", "roles": ["guard"]},
        headers=o.h,
    )
    assert guard_no_pw.status_code == 422
    bad_phone = await client.post(
        f"{API}/users", json={"full_name": "B", "phone": "12345"}, headers=o.h
    )
    assert bad_phone.status_code == 422

    u = await f.user(o, phone="+91 98111 22233")
    assert u["phone"] == "+919811122233"
    dup = await client.post(
        f"{API}/users", json={"full_name": "C", "phone": "9811122233"}, headers=o.h
    )
    assert dup.status_code == 409 and dup.json()["error"]["details"]["field"] == "phone"

    self_backup = await client.patch(
        f"{API}/users/{u['id']}", json={"backup_host_id": u["id"]}, headers=o.h
    )
    assert self_backup.status_code == 422
    other = await f.user(o)
    ok = await client.patch(
        f"{API}/users/{u['id']}", json={"backup_host_id": other["id"]}, headers=o.h
    )
    assert ok.status_code == 200 and ok.json()["backup_host_id"] == other["id"]

    # Granting guard access needs a password
    r = await client.patch(f"{API}/users/{u['id']}", json={"roles": ["host", "guard"]}, headers=o.h)
    assert r.status_code == 422
    r = await client.patch(
        f"{API}/users/{u['id']}",
        json={"roles": ["host", "guard"], "password": PASSWORD},
        headers=o.h,
    )
    assert r.status_code == 200 and r.json()["has_password"]


async def test_admin_cannot_demote_self(client, f):
    o = await f.org()
    r = await client.patch(f"{API}/users/{o.admin_id}", json={"roles": ["guard"]}, headers=o.h)
    assert r.status_code == 422
    assert (await client.delete(f"{API}/users/{o.admin_id}", headers=o.h)).status_code == 422


async def test_guard_permissions(client, f):
    o = await f.org()
    s = await f.site(o)
    g, gh = await f.guard(o)
    # Guards can read sites and the host directory ...
    assert (await client.get(f"{API}/sites", headers=gh)).status_code == 200
    await f.user(o, full_name="Meera Iyer")
    d = await client.get(f"{API}/users/directory?q=meera", headers=gh)
    assert d.status_code == 200 and d.json()[0]["full_name"] == "Meera Iyer"
    assert "phone" not in d.json()[0]
    # ... but cannot manage anything.
    assert (await client.post(f"{API}/sites", json={"name": "X"}, headers=gh)).status_code == 403
    assert (await client.get(f"{API}/users", headers=gh)).status_code == 403
    assert (await client.patch(f"{API}/org", json={"name": "X"}, headers=gh)).status_code == 403
    assert (
        await client.post(f"{API}/gates/{s['gates'][0]['id']}/rotate-qr", headers=gh)
    ).status_code == 403
    assert (await client.get(f"{API}/audit-logs", headers=gh)).status_code == 403


async def test_guard_site_assignment(client, f):
    o = await f.org()
    s1, s2 = await f.site(o), await f.site(o)
    g, gh = await f.guard(o)
    r = await client.put(
        f"{API}/users/{g['id']}/sites",
        json={"site_ids": [s1["id"], s2["id"], s1["id"]]},
        headers=o.h,
    )
    assert r.status_code == 200 and sorted(r.json()["site_ids"]) == sorted([s1["id"], s2["id"]])
    me = (await client.get(f"{API}/auth/me", headers=gh)).json()
    assert len(me["site_ids"]) == 2


async def test_org_settings_validation(client, f):
    o = await f.org()
    r = await client.patch(
        f"{API}/org",
        json={"settings": {"approval_timeout_min": 10, "retention_days": 30}},
        headers=o.h,
    )
    assert r.status_code == 200
    assert r.json()["settings"]["approval_timeout_min"] == 10
    assert (
        await client.patch(f"{API}/org", json={"settings": {"typo_key": 1}}, headers=o.h)
    ).status_code == 422
    assert (
        await client.patch(f"{API}/org", json={"settings": {"retention_days": 1}}, headers=o.h)
    ).status_code == 422
    r = await client.patch(
        f"{API}/org", json={"branding": {"primary_color": "#123abc"}}, headers=o.h
    )
    assert r.json()["branding"]["primary_color"] == "#123ABC"


async def test_purposes_and_custom_fields(client, f):
    o = await f.org()
    ps = (await client.get(f"{API}/purposes", headers=o.h)).json()
    ids = [p["id"] for p in reversed(ps)]
    r = await client.put(f"{API}/purposes/order", json={"ids": ids}, headers=o.h)
    assert [p["id"] for p in r.json()] == ids
    bad_locale = await client.post(
        f"{API}/purposes", json={"label": "X", "label_i18n": {"xx": "?"}}, headers=o.h
    )
    assert bad_locale.status_code == 422

    sel = await client.post(
        f"{API}/custom-fields",
        json={"key": "ppe", "label": "PPE", "type": "select", "options": ["Yes"]},
        headers=o.h,
    )
    assert sel.status_code == 422
    dec = await client.post(
        f"{API}/custom-fields",
        json={"key": "nda", "label": "I accept the NDA", "type": "declaration", "required": False},
        headers=o.h,
    )
    assert dec.status_code == 201 and dec.json()["required"] is True
    dup = await client.post(
        f"{API}/custom-fields", json={"key": "nda", "label": "x", "type": "text"}, headers=o.h
    )
    assert dup.status_code == 409
    s = await f.site(o)
    per_site = await client.post(
        f"{API}/custom-fields",
        json={"key": "nda", "label": "x", "type": "text", "site_id": s["id"]},
        headers=o.h,
    )
    assert per_site.status_code == 201  # same key allowed at a different scope
    bad_key = await client.post(
        f"{API}/custom-fields", json={"key": "Bad Key", "label": "x", "type": "text"}, headers=o.h
    )
    assert bad_key.status_code == 422


async def test_departments(client, f):
    o = await f.org()
    d = (await client.post(f"{API}/departments", json={"name": "HR"}, headers=o.h)).json()
    u = await f.user(o, department_id=d["id"])
    lst = (await client.get(f"{API}/departments", headers=o.h)).json()
    assert lst[0]["user_count"] == 1
    assert (await client.delete(f"{API}/departments/{d['id']}", headers=o.h)).status_code == 204
    assert (await client.get(f"{API}/users/{u['id']}", headers=o.h)).json()["department_id"] is None


async def test_platform_admin_manages_orgs(client, f):
    sa = await f.platform_admin()
    r = await client.post(
        f"{API}/platform/orgs",
        json={
            "name": "Govt Office Cuttack",
            "admin_name": "Officer",
            "admin_email": "o@gov.example",
            "admin_password": "longpassword1",
        },
        headers=sa,
    )
    assert r.status_code == 201 and r.json()["user_count"] == 1
    stats = (await client.get(f"{API}/platform/stats", headers=sa)).json()
    assert stats["orgs"] == 1
    o = await f.org()
    assert (await client.get(f"{API}/platform/orgs", headers=o.h)).status_code == 403
    assert (await client.get(f"{API}/sites", headers=sa)).status_code == 403
