"""Meta Cloud API: template payloads, error handling, opt-out (STOP) and the 24h window."""

import json
import re

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import system_session
from app.models import NotificationLog, WhatsAppContact
from app.notifications import dispatcher, meta, providers
from app.notifications.templates import TEMPLATES
from tests.factories import messages
from tests.test_approval import _visit, tap

API = "/api/v1"

# What the call sites put in params (see visits.ask_approver, guard.check_in, ...).
PARAMS = {
    "code": "123456",
    "org": "Acme",
    "site": "HQ",
    "gate": "Main gate",
    "visitor": "Ravi Kumar",
    "company": ", Acme Logistics",
    "purpose": "Meeting",
    "details": "\nNote: bring the contract\n2 people with them\nVehicle: OD02AB1234",
    "host": "Meera",
    "link": "http://web.test/r/tok123",
    "pass_url": "http://web.test/p/pass456",
    "message": " “Five minutes”",
    "note": "\nLet in by security: host unreachable",
    "when": " on 21 Nov, 10:00–12:00",
    "title": " Quarterly review.",
    "time": "11:42 AM",
    "visits": "3",
    "people": "5",
    "by": "Anil",
}
BUTTONS = [{"id": f"v1|abc|{a}", "title": a} for a in ("approve", "wait", "reject")]


def test_every_message_has_a_template_or_is_session_text():
    assert set(TEMPLATES) == set(meta.SPECS) | meta.SESSION_ONLY


def test_every_language_has_every_message():
    """Adding a language means translating all of these (docs/adding-a-language.md)."""
    from string import Formatter

    from app.core.i18n import LOCALES
    from app.notifications.templates import BUTTONS, OUTCOMES
    from app.services.consent import DEFAULT_NOTICE

    def fields(s: str) -> set[str]:
        return {f for _, f, _, _ in Formatter().parse(s) if f}

    for key, t in TEMPLATES.items():
        assert set(t) == set(LOCALES), key
        assert len({frozenset(fields(x)) for x in t.values()}) == 1, f"{key}: placeholders differ"
    for key, spec in meta.SPECS.items():
        assert set(spec.body) == set(LOCALES), key
    for table in (BUTTONS, OUTCOMES):
        for key, t in table.items():
            assert set(t) == set(LOCALES), key
    assert set(DEFAULT_NOTICE) == set(LOCALES)


@pytest.mark.parametrize("key", sorted(meta.SPECS))
@pytest.mark.parametrize("locale", ["en", "hi"])
def test_template_payloads_follow_meta_rules(key, locale):
    spec = meta.SPECS[key]
    body = spec.body[locale]
    numbers = sorted({int(n) for n in re.findall(r"\{\{(\d+)\}\}", body)})
    assert numbers == list(range(1, len(spec.vars) + 1))
    assert not body.startswith("{{") and not body.rstrip().endswith("}}")

    p = meta.message_payload("+919800000001", key, locale, PARAMS, "", BUTTONS)
    assert p["to"] == "919800000001" and p["type"] == "template"
    t = p["template"]
    assert t["name"] == f"vms_{key}" and t["language"]["code"] == locale
    texts = [x["text"] for c in t["components"] if c["type"] == "body" for x in c["parameters"]]
    assert len(texts) == len(spec.vars)
    for x in texts:  # Meta rejects empty variables, new lines, tabs and 5+ spaces
        assert x.strip() and not re.search(r"[\n\t]| {5,}", x), (key, x)
    url = [c for c in t["components"] if c.get("sub_type") == "url"]
    if spec.url_param:
        suffix = url[-1]["parameters"][0]["text"]
        assert "http://web.test/" + suffix == PARAMS[spec.url_param]
    quick = [c for c in t["components"] if c.get("sub_type") == "quick_reply"]
    assert len(quick) == (3 if spec.quick_replies else 0)
    if quick:
        assert [c["parameters"][0]["payload"] for c in quick] == [b["id"] for b in BUTTONS]
        assert int(url[0]["index"]) == 3  # the URL button comes after the quick replies

    created = meta.create_payload(key, locale)
    assert json.dumps(created)  # serializable, and buttons short enough for WhatsApp
    for c in created["components"]:
        for b in c.get("buttons", []):
            assert len(b.get("text", "")) <= 25


def test_values_read_naturally():
    p = meta.message_payload("+91980", "visit_request", "en", PARAMS, "", BUTTONS)
    texts = [x["text"] for x in p["template"]["components"][0]["parameters"]]
    assert texts == [
        "HQ, Main gate",
        "Ravi Kumar, Acme Logistics",
        "Meeting",
        "Note: bring the contract · 2 people with them · Vehicle: OD02AB1234",
    ]
    empty = {**PARAMS, "company": "", "details": "", "message": "", "note": "", "title": ""}
    p = meta.message_payload("+91980", "visit_request", "hi", empty, "", BUTTONS)
    assert p["template"]["components"][0]["parameters"][3]["text"] == "कोई अन्य विवरण नहीं।"
    p = meta.message_payload("+91980", "visit_waiting", "en", PARAMS, "", [])
    assert (
        p["template"]["components"][0]["parameters"][1]["text"] == "Their message: “Five minutes”."
    )
    p = meta.message_payload("+91980", "visitor_arrived", "en", empty, "", [])
    assert p["template"]["components"][0]["parameters"][2]["text"] == "No notes from security."
    otp = meta.message_payload("+91980", "otp", "en", PARAMS, "", [])
    assert otp["template"]["components"][1] == {
        "type": "button",
        "sub_type": "url",
        "index": "0",
        "parameters": [{"type": "text", "text": "123456"}],
    }
    ack = meta.message_payload("+91980", "response_ack", "en", {}, "Done: Ravi approved.", [])
    assert ack["type"] == "text" and ack["text"]["body"] == "Done: Ravi approved."


@pytest.fixture
def meta_settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "whatsapp_phone_number_id", "1234567890")
    monkeypatch.setattr(s, "whatsapp_access_token", "test-token")


def _provider(handler) -> providers.MetaCloudProvider:
    return providers.MetaCloudProvider(transport=httpx.MockTransport(handler))


OUT = providers.Outbound(
    to="+919800000001", template="visit_approved", locale="en", params=PARAMS, text=""
)


async def test_meta_provider_sends_and_returns_the_message_id(meta_settings):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(req.url), req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.ABC"}]})

    assert await _provider(handler).send(OUT) == "wamid.ABC"
    assert seen["url"] == "https://graph.facebook.com/v21.0/1234567890/messages"
    assert seen["auth"] == "Bearer test-token"
    assert seen["body"]["template"]["name"] == "vms_visit_approved"


@pytest.mark.parametrize(
    ("status", "code", "retry"),
    [
        (400, 132001, False),  # template does not exist / not approved
        (400, 131026, False),  # message undeliverable
        (400, 131030, False),  # recipient not in allowed list (test number)
        (429, 130429, True),  # throughput limit
        (400, 131056, True),  # pair rate limit
        (503, 1, True),  # Meta outage
    ],
)
async def test_meta_errors_are_classified(meta_settings, status, code, retry):
    def handler(req):  # noqa: ANN001, ARG001
        return httpx.Response(status, json={"error": {"code": code, "message": "nope"}})

    with pytest.raises(providers.SendError) as e:
        await _provider(handler).send(OUT)
    assert e.value.retry is retry and e.value.code == code


async def test_meta_network_error_is_retried(meta_settings):
    def handler(req):  # noqa: ANN001
        raise httpx.ConnectTimeout("slow", request=req)

    with pytest.raises(providers.SendError) as e:
        await _provider(handler).send(OUT)
    assert e.value.retry is True


def test_meta_provider_needs_credentials():
    with pytest.raises(RuntimeError, match="WHATSAPP_PHONE_NUMBER_ID"):
        providers.MetaCloudProvider()


async def test_permanent_failure_is_not_retried(client, f, meta_settings, monkeypatch):
    def handler(req):  # noqa: ANN001, ARG001
        return httpx.Response(400, json={"error": {"code": 132001, "message": "no template"}})

    monkeypatch.setattr(dispatcher, "get_provider", lambda: _provider(handler))
    _, host, _, _ = await _visit(client, f)
    msg = (await messages(host["phone"], "visit_request"))[0]
    assert msg.status == "failed" and msg.attempts == 1 and "#132001" in msg.error


async def test_stop_and_start(client, f):
    o, host, v, _ = await _visit(client, f)
    r = await client.post(
        f"{API}/dev/whatsapp/inbound", json={"phone": host["phone"], "text": "STOP"}
    )
    assert r.json()["results"] == ["keyword:stop"]

    # The host opted out: the next request to them is recorded but not sent.
    site = await f.site(o, "Annex")
    await f.checkin(site["gates"][0]["qr_token"], host["id"])
    latest = (await messages(host["phone"], "visit_request"))[0]
    assert latest.status == "skipped" and "STOP" in latest.error

    # An admin re-adding them doesn't undo it; only the person can.
    from app.notifications import contacts

    await contacts.opt_in(host["phone"], "added_by_org")
    async with system_session() as db:
        c = (
            await db.execute(select(WhatsAppContact).where(WhatsAppContact.phone == host["phone"]))
        ).scalar_one()
        assert c.opted_out_at is not None

    r = await client.post(
        f"{API}/dev/whatsapp/inbound", json={"phone": host["phone"], "text": "start"}
    )
    assert r.json()["results"] == ["keyword:start"]
    await f.checkin(site["gates"][0]["qr_token"], host["id"])
    assert (await messages(host["phone"], "visit_request"))[0].status == "sent"


async def test_visitor_asking_for_an_otp_undoes_their_stop(client, f):
    o = await f.org()
    site = await f.site(o, "HQ")
    phone = "+919800000123"
    await client.post(f"{API}/dev/whatsapp/inbound", json={"phone": phone, "text": "रोकें"})
    r = await client.post(
        f"{API}/public/otp/send",
        json={"gate_token": site["gates"][0]["qr_token"], "phone": phone},
    )
    assert r.status_code == 202
    assert (await messages(phone, "otp"))[0].status == "sent"


async def test_free_text_only_inside_the_24h_window(client, f):
    o, host, v, _ = await _visit(client, f)
    # A tap opens the window, so the acknowledgement goes out.
    await tap(client, host["phone"], "approve")
    assert (await messages(host["phone"], "response_ack"))[0].status == "sent"

    # Without a recent message from the person, free text is skipped.
    async with system_session() as db:
        row = NotificationLog(
            org_id=o.id,
            recipient_phone="+919800000999",
            template_key="response_ack",
            locale="en",
            provider="mock",
            status="queued",
            payload={"params": {}, "buttons": [], "text": "Done"},
        )
        db.add(row)
        await db.commit()
    await dispatcher.deliver([row.id])
    async with system_session() as db:
        row = await db.get(NotificationLog, row.id)
        assert row.status == "skipped" and "24-hour" in row.error
