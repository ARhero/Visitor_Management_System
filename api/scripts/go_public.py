"""Switch api/.env to running VMS publicly on one address and port (see docs/public-setup.md).

    uv run python -m scripts.go_public https://203.0.113.10:8443

- Copies the current api/.env to api/.env.dev.bak (once), so you can go back.
- Sets ENV=prod, the public address, secure cookies, WhatsApp off, no public sign-up,
  and serving the built web app from the API (WEB_DIST_DIR). On a fresh server it also
  sets the built-in database, like start.bat's first run.
- Generates the secrets production needs, unless already set: JWT_SECRET,
  PASS_SIGNING_KEY (signs visitor passes) and VAPID_PRIVATE_KEY (phone alerts).
- Makes a self-signed HTTPS certificate for the address (scripts/make_cert.py).

Run it again with a different address to change only the address and the certificate.
"""

import re
import secrets
import shutil
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from py_vapid import Vapid

from scripts import make_cert

API = Path(__file__).resolve().parents[1]
ENV = API / ".env"
DEV_SECRET = "dev-insecure-change-me"


def _one_line(pem: str) -> str:
    return '"' + pem.strip().replace("\n", "\\n") + '"'


def _lan_ips() -> list[str]:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # no packet is sent; just picks the outgoing interface
            return [s.getsockname()[0]]
    except OSError:
        return []


def main(url: str) -> None:
    u = urlsplit(url.rstrip("/"))
    if u.scheme != "https" or not u.hostname or not u.port:
        raise SystemExit(
            "Give the full public address with https and the port, e.g. https://203.0.113.10:8443"
        )
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    backup = API / ".env.dev.bak"
    if ENV.exists() and not backup.exists():
        shutil.copy(ENV, backup)
        print(f"Saved the old settings as {backup.name}")

    current = {
        m.group(1): m.group(2) for line in lines if (m := re.match(r"^([A-Z_]+)=(.*)$", line))
    }
    want: dict[str, str] = {
        "ENV": "prod",
        "PUBLIC_WEB_URL": f"{u.scheme}://{u.netloc}",
        "CORS_ORIGINS": f'["{u.scheme}://{u.netloc}"]',
        "COOKIE_SECURE": "true",
        "WHATSAPP_PROVIDER": current.get("WHATSAPP_PROVIDER", "off"),
        "WEB_DIST_DIR": "../web/dist",
        "VMS_PORT": str(u.port),
        # Only the super admin creates organizations (in /platform).
        "ALLOW_SIGNUP": "false",
    }
    # A fresh server: the built-in database, in-process jobs and files on this disk
    # (the same as start.bat's first run), unless something else is set already.
    for k, v in {
        "DATABASE_URL": "postgresql+asyncpg://vms_app:vms_app@127.0.0.1:54329/vms",
        "DATABASE_ADMIN_URL": "postgresql+asyncpg://vms:vms@127.0.0.1:54329/vms",
        "REDIS_URL": "memory://",
        "STORAGE_BACKEND": "local",
    }.items():
        if k not in current:
            want[k] = v
    if not current.get("JWT_SECRET") or DEV_SECRET in current["JWT_SECRET"]:
        want["JWT_SECRET"] = secrets.token_urlsafe(48)
    if not current.get("PASS_SIGNING_KEY", "").strip('"'):
        pem = Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        want["PASS_SIGNING_KEY"] = _one_line(pem.decode())
    if not current.get("VAPID_PRIVATE_KEY", "").strip('"'):
        v = Vapid()
        v.generate_keys()
        want["VAPID_PRIVATE_KEY"] = _one_line(v.private_pem().decode())

    out, seen = [], set()
    for line in lines:
        m = re.match(r"^([A-Z_]+)=", line)
        if m and m.group(1) in want:
            out.append(f"{m.group(1)}={want[m.group(1)]}")
            seen.add(m.group(1))
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in want.items() if k not in seen]
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"api/.env now serves VMS at {u.scheme}://{u.netloc} (ENV=prod)")

    make_cert.main([u.hostname, *[ip for ip in _lan_ips() if ip != u.hostname]])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: uv run python -m scripts.go_public https://<public-ip>:<port>")
    main(sys.argv[1])
