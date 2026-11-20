"""Create and check the WhatsApp message templates in Meta.

    python -m scripts.whatsapp_templates print    # the JSON, to review or paste
    python -m scripts.whatsapp_templates create   # submit every template for approval
    python -m scripts.whatsapp_templates status   # approval status of each one

Needs WHATSAPP_WABA_ID and WHATSAPP_ACCESS_TOKEN (create/status). Template URL buttons
point at PUBLIC_WEB_URL, so run this with the production PUBLIC_WEB_URL set. Templates
are created in English and Hindi; Meta usually reviews them within minutes to a day.
"""

import json
import sys

import httpx

from app.core.config import get_settings
from app.notifications.meta import LANGUAGES, SPECS, create_payload, template_name


def payloads() -> list[dict]:
    return [create_payload(k, loc) for k in SPECS for loc in LANGUAGES]


def _client() -> tuple[httpx.Client, str]:
    s = get_settings()
    if not s.whatsapp_waba_id or not s.whatsapp_access_token:
        sys.exit("Set WHATSAPP_WABA_ID and WHATSAPP_ACCESS_TOKEN first.")
    url = f"{s.whatsapp_graph_url.rstrip('/')}/{s.whatsapp_waba_id}/message_templates"
    headers = {"Authorization": f"Bearer {s.whatsapp_access_token}"}
    return httpx.Client(headers=headers, timeout=30), url


def create() -> None:
    client, url = _client()
    for p in payloads():
        r = client.post(url, json=p)
        data = r.json()
        if r.is_success:
            print(f"submitted  {p['name']} [{p['language']}]: {data.get('status', '?')}")
        else:
            msg = (data.get("error") or {}).get("error_user_msg") or data.get("error") or r.text
            print(f"error      {p['name']} [{p['language']}]: {msg}")


def status() -> None:
    client, url = _client()
    found: dict[tuple[str, str], str] = {}
    params: dict[str, str | int] = {"limit": 200, "fields": "name,language,status"}
    while True:
        data = client.get(url, params=params).json()
        for t in data.get("data", []):
            found[(t["name"], t["language"])] = t["status"]
        after = (data.get("paging") or {}).get("cursors", {}).get("after")
        if not after or not data.get("paging", {}).get("next"):
            break
        params["after"] = after
    missing = 0
    for key in SPECS:
        for loc in LANGUAGES:
            st = found.get((template_name(key), loc), "MISSING")
            missing += st != "APPROVED"
            print(f"{st:<10} {template_name(key)} [{loc}]")
    if missing:
        print(f"\n{missing} not approved yet. Messages using them will fail until they are.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "print"
    if cmd == "print":
        print(json.dumps(payloads(), ensure_ascii=False, indent=2))
    elif cmd == "create":
        create()
    elif cmd == "status":
        status()
    else:
        sys.exit(__doc__)
