"""Phase 4: visit log, live dashboard, reports, evacuation list and exports."""

import csv
import io
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from openpyxl import load_workbook
from sqlalchemy import select, update

from app.core.db import system_session
from app.models import AuditLog, ExportJob, Visit
from app.services import exports as export_svc
from tests.factories import bearer, messages, phone
from tests.test_guard import Gate

API = "/api/v1"
IST = ZoneInfo("Asia/Kolkata")


async def set_times(visit_id: str, **cols) -> None:
    async with system_session() as s:
        await s.execute(update(Visit).where(Visit.id == UUID(visit_id)).values(**cols))
        await s.commit()


async def get(client, path: str, h: dict, **params):
    r = await client.get(f"{API}{path}", headers=h, params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- Visit log ----------


async def test_log_filters_search_and_pages(client, f):
    g = await Gate(client, f).setup()
    vs = [await g.visit(full_name=f"Visitor {i}") for i in range(5)]
    await g.act(vs[0]["visit_id"], "check-in")

    page = await get(client, "/visits", g.o.h, limit=2)
    assert page["total"] == 5 and len(page["items"]) == 2 and page["next_cursor"]
    seen = [x["id"] for x in page["items"]]
    while page["next_cursor"]:
        page = await get(client, "/visits", g.o.h, limit=2, cursor=page["next_cursor"])
        assert page["total"] is None
        seen += [x["id"] for x in page["items"]]
    assert sorted(seen) == sorted(v["visit_id"] for v in vs)  # every visit exactly once

    only_in = await get(client, "/visits", g.o.h, status="checked_in")
    assert [x["id"] for x in only_in["items"]] == [vs[0]["visit_id"]]
    by_name = await get(client, "/visits", g.o.h, q="visitor 3")
    assert [x["visitor_name"] for x in by_name["items"]] == ["Visitor 3"]
    by_phone = await get(client, "/visits", g.o.h, q=vs[4]["phone"][-6:])
    assert [x["id"] for x in by_phone["items"]] == [vs[4]["visit_id"]]
    row = only_in["items"][0]
    assert row["host_name"] == "Meera Iyer" and row["site_name"] == "HQ"
    assert row["wait_seconds"] is not None and row["response_channel"] == "web"


async def test_log_days_are_ist(client, f):
    g = await Gate(client, f).setup()
    v = await g.visit()
    # 23:30 IST on 10 Nov is 18:00 UTC on 10 Nov; 00:30 IST on 11 Nov is 19:00 UTC on 10 Nov.
    late = datetime(2026, 11, 10, 23, 30, tzinfo=IST)
    await set_times(v["visit_id"], requested_at=late)
    on_10 = await get(client, "/visits", g.o.h, **{"from": "2026-11-10", "to": "2026-11-10"})
    on_11 = await get(client, "/visits", g.o.h, **{"from": "2026-11-11", "to": "2026-11-11"})
    assert on_10["total"] == 1 and on_11["total"] == 0
    r = await client.get(
        f"{API}/visits", headers=g.o.h, params={"from": "2026-11-11", "to": "2026-11-01"}
    )
    assert r.status_code == 422


async def test_host_sees_only_own_visits_guard_sees_none(client, f):
    g = await Gate(client, f).setup()
    other = await f.user(g.o, full_name="Other Host")
    mine = await g.visit()
    theirs = await f.checkin(g.gate_token, other["id"])
    rows = (await get(client, "/visits", g.host_h))["items"]
    assert [x["id"] for x in rows] == [mine["visit_id"]]
    # The host can't widen their view with a filter, or open someone else's visit.
    rows = (await get(client, "/visits", g.host_h, host_id=other["id"]))["items"]
    assert rows == []
    r = await client.get(f"{API}/visits/{theirs['visit_id']}", headers=g.host_h)
    assert r.status_code == 404
    assert (await client.get(f"{API}/visits", headers=g.gh)).status_code == 403


async def test_visit_detail_timeline(client, f):
    g = await Gate(client, f).setup()
    v = await g.visit()
    await g.act(v["visit_id"], "check-in")
    d = await get(client, f"/visits/{v['visit_id']}", g.o.h)
    assert [e["to_status"] for e in d["timeline"]] == ["pending", "approved", "checked_in"]
    assert d["timeline"][1]["actor_name"] == "Meera Iyer"
    assert d["timeline"][2]["actor_type"] == "guard"
    assert d["consent"]["version"] == 1 and d["photo_url"]
    sent = {m["template"] for m in d["messages"]}
    assert {"visit_request", "visit_approved", "visitor_arrived"} <= sent
    assert all(m["to"].startswith("••") for m in d["messages"])


# ---------- Reports ----------


async def test_reports_bucket_by_ist(client, f):
    g = await Gate(client, f).setup()
    a, b, c = [await g.visit(full_name=n) for n in ("A", "B", "C")]
    day = datetime(2026, 11, 2, tzinfo=IST)  # a Monday
    t_a = day.replace(hour=10, minute=5)
    await set_times(
        a["visit_id"],
        requested_at=t_a,
        responded_at=t_a + timedelta(seconds=45),
        status="checked_out",
        checked_in_at=t_a + timedelta(minutes=5),
        checked_out_at=t_a + timedelta(hours=1),
    )
    t_b = day.replace(hour=23, minute=40)  # still Monday in IST, Monday 18:10 UTC
    await set_times(
        b["visit_id"],
        requested_at=t_b,
        responded_at=t_b + timedelta(minutes=7),
        status="checked_out",
        checked_in_at=t_b + timedelta(minutes=1),
    )
    t_c = day + timedelta(days=2, hours=9)
    await set_times(
        c["visit_id"],
        requested_at=t_c,
        responded_at=None,
        response_channel=None,
        status="expired",
        approved_at=None,
    )
    params = {"from": "2026-11-01", "to": "2026-11-05"}

    tr = await get(client, "/reports/traffic", g.o.h, **params)
    assert [d["day"] for d in tr["days"]][:3] == ["2026-11-01", "2026-11-02", "2026-11-03"]
    assert [d["requests"] for d in tr["days"]] == [0, 2, 0, 1, 0]
    assert [d["checked_in"] for d in tr["days"]] == [0, 2, 0, 0, 0]
    assert tr["totals"]["visits"] == 2 and tr["totals"]["expired"] == 1
    assert tr["by_source"]["qr_self"] == 3

    ph = await get(client, "/reports/peak-hours", g.o.h, **params)
    assert ph["grid"][0][10] == 1 and ph["grid"][0][23] == 1 and sum(map(sum, ph["grid"])) == 2

    ap = await get(client, "/reports/approval-times", g.o.h, **params)
    assert ap["answered"] == 2 and ap["unanswered"] == 1
    assert {x["label"]: x["count"] for x in ap["buckets"]}["< 1 min"] == 1
    assert {x["label"]: x["count"] for x in ap["buckets"]}["5–10 min"] == 1
    assert ap["median_seconds"] == round((45 + 420) / 2)

    hosts = await get(client, "/reports/top-hosts", g.o.h, **params)
    assert hosts[0]["host_name"] == "Meera Iyer" and hosts[0]["visits"] == 3
    depts = await get(client, "/reports/departments", g.o.h, **params)
    assert depts == [{"department": "No department", "visits": 3, "hosts": 1}]

    # Another site's filter sees nothing; hosts can't read reports.
    other = await f.site(g.o, "Plant")
    empty = await get(client, "/reports/traffic", g.o.h, site_id=other["id"], **params)
    assert empty["totals"]["requests"] == 0
    assert (await client.get(f"{API}/reports/traffic", headers=g.host_h)).status_code == 403


async def test_live_dashboard(client, f):
    g = await Gate(client, f).setup()
    inside = await g.visit(accompanying_count=2)
    await g.act(inside["visit_id"], "check-in")
    await g.visit(approve=False)
    await g.visit()
    live = await get(client, "/dashboard/live", g.o.h)
    assert live["on_site"] == 1 and live["people_on_site"] == 3
    assert live["waiting_for_host"] == 1 and live["approved_not_arrived"] == 1
    assert live["today"]["requests"] == 3 and live["today"]["checked_in"] == 1
    assert live["by_gate"] == [{"site": "HQ", "gate": "Main Gate", "check_ins": 1}]
    hour = datetime.now(IST).hour
    assert live["by_hour"][hour] == 1
    assert live["by_site"][0]["people"] == 3 and live["recent"]
    assert (await client.get(f"{API}/dashboard/live", headers=g.gh)).status_code == 403


# ---------- Evacuation ----------


async def test_evacuation_list_pdf_and_share(client, f):
    g = await Gate(client, f).setup()
    v = await g.visit(full_name="हिमांशु परीक्षक", accompanying_count=1)
    await g.act(v["visit_id"], "check-in")
    await g.visit()  # approved but not inside: not on the list

    ev = await get(client, "/evacuation", g.gh, site_id=g.site["id"])
    assert ev["visits"] == 1 and ev["people"] == 2
    assert ev["rows"][0]["visitor_phone"] == v["phone"] and ev["rows"][0]["host_phone"]

    r = await client.get(f"{API}/evacuation.pdf", headers=g.gh, params={"site_id": g.site["id"]})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")

    # Share needs contacts on the site.
    r = await client.post(f"{API}/evacuation/share", json={"site_id": g.site["id"]}, headers=g.gh)
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_contacts"
    c1, c2 = phone(), phone()
    r = await client.patch(
        f"{API}/sites/{g.site['id']}",
        json={
            "safety_contacts": [
                {"name": "Fire warden", "phone": c1},
                {"name": "Security head", "phone": c2},
            ]
        },
        headers=g.o.h,
    )
    assert r.status_code == 200 and len(r.json()["safety_contacts"]) == 2
    r = await client.post(f"{API}/evacuation/share", json={"site_id": g.site["id"]}, headers=g.gh)
    assert r.status_code == 200 and r.json() == {"sent": 2, "visits": 1, "people": 2}
    msg = (await messages(c1, "evacuation"))[0].payload["text"]
    assert "1 visitors are checked in (2 people" in msg
    # The link opens a web page (phones opened from WhatsApp can't always show a PDF).
    link = re.search(r"http://web.test/e/(\S+)", msg).group(1)  # type: ignore[union-attr]
    page = (await client.get(f"{API}/public/evacuation/{link}/data")).json()
    assert page["visits"] == 1 and page["people"] == 2 and page["rows"][0]["visitor_phone"]
    assert page["org_name"]
    pdf = await client.get(f"{API}/public/evacuation/{link}")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert (await client.get(f"{API}/public/evacuation/{link}x")).status_code == 401

    # Guards only for their sites; hosts not at all.
    other = await f.site(g.o, "Plant")
    r = await client.get(f"{API}/evacuation", headers=g.gh, params={"site_id": other["id"]})
    assert r.status_code == 404
    assert (await client.get(f"{API}/evacuation", headers=g.host_h)).status_code == 403
    async with system_session() as s:
        actions = (await s.execute(select(AuditLog.action))).scalars().all()
    assert "evacuation.share" in actions and "evacuation.download" in actions


# ---------- Exports ----------


async def _export(client, h, kind: str, **filters):
    r = await client.post(f"{API}/exports", json={"kind": kind, "filters": filters}, headers=h)
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "done", job
    d = await client.get(f"{API}/exports/{job['id']}/download", headers=h)
    assert d.status_code == 200
    return job, d


async def test_exports_csv_xlsx_pdf(client, f):
    g = await Gate(client, f).setup()
    await g.visit(full_name='=HYPERLINK("http://evil")', company="+Acme")
    await g.visit(full_name="हिमांशु परीक्षक")

    job, d = await _export(client, g.o.h, "visits_csv")
    assert job["row_count"] == 2 and job["file_name"].endswith(".csv")
    text = d.content.decode("utf-8")
    assert text.startswith("﻿")
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    assert rows[0][:3] == ["Date (IST)", "Requested (IST)", "Visitor"]
    names = {r[2] for r in rows[1:]}
    assert '\'=HYPERLINK("http://evil")' in names and "हिमांशु परीक्षक" in names
    assert any(r[3] == "'+Acme" for r in rows[1:])

    _, d = await _export(client, g.o.h, "visits_xlsx", q="हिमांशु")
    ws = load_workbook(io.BytesIO(d.content)).active
    data = list(ws.values)
    assert data[0][2] == "Visitor" and len(data) == 2 and data[1][2] == "हिमांशु परीक्षक"
    assert isinstance(data[1][1], datetime)  # real dates, sortable in Excel

    for kind in ("visits_pdf", "report_pdf"):
        _, d = await _export(client, g.o.h, kind)
        assert d.content.startswith(b"%PDF") and d.headers["content-type"] == "application/pdf"

    listed = await get(client, "/exports", g.o.h)
    assert len(listed) == 4
    async with system_session() as s:
        logged = (
            (await s.execute(select(AuditLog).where(AuditLog.action == "export.create")))
            .scalars()
            .all()
        )
    assert len(logged) == 4


async def test_export_limits_access_and_expiry(client, f, monkeypatch):
    g = await Gate(client, f).setup()
    await g.visit()
    await g.visit()
    monkeypatch.setitem(export_svc.MAX_ROWS, "visits_csv", 1)
    r = await client.post(f"{API}/exports", json={"kind": "visits_csv"}, headers=g.o.h)
    assert r.json()["status"] == "failed" and "Narrow the filters" in r.json()["error"]
    monkeypatch.setitem(export_svc.MAX_ROWS, "visits_csv", 1000)

    job, _ = await _export(client, g.o.h, "visits_csv")
    # Another admin of the same org can't fetch it; hosts can't export at all.
    admin2 = await f.user(g.o, roles=["org_admin", "host"], password="correct-horse-battery")
    h2 = bearer(UUID(admin2["id"]), g.o.id, ["org_admin", "host"])
    assert (await client.get(f"{API}/exports/{job['id']}/download", headers=h2)).status_code == 404
    r = await client.post(f"{API}/exports", json={"kind": "visits_csv"}, headers=g.host_h)
    assert r.status_code == 403

    async with system_session() as s:
        await s.execute(
            update(ExportJob)
            .where(ExportJob.id == UUID(job["id"]))
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await s.commit()
    assert await export_svc.purge_expired() == 1
    r = await client.get(f"{API}/exports/{job['id']}/download", headers=g.o.h)
    assert r.status_code == 409
    assert (await get(client, f"/exports/{job['id']}", g.o.h))["status"] == "expired"
