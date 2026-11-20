"""Default DPDP privacy notice shown to visitors before they submit.

Orgs can publish their own wording later (a new version row). The notice says what is
collected, why, how long it is kept and how to ask for erasure, as DPDP requires.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import ConsentNotice, Organization

DEFAULT_NOTICE = {
    "en": (
        "{org} collects your name, mobile number, company, photo, the person you are "
        "visiting and the purpose of your visit. If an ID is needed, only its type and "
        "last 4 characters are kept. This is used only to manage your visit and keep the "
        "premises safe. Your host and the security team can see it. It is stored in India "
        "and deleted after {days} days. You can ask {org} for a copy or for it to be "
        "erased at any time: {privacy}"
    ),
    "hi": (
        "{org} आपका नाम, मोबाइल नंबर, कंपनी, फ़ोटो, जिनसे आप मिल रहे हैं और आने का "
        "उद्देश्य दर्ज करता है। यदि पहचान पत्र आवश्यक है, तो केवल उसका प्रकार और अंतिम 4 "
        "अक्षर रखे जाते हैं। इसका उपयोग केवल आपकी विज़िट को संभालने और परिसर को सुरक्षित "
        "रखने के लिए होता है। इसे आपके मेज़बान और सुरक्षा टीम देख सकते हैं। यह भारत में "
        "संग्रहीत होता है और {days} दिनों के बाद हटा दिया जाता है। आप कभी भी {org} से इसकी "
        "प्रति या इसे हटाने का अनुरोध कर सकते हैं: {privacy}"
    ),
}


def default_notices(org_id: UUID) -> list[ConsentNotice]:
    """The body keeps {org}/{days} placeholders; they are filled in when shown, so the
    org name and retention period are always current."""
    now = datetime.now(UTC)
    return [
        ConsentNotice(
            org_id=org_id, version=1, locale=loc, body=body, is_current=True, published_at=now
        )
        for loc, body in DEFAULT_NOTICE.items()
    ]


async def current_notices(db: AsyncSession, org_id: UUID) -> dict[str, ConsentNotice]:
    rows = (
        await db.execute(
            select(ConsentNotice).where(
                ConsentNotice.org_id == org_id, ConsentNotice.is_current.is_(True)
            )
        )
    ).scalars()
    return {n.locale: n for n in rows}


def privacy_url(org: Organization) -> str:
    return f"{get_settings().public_web_url.rstrip('/')}/privacy/{org.slug}"


def render(body: str, org: Organization) -> str:
    """Placeholders: {org}, {days} (retention), {privacy} (the self-service page and the
    org's privacy contact, if set)."""
    settings = org.settings or {}
    contact = (settings.get("privacy_contact") or "").strip()
    privacy = privacy_url(org) + (f" ({contact})" if contact else "")
    return (
        body.replace("{org}", org.name)
        .replace("{days}", str(int(settings.get("retention_days", 90))))
        .replace("{privacy}", privacy)
    )
