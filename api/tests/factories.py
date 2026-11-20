import io
import itertools
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select

from app.core.db import system_session
from app.core.security import create_access_token, hash_password
from app.models import NotificationLog, PlatformUser
from app.services.orgs import create_org_with_admin

_n = itertools.count(1)
PASSWORD = "correct-horse-battery"


def phone() -> str:
    return f"+9198{next(_n):08d}"


@dataclass
class OrgCtx:
    id: UUID
    slug: str
    admin_id: UUID
    admin_email: str
    token: str
    ids: dict[str, Any] = field(default_factory=dict)

    @property
    def h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def png(color: str = "teal") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), color).save(buf, format="PNG")
    return buf.getvalue()


async def messages(phone: str, template: str | None = None) -> list[NotificationLog]:
    """Mock WhatsApp outbox for a phone, newest first."""
    async with system_session() as s:
        q = (
            select(NotificationLog)
            .where(NotificationLog.recipient_phone == phone)
            .order_by(NotificationLog.created_at.desc())
        )
        if template:
            q = q.where(NotificationLog.template_key == template)
        return list((await s.execute(q)).scalars())


def bearer(
    user_id: UUID, org_id: UUID | None, roles: list[str], scope: str = "org"
) -> dict[str, str]:
    tok, _ = create_access_token(subject=user_id, scope=scope, org_id=org_id, roles=roles)  # type: ignore[arg-type]
    return {"Authorization": f"Bearer {tok}"}


class Factory:
    def __init__(self, client: AsyncClient) -> None:
        self.c = client

    async def org(self, name: str | None = None) -> OrgCtx:
        n = next(_n)
        email = f"admin{n}@example.com"
        async with system_session() as s:
            org, admin = await create_org_with_admin(
                s,
                name=name or f"Org {n}",
                admin_name=f"Admin {n}",
                admin_email=email,
                admin_password=PASSWORD,
                status="active",
            )
            await s.commit()
        h = bearer(admin.id, org.id, admin.roles)
        return OrgCtx(org.id, org.slug, admin.id, email, h["Authorization"].split()[1])

    async def platform_admin(self) -> dict[str, str]:
        async with system_session() as s:
            pu = PlatformUser(
                email=f"sa{next(_n)}@vms.test",
                full_name="Super",
                password_hash=hash_password(PASSWORD),
            )
            s.add(pu)
            await s.commit()
        return bearer(pu.id, None, ["super_admin"], scope="platform")

    async def site(self, o: OrgCtx, name: str | None = None) -> dict:
        r = await self.c.post(
            "/api/v1/sites", json={"name": name or f"Site {next(_n)}"}, headers=o.h
        )
        assert r.status_code == 201, r.text
        return r.json()

    async def user(self, o: OrgCtx, **kw: Any) -> dict:
        body = {"full_name": f"Person {next(_n)}", "phone": phone(), "roles": ["host"]} | kw
        r = await self.c.post("/api/v1/users", json=body, headers=o.h)
        assert r.status_code == 201, r.text
        return r.json()

    async def guard(self, o: OrgCtx) -> tuple[dict, dict[str, str]]:
        u = await self.user(o, roles=["guard"], password=PASSWORD)
        return u, bearer(UUID(u["id"]), o.id, ["guard"])

    async def visitor_token(self, gate_token: str, phone_: str) -> str:
        from app.core.redis import get_redis

        gate = (await self.c.get(f"/api/v1/public/gates/{gate_token}")).json()
        if not gate.get("verify_phone", True):  # no codes: the number is just typed in
            r = await self.c.post(
                "/api/v1/public/start", json={"gate_token": gate_token, "phone": phone_}
            )
            assert r.status_code == 200, r.text
            return r.json()["token"]
        for k in [k async for k in get_redis().scan_iter(f"otp-cd:*:{phone_}")]:
            await get_redis().delete(k)  # tests may verify the same phone twice
        r = await self.c.post(
            "/api/v1/public/otp/send", json={"gate_token": gate_token, "phone": phone_}
        )
        assert r.status_code == 202, r.text
        code = (await messages(phone_, "otp"))[0].payload["params"]["code"]
        r = await self.c.post(
            "/api/v1/public/otp/verify",
            json={"gate_token": gate_token, "phone": phone_, "code": code},
        )
        assert r.status_code == 200, r.text
        return r.json()["token"]

    async def checkin(
        self, gate_token: str, host_id: str, phone_: str | None = None, **body: Any
    ) -> dict[str, Any]:
        """Full visitor flow up to submission. Returns the response plus ``token``
        (status token), ``vtoken`` (visitor token) and ``phone``."""
        phone_ = phone_ or phone()
        vt = await self.visitor_token(gate_token, phone_)
        vh = {"Authorization": f"Bearer {vt}"}
        gate = (await self.c.get(f"/api/v1/public/gates/{gate_token}")).json()
        up = await self.c.post(
            "/api/v1/public/uploads",
            files={"file": ("me.png", png(), "image/png")},
            data={"kind": "selfie"},
            headers=vh,
        )
        assert up.status_code == 201, up.text
        payload = {
            "full_name": "Ravi Kumar",
            "company": "Acme Pvt Ltd",
            "host_id": host_id,
            "purpose_id": gate["purposes"][0]["id"],
            "photo_upload": up.json()["upload_token"],
            "consent_notice_id": gate["notices"]["en"]["id"],
            "consent": True,
        } | body
        r = await self.c.post("/api/v1/public/visits", json=payload, headers=vh)
        out = {"status_code": r.status_code, **r.json()}
        out.update(token=out.get("status_token"), vtoken=vt, phone=phone_)
        return out

    async def invite(self, o: OrgCtx, site_id: str, host_id: str, **body: Any) -> dict[str, Any]:
        """A one-guest invite for today, created by the admin for ``host_id``."""
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("Asia/Kolkata"))
        payload = {
            "site_id": site_id,
            "host_id": host_id,
            "kind": "single",
            "title": "Board meeting",
            "date": today.date().isoformat(),
            "start_time": "00:00",
            "end_time": "23:59",
            "guests": [{"name": "Vikram Seth", "phone": phone(), "company": "Partner Co"}],
        } | body
        if payload["kind"] == "multi_day" and "end_date" not in payload:
            payload["end_date"] = (today + timedelta(days=3)).date().isoformat()
        r = await self.c.post("/api/v1/invites", json=payload, headers=o.h)
        assert r.status_code == 201, r.text
        return r.json()

    async def populated(self, name: str | None = None) -> OrgCtx:
        """An org with one of every resource type, ids stored in ``o.ids``."""
        o = await self.org(name)
        site = await self.site(o)
        dept = (
            await self.c.post("/api/v1/departments", json={"name": "Finance"}, headers=o.h)
        ).json()
        host = await self.user(o, department_id=dept["id"], primary_site_id=site["id"])
        purpose = (
            await self.c.post("/api/v1/purposes", json={"label": "Audit"}, headers=o.h)
        ).json()
        field_ = (
            await self.c.post(
                "/api/v1/custom-fields",
                json={"key": "laptop_serial", "label": "Laptop serial", "type": "text"},
                headers=o.h,
            )
        ).json()
        visit = await self.checkin(site["gates"][0]["qr_token"], host["id"])
        assert visit["status_code"] == 201, visit
        invite = await self.invite(o, site["id"], host["id"])
        entry = (
            await self.c.post(
                "/api/v1/blacklist",
                json={"phone": phone(), "reason": "Test entry", "action": "alert"},
                headers=o.h,
            )
        ).json()
        export = (
            await self.c.post("/api/v1/exports", json={"kind": "visits_csv"}, headers=o.h)
        ).json()
        from app.models import PrivacyRequest
        from app.services.privacy import mask, phone_hash

        async with system_session() as s:
            req = PrivacyRequest(
                org_id=o.id,
                phone=visit["phone"],
                phone_masked=mask(visit["phone"]),
                phone_hash=phone_hash(o.id, visit["phone"]),
                status="open",
            )
            s.add(req)
            await s.commit()
        o.ids = {
            "request_id": str(req.id),
            "export_id": export["id"],
            "invite_id": invite["id"],
            "guest_id": invite["guests"][0]["id"],
            "entry_id": entry["id"],
            "visit_id": visit["visit_id"],
            "site_id": site["id"],
            "gate_id": site["gates"][0]["id"],
            "department_id": dept["id"],
            "user_id": host["id"],
            "purpose_id": purpose["id"],
            "field_id": field_["id"],
        }
        return o
