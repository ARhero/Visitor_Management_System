from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.i18n import Locale
from app.schemas.common import Phone


class EraseIn(BaseModel):
    phone: Phone
    confirm_phone: Phone  # typed again, so nobody erases the wrong person by accident
    note: str | None = Field(None, max_length=500)


class ResolveIn(BaseModel):
    note: str | None = Field(None, max_length=500)


class RejectIn(BaseModel):
    note: str = Field(min_length=3, max_length=500)


class EraseOut(BaseModel):
    visits: int
    visitors: int
    guests: int
    messages: int
    files: int


class PrivacyRequestOut(BaseModel):
    id: UUID
    kind: str
    phone: str | None
    phone_masked: str
    name: str | None
    reason: str | None
    status: str
    resolution_note: str | None
    resolved_at: datetime | None
    resolved_by_name: str | None
    created_at: datetime
    visits: int = 0  # identifiable visits still held for this phone
    active_visit: bool = False


class RetentionStatus(BaseModel):
    retention_days: int
    cutoff: datetime
    due: int
    anonymized_visits: int
    oldest_identifiable: datetime | None
    last_run: dict[str, Any] | None


class PrivacyOverview(BaseModel):
    retention: RetentionStatus
    open_requests: int
    privacy_url: str
    privacy_contact: str | None


class NoticeOut(BaseModel):
    id: UUID
    locale: str
    version: int
    body: str
    preview: str
    is_current: bool
    published_at: datetime
    acceptances: int


class NoticeIn(BaseModel):
    locale: Locale
    body: str = Field(min_length=80, max_length=4000)


# ---------- Public (visitor self-service) ----------


class PrivacyPage(BaseModel):
    org_name: str
    logo_url: str | None
    primary_color: str
    retention_days: int
    privacy_contact: str | None
    notices: dict[str, str]
    # False when WhatsApp is off: no code can be sent, so visitors ask the contact.
    self_serve: bool = True


class PrivacyOtpIn(BaseModel):
    phone: Phone
    locale: Locale = "en"


class PrivacyVerifyIn(BaseModel):
    phone: Phone
    code: str = Field(pattern=r"^\d{6}$")


class PrivacyToken(BaseModel):
    token: str
    expires_in: int


class ErasureRequestIn(BaseModel):
    reason: str | None = Field(None, max_length=500)
    locale: Locale = "en"


class MyData(BaseModel):
    data: dict[str, Any]
    open_request: PrivacyRequestOut | None
