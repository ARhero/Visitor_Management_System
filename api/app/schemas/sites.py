from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.schemas.common import ORM, Name, Phone, ShortText, Timestamps


class SafetyContact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    phone: Phone


class SiteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    address: str | None = Field(None, max_length=1000)
    city: ShortText | None = None
    state: ShortText | None = None
    pincode: str | None = Field(None, pattern=r"^\d{6}$")
    lat: Decimal | None = Field(None, ge=-90, le=90)
    lng: Decimal | None = Field(None, ge=-180, le=180)
    map_url: HttpUrl | None = None
    directions_text: str | None = Field(None, max_length=2000)
    safety_contacts: list[SafetyContact] = Field(default_factory=list, max_length=10)
    is_active: bool = True


class SiteCreate(SiteIn):
    default_gate_name: str | None = Field("Main Gate", max_length=100)


class SiteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    address: str | None = Field(None, max_length=1000)
    city: ShortText | None = None
    state: ShortText | None = None
    pincode: str | None = Field(None, pattern=r"^\d{6}$")
    lat: Decimal | None = Field(None, ge=-90, le=90)
    lng: Decimal | None = Field(None, ge=-180, le=180)
    map_url: HttpUrl | None = None
    directions_text: str | None = Field(None, max_length=2000)
    safety_contacts: list[SafetyContact] | None = Field(None, max_length=10)
    is_active: bool | None = None


class GateOut(Timestamps):
    site_id: UUID
    name: str
    qr_token: str
    qr_rotated_at: datetime | None
    is_active: bool
    checkin_url: str = ""


class SiteOut(Timestamps):
    name: str
    address: str | None
    city: str | None
    state: str | None
    pincode: str | None
    lat: Decimal | None
    lng: Decimal | None
    map_url: str | None
    directions_text: str | None
    timezone: str
    settings_override: dict[str, Any]
    safety_contacts: list[dict[str, str]] = []
    is_active: bool
    gates: list[GateOut] = []


class GateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    is_active: bool = True


class GateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    is_active: bool | None = None


class DepartmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name


class DepartmentOut(Timestamps):
    name: str
    user_count: int = 0


class GuardSitesIn(BaseModel):
    site_ids: list[UUID]


class IdOnly(ORM):
    id: UUID
