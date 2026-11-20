from datetime import datetime, time
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.core.i18n import LOCALES, Locale
from app.schemas.common import Name, Phone, ShortText

Locale = Locale
IdType = Literal["aadhaar", "pan", "driving_licence", "voter_id", "passport", "company_id", "other"]
Action = Literal["approve", "reject", "wait"]


# ---------- Gate (public) ----------


class PublicPurpose(BaseModel):
    id: UUID
    label: str
    label_i18n: dict[str, str]
    requires_id_proof: bool


class PublicField(BaseModel):
    key: str
    label: str
    label_i18n: dict[str, str]
    help_i18n: dict[str, str]
    type: str
    options: list[Any]
    required: bool


class PublicNotice(BaseModel):
    id: UUID
    version: int
    body: str


class GateInfo(BaseModel):
    org_name: str
    branding: dict[str, Any]
    logo_url: str | None = None
    privacy_url: str | None = None
    locales: list[str]
    default_locale: str
    require_selfie: bool
    id_proof_mode: str
    site_name: str
    site_address: str | None
    gate_name: str
    # False: no WhatsApp code; the number is typed in and the guard checks ID instead.
    verify_phone: bool = True
    purposes: list[PublicPurpose]
    fields: list[PublicField]
    notices: dict[str, PublicNotice]  # by locale


# ---------- OTP ----------


class OtpSendIn(BaseModel):
    gate_token: str = Field(max_length=64)
    phone: Phone
    locale: Locale = "en"


class OtpSendOut(BaseModel):
    sent_to: str
    channel: str = "whatsapp"
    resend_after: int
    expires_in: int


class OtpVerifyIn(BaseModel):
    gate_token: str = Field(max_length=64)
    phone: Phone
    code: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{6}$")]


class VisitorPrefill(BaseModel):
    full_name: str | None
    company: str | None
    email: str | None
    has_photo: bool
    last_host: "HostOption | None" = None


class OtpVerifyOut(BaseModel):
    token: str
    expires_in: int
    returning: VisitorPrefill | None


class HostOption(BaseModel):
    id: UUID
    full_name: str
    department: str | None
    designation: str | None


class UploadOut(BaseModel):
    upload_token: str


# ---------- Submit ----------


class VisitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: Name
    company: ShortText | None = None
    email: EmailStr | None = None
    host_id: UUID
    purpose_id: UUID
    purpose_note: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None
    ) = None
    accompanying_count: int = Field(0, ge=0, le=20)
    vehicle_number: (
        Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, max_length=20)]
        | None
    ) = None
    custom_values: dict[str, Any] = Field(default_factory=dict)
    photo_upload: str | None = None
    use_previous_photo: bool = False
    id_type: IdType | None = None
    # Only the last 4 characters of any ID are ever accepted or stored.
    id_last4: (
        Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9A-Za-z]{4}$")] | None
    ) = None
    id_upload: str | None = None
    consent_notice_id: UUID
    consent: bool
    locale: Locale = "en"

    @field_validator("consent")
    @classmethod
    def _consent(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Consent is required to check in")
        return v

    @field_validator("vehicle_number")
    @classmethod
    def _vehicle(cls, v: str | None) -> str | None:
        return v.replace(" ", "") or None if v else None


class VisitCreated(BaseModel):
    visit_id: UUID
    status: str
    status_token: str


class PassInfo(BaseModel):
    token: str
    url: str


class VisitStatus(BaseModel):
    id: UUID
    status: str
    visitor_name: str | None
    host_name: str
    site_name: str
    gate_name: str | None
    host_message: str | None
    requested_at: datetime
    responded_at: datetime | None
    valid_until: datetime
    escalated: bool
    pass_: PassInfo | None = Field(None, serialization_alias="pass")
    # False: nothing reaches the visitor on WhatsApp; this page is where they see it.
    whatsapp: bool = True


# ---------- Host side ----------


class RespondIn(BaseModel):
    action: Action
    message: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None


class VisitForHost(BaseModel):
    id: UUID
    status: str
    visitor_name: str | None
    visitor_company: str | None
    visitor_phone: str | None
    photo_url: str | None
    purpose: str | None
    purpose_i18n: dict[str, str] = {}
    purpose_note: str | None
    accompanying_count: int
    vehicle_number: str | None
    custom_values: dict[str, Any]
    id_type: str | None
    id_last4: str | None
    site_name: str
    gate_name: str | None
    host_name: str
    requested_at: datetime
    responded_at: datetime | None
    host_message: str | None
    can_respond: bool
    source: str = "qr_self"
    checked_in_at: datetime | None = None
    checked_out_at: datetime | None = None


# ---------- Pass page ----------


class PassView(BaseModel):
    state: Literal["valid", "not_yet", "checked_in", "used", "expired", "revoked"]
    kind: Literal["visit", "invite"] = "visit"
    status: str
    org_name: str
    branding: dict[str, Any]
    visitor_name: str | None
    visitor_company: str | None
    photo_url: str | None
    host_name: str
    site_name: str
    site_address: str | None
    directions: str | None
    map_url: str | None
    accompanying_count: int
    valid_until: datetime
    qr_svg: str | None
    # Invites: the window, and the privacy notice the guest must accept before the QR
    # is shown (they never went through check-in).
    title: str | None = None
    valid_from: datetime | None = None
    daily_start_time: time | None = None
    daily_end_time: time | None = None
    needs_consent: bool = False
    notices: dict[str, PublicNotice] | None = None
    locales: list[str] = list(LOCALES)


class PassConsentIn(BaseModel):
    notice_id: UUID
    locale: Locale = "en"


VisitorPrefill.model_rebuild()
