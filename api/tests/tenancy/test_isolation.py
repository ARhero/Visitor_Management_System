"""Proof that one organization can never read or change another's data.

Layer 1 (API): every route that takes a resource id is called by org B's admin
with org A's ids. Each must answer 404 and leave A's data untouched.

Layer 2 (DB): raw SQL on the restricted role shows RLS hides/blocks rows even
when the application filter is bypassed entirely.
"""

import re
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.db import admin_engine, app_engine
from app.main import app

API = "/api/v1"
PARAM = re.compile(r"{(\w+)}")
# Every path parameter used by org-scoped routes must be listed here. If you add a
# route with a new parameter, add it to OrgCtx.ids in factories.populated().
KNOWN_PARAMS = {
    "site_id",
    "gate_id",
    "department_id",
    "user_id",
    "purpose_id",
    "field_id",
    "visit_id",
    "invite_id",
    "guest_id",
    "entry_id",
    "export_id",
    "request_id",
}
# Not staff-authenticated: covered by tests/tenancy/test_public_isolation.py instead.
TOKEN_ROUTES = ("platform", "auth", "public", "webhooks", "dev")


def org_routes() -> list[tuple[str, str]]:
    # The OpenAPI schema is the public, complete list of routes (incl. nested routers).
    out = []
    for path, ops in app.openapi()["paths"].items():
        if not path.startswith(API) or path.startswith(tuple(f"{API}/{p}" for p in TOKEN_ROUTES)):
            continue
        if PARAM.search(path):
            out.extend((m.upper(), path) for m in ops)
    return sorted(out)


def test_every_param_is_known():
    params = {p for _, path in org_routes() for p in PARAM.findall(path)}
    assert params <= KNOWN_PARAMS, f"Add to tenancy matrix: {params - KNOWN_PARAMS}"
    assert len(org_routes()) >= 15  # sanity: the matrix is actually exercising routes


async def test_cross_tenant_route_matrix(client, f):
    a = await f.populated("Org A")
    b = await f.populated("Org B")
    before = (await client.get(f"{API}/sites/{a.ids['site_id']}", headers=a.h)).json()

    failures = []
    for method, path in org_routes():
        url = PARAM.sub(lambda m: a.ids[m.group(1)], path)
        r = await client.request(method, url, headers=b.h, json={})
        if r.status_code != 404:
            failures.append(f"{method} {path} -> {r.status_code} {r.text[:120]}")
    assert not failures, "Cross-tenant access not blocked:\n" + "\n".join(failures)

    # Org A's data is unchanged and still reachable by A.
    after = (await client.get(f"{API}/sites/{a.ids['site_id']}", headers=a.h)).json()
    assert after == before
    host = await client.get(f"{API}/users/{a.ids['user_id']}", headers=a.h)
    assert host.status_code == 200 and host.json()["is_active"]


async def test_lists_only_show_own_org(client, f):
    a = await f.populated("Org A")
    b = await f.populated("Org B")
    for path in ("/sites", "/departments", "/purposes", "/custom-fields", "/users", "/audit-logs"):
        body = (await client.get(f"{API}{path}", headers=b.h)).json()
        items = body["items"] if isinstance(body, dict) else body
        ids = {i["id"] for i in items}
        assert not ids & set(map(str, a.ids.values())), path
    d = (await client.get(f"{API}/users/directory?q=person", headers=b.h)).json()
    assert a.ids["user_id"] not in {x["id"] for x in d}
    assert (await client.get(f"{API}/org", headers=b.h)).json()["id"] == str(b.id)


async def test_cannot_reference_other_orgs_rows_in_bodies(client, f):
    a = await f.populated("Org A")
    b = await f.populated("Org B")
    cases = [
        (
            "POST",
            "/users",
            {"full_name": "X", "phone": "9000000099", "department_id": a.ids["department_id"]},
        ),
        (
            "POST",
            "/users",
            {"full_name": "X", "phone": "9000000098", "primary_site_id": a.ids["site_id"]},
        ),
        (
            "POST",
            "/users",
            {"full_name": "X", "phone": "9000000097", "backup_host_id": a.ids["user_id"]},
        ),
        ("PATCH", f"/users/{b.ids['user_id']}", {"department_id": a.ids["department_id"]}),
        ("PUT", f"/users/{b.ids['user_id']}/sites", {"site_ids": [a.ids["site_id"]]}),
        (
            "POST",
            "/custom-fields",
            {"key": "x1", "label": "x", "type": "text", "site_id": a.ids["site_id"]},
        ),
        ("PUT", "/purposes/order", {"ids": [a.ids["purpose_id"]]}),
        ("PUT", "/custom-fields/order", {"ids": [a.ids["field_id"]]}),
    ]
    for method, path, body in cases:
        r = await client.request(method, f"{API}{path}", headers=b.h, json=body)
        assert r.status_code in (404, 422), f"{method} {path} -> {r.status_code}"


async def test_token_for_other_org_user_rejected(client, f):
    """A token whose sub is a real user but whose org claim is forged is refused."""
    from tests.factories import bearer

    a = await f.org()
    b = await f.org()
    forged = bearer(a.admin_id, b.id, ["org_admin"])
    assert (await client.get(f"{API}/sites", headers=forged)).status_code == 401


# ---------------- Database layer ----------------


async def _org_ids(f):
    a = await f.populated("Org A")
    b = await f.populated("Org B")
    return a, b


async def test_rls_no_org_context_sees_nothing(f):
    await _org_ids(f)
    async with app_engine().connect() as c:
        for t in (
            "users",
            "sites",
            "gates",
            "departments",
            "purposes",
            "audit_logs",
            "organizations",
        ):
            n = (await c.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one()
            assert n == 0, f"{t} visible without org context"


async def test_rls_hides_other_org_even_without_app_filter(f):
    a, b = await _org_ids(f)
    async with app_engine().begin() as c:
        await c.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": str(b.id)})
        orgs = (await c.execute(text("SELECT DISTINCT org_id FROM users"))).scalars().all()
        assert orgs == [b.id]
        hit = (
            await c.execute(
                text("SELECT count(*) FROM sites WHERE id = :i"), {"i": a.ids["site_id"]}
            )
        ).scalar_one()
        assert hit == 0
        upd = await c.execute(
            text("UPDATE sites SET name = 'pwned' WHERE id = :i"), {"i": a.ids["site_id"]}
        )
        assert upd.rowcount == 0
        dele = await c.execute(text("DELETE FROM users WHERE org_id = :o"), {"o": a.id})
        assert dele.rowcount == 0


async def test_rls_blocks_writing_rows_into_other_org(f):
    a, b = await _org_ids(f)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with app_engine().begin() as c:
            await c.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": str(b.id)})
            await c.execute(
                text(
                    "INSERT INTO departments (id, org_id, name, created_at, updated_at) "
                    "VALUES (:i, :o, 'Evil', now(), now())"
                ),
                {"i": uuid.uuid4(), "o": a.id},
            )
    with pytest.raises(DBAPIError, match="row-level security"):
        async with app_engine().begin() as c:
            await c.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": str(b.id)})
            await c.execute(
                text("UPDATE users SET org_id = :a WHERE org_id = :b"), {"a": a.id, "b": b.id}
            )


async def test_composite_fk_blocks_cross_org_links_even_for_owner(f):
    a, b = await _org_ids(f)
    with pytest.raises(IntegrityError):
        async with admin_engine().begin() as c:  # owner role, RLS bypassed
            await c.execute(
                text("UPDATE users SET department_id = :d WHERE id = :u"),
                {"d": a.ids["department_id"], "u": b.ids["user_id"]},
            )


async def test_every_org_table_has_rls_policy():
    async with admin_engine().connect() as c:
        rows = (
            await c.execute(
                text("""
            SELECT c.relname, c.relrowsecurity,
                   EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid) AS has_policy
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
              AND EXISTS (SELECT 1 FROM information_schema.columns col
                          WHERE col.table_name = c.relname AND col.column_name = 'org_id')
              AND c.relname <> 'refresh_tokens'
        """)
            )
        ).all()
    assert rows
    missing = [r.relname for r in rows if not (r.relrowsecurity and r.has_policy)]
    assert not missing, f"Tables without RLS: {missing}"


async def test_app_role_is_restricted():
    async with app_engine().connect() as c:
        su, bypass = (
            await c.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
        assert not su and not bypass
        for t in ("platform_users", "refresh_tokens"):
            with pytest.raises(DBAPIError, match="permission denied"):
                async with c.begin_nested():
                    await c.execute(text(f"SELECT 1 FROM {t}"))


async def test_audit_log_is_append_only(f):
    a, _ = await _org_ids(f)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with app_engine().begin() as c:
            await c.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": str(a.id)})
            await c.execute(text("DELETE FROM audit_logs"))
