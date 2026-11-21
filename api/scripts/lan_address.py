"""Point QR codes and links at this PC's Wi-Fi address, so phones on the same network can
use them (start.bat runs this on every start).

    uv run python -m scripts.lan_address

When PUBLIC_WEB_URL in api/.env is localhost or a local network address, it becomes
https://<this PC's current local address>:5173, so it follows the PC when the router
hands out a new address. https makes the dev server use a self-signed certificate, which
the guard's camera needs (phones show a warning once).

Left alone: production settings (ENV=prod), any other address or name you set yourself,
and when LAN_ADDRESS=off is in api/.env. With no network, nothing changes.
"""

import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urlsplit

ENV = Path(__file__).resolve().parents[1] / ".env"
PORT = 5173


def lan_ip() -> str | None:
    """The address this PC uses on its local network (not VPNs like Tailscale)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # sends nothing; picks the outgoing interface
            ip = s.getsockname()[0]
    except OSError:
        return None
    a = ipaddress.ip_address(ip)
    return ip if a.is_private and a not in ipaddress.ip_network("100.64.0.0/10") else None


def _ours(url: str) -> bool:
    """Is this an address we may manage: localhost or a local IP on the dev port?"""
    u = urlsplit(url)
    if u.hostname in (None, "localhost", "127.0.0.1"):
        return True
    try:
        return ipaddress.ip_address(u.hostname).is_private and u.port in (None, PORT)
    except ValueError:
        return False  # a name (a domain): set on purpose


def main() -> None:
    if not ENV.exists():
        return
    lines = ENV.read_text(encoding="utf-8").splitlines()
    cur = {
        m.group(1): m.group(2).strip() for ln in lines if (m := re.match(r"^([A-Z_]+)=(.*)$", ln))
    }
    if cur.get("ENV") == "prod" or cur.get("LAN_ADDRESS", "").lower() == "off":
        return
    url = cur.get("PUBLIC_WEB_URL", "http://localhost:5173")
    if not _ours(url):
        return
    ip = lan_ip()
    if ip is None:
        print("No local network found: QR codes keep using this PC only (localhost).")
        return
    new = f"https://{ip}:{PORT}"
    if url == new:
        return
    want = {
        "PUBLIC_WEB_URL": new,
        "CORS_ORIGINS": f'["http://localhost:{PORT}","https://localhost:{PORT}","{new}"]',
    }
    out, seen = [], set()
    for ln in lines:
        m = re.match(r"^([A-Z_]+)=", ln)
        if m and m.group(1) in want:
            out.append(f"{m.group(1)}={want[m.group(1)]}")
            seen.add(m.group(1))
        else:
            out.append(ln)
    out += [f"{k}={v}" for k, v in want.items() if k not in seen]
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"QR codes and links now use {new} (this PC on your Wi-Fi).")
    print("Phones: same Wi-Fi; accept the certificate warning once. Re-download QR posters.")
    print("If VMS was already running, close its two windows and run start.bat again.")


if __name__ == "__main__":
    main()
