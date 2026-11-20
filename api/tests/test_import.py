API = "/api/v1"


def _csv(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode()


async def _upload(client, o, data: bytes, dry_run: bool):
    return await client.post(
        f"{API}/users/import?dry_run={'true' if dry_run else 'false'}",
        files={"file": ("hosts.csv", data, "text/csv")},
        headers=o.h,
    )


async def test_template_downloads(client, f):
    o = await f.org()
    r = await client.get(f"{API}/users/import/template.csv", headers=o.h)
    assert r.status_code == 200 and r.text.startswith("full_name,phone")


async def test_dry_run_reports_errors_and_writes_nothing(client, f):
    o = await f.org()
    await f.site(o, "Head Office")
    data = _csv(
        "Name,Mobile,Email,Department,Site",
        "Priya Sharma,9876500001,priya@x.com,Finance,Head Office",
        "Bad Phone,12345,,Finance,",
        "Dup Phone,9876500001,,,",
        "No Site,9876500003,,,Nowhere",
        ",,,,",
    )
    r = await _upload(client, o, data, dry_run=True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] and body["total"] == 4 and body["errors"] == 3 and body["created"] == 1
    assert body["new_departments"] == ["Finance"]
    errs = {row["row"]: row["errors"] for row in body["rows"]}
    assert any("phone" in e for e in errs[3])
    assert any("repeats row 2" in e for e in errs[4])
    assert any("Nowhere" in e for e in errs[5])
    assert (await client.get(f"{API}/users?role=host", headers=o.h)).json()["total"] == 0


async def test_commit_refuses_file_with_errors(client, f):
    o = await f.org()
    r = await _upload(client, o, _csv("full_name,phone", "Ok,9876500001", "Bad,1"), dry_run=False)
    assert r.json()["dry_run"] is True  # nothing committed
    assert (await client.get(f"{API}/users?role=host", headers=o.h)).json()["total"] == 0


async def test_commit_creates_updates_and_links_backups(client, f):
    o = await f.org()
    existing = await f.user(o, full_name="Old Name", phone="9876500002")
    data = _csv(
        "full_name,phone,email,department,designation,backup_host_phone",
        "Anil Das,9876500001,anil@x.com,Operations,Plant Head,9876500002",
        "New Name,9876500002,,Operations,,",
        "Sita Rao,+91 98765 00003,,HR,,",
    )
    r = await _upload(client, o, data, dry_run=False)
    body = r.json()
    assert not body["dry_run"] and body["created"] == 2 and body["updated"] == 1, body
    users = {
        u["phone"]: u
        for u in (await client.get(f"{API}/users?role=host", headers=o.h)).json()["items"]
    }
    assert users["+919876500002"]["full_name"] == "New Name"
    assert users["+919876500002"]["id"] == existing["id"]
    assert users["+919876500001"]["backup_host_id"] == existing["id"]
    depts = {d["name"] for d in (await client.get(f"{API}/departments", headers=o.h)).json()}
    assert depts == {"Operations", "HR"}
    logs = (await client.get(f"{API}/audit-logs?action=user.import", headers=o.h)).json()
    assert logs["items"][0]["diff"]["created"] == 2


async def test_import_rejects_admin_roles_and_bad_headers(client, f):
    o = await f.org()
    r = await _upload(
        client, o, _csv("full_name,phone,roles", "X,9876500001,org_admin"), dry_run=True
    )
    assert r.json()["errors"] == 1
    r = await _upload(client, o, _csv("foo,bar", "1,2"), dry_run=True)
    assert r.status_code == 422 and r.json()["error"]["code"] == "missing_columns"
