import re
from datetime import time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.i18n import Locale
from app.schemas.common import Name, Phone, Timestamps

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class OrgSettings(BaseModel):
    """Per-org behaviour. Unknown keys are rejected so typos don't silently do nothing."""

    model_config = ConfigDict(extra="forbid")

    approval_timeout_min: int = Field(5, ge=1, le=60)
    max_escalations: int = Field(2, ge=0, le=5)
    auto_checkout_time: time = time(20, 0)  # IST wall-clock
    retention_days: int = Field(90, ge=7, le=3650)
    require_selfie: bool = True
    id_proof_mode: Literal["off", "optional", "required"] = "off"
    store_id_image: bool = False
    guard_manual_requires_otp: bool = False
    # Visitors confirm their number with a WhatsApp code (ignored when WhatsApp is off).
    verify_visitor_phone: bool = True
    enabled_locales: list[Locale] = ["en", "hi"]
    # Who visitors can contact about their data (DPDP): an email or phone, shown in the
    # privacy notice and on the privacy page.
    privacy_contact: str | None = Field(None, max_length=200)


class Branding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logo_key: str | None = None
    primary_color: str = "#0F4C5C"
    accent_color: str = "#E36414"

    @field_validator("primary_color", "accent_color")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not HEX.match(v):
            raise ValueError("Use a hex colour like #0F4C5C")
        return v.upper()


class OrgOut(Timestamps):
    name: str
    slug: str
    status: str
    data_region: str
    default_locale: str
    timezone: str
    branding: Branding
    settings: OrgSettings
    logo_url: str | None = None


class OrgUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    default_locale: Locale | None = None
    settings: OrgSettings | None = None
    branding: Branding | None = None


class SignupIn(BaseModel):
    org_name: Name
    admin_name: Name
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    phone: Phone | None = None


class PlatformOrgCreate(BaseModel):
    name: Name
    admin_name: Name
    admin_email: EmailStr
    admin_password: str = Field(min_length=10, max_length=128)
    status: Literal["active", "trial"] = "trial"
    data_region: str = "ap-south-1"


class PlatformOrgUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    data_region: str | None = None


class PlatformOrgOut(OrgOut):
    user_count: int = 0
    site_count: int = 0


class PlatformStats(BaseModel):
    orgs: int
    active_orgs: int
    users: int
    sites: int


class OrgRef(BaseModel):
    id: UUID
    name: str
    slug: str
