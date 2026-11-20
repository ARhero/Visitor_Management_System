from datetime import datetime, time
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

from app.core.i18n import Locale
from app.schemas.common import Phone
from app.schemas.visits import VisitIn

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]

ScanResult = Literal[
    "ok",  # approved: let them in
    "inside",  # already checked in: offer check-out
    "invalid",  # not a pass from this organization
    "expired",
    "not_yet",
    "outside_hours",
    "used",  # single-use pass already used, or visit over
    "left",  # multi-day guest already came and left today
    "revoked",  # rejected / cancelled / invite revoked
    "not_approved",  # host hasn't approved yet
    "wrong_site",
    "blocked",
]


class GuardSite(BaseModel):
    id: UUID
    name: str
    city: str | None
    gates: list[dict[str, str]]  # [{id, name}]


class Alert(BaseModel):
    action: Literal["block", "alert"]
    reason: str


class GuardCard(BaseModel):
    id: UUID
    status: str
    source: str
    visitor_name: str | None
    visitor_company: str | None
    phone_last4: str | None
    # False: typed in without a WhatsApp code; check the visitor's ID.
    phone_verified: bool = True
    photo_url: str | None
    host_name: str
    purpose: str | None
    purpose_i18n: dict[str, str] = {}
    purpose_note: str | None
    accompanying_count: int
    vehicle_number: str | None
    id_type: str | None
    id_last4: str | None
    gate_name: str | None
    requested_at: datetime
    approved_at: datetime | None
    checked_in_at: datetime | None
    checked_out_at: datetime | None
    checkout_method: str | None
    valid_until: datetime
    host_message: str | None
    guard_note: str | None
    escalated: bool
    invite_title: str | None = None
    invite_notes: str | None = None
    alert: Alert | None = None


class ExpectedGuest(BaseModel):
    guest_id: UUID
    invite_id: UUID
    name: str
    company: str | None
    phone_last4: str | None
    host_name: str
    kind: str
    title: str | None
    notes: str | None
    valid_from: datetime
    valid_until: datetime
    daily_start_time: time | None
    daily_end_time: time | None
    consented: bool


class GuardQueue(BaseModel):
    site_id: UUID
    awaiting: list[GuardCard]  # host hasn't answered
    expected: list[GuardCard]  # approved, not yet arrived
    on_site: list[GuardCard]
    left: list[GuardCard]  # checked out today
    alerts: list[GuardCard]  # blocked attempts today
    invites: list[ExpectedGuest]  # pre-approved guests due today, not arrived yet
    people_on_site: int  # visitors + people with them


class ScanIn(BaseModel):
    site_id: UUID
    payload: str = Field(min_length=10, max_length=2000)


class ScanOut(BaseModel):
    result: ScanResult
    message: str
    visit: GuardCard | None = None
    guest: ExpectedGuest | None = None
    site_name: str | None = None  # for wrong_site: where the pass is for


class OfflineEntry(BaseModel):
    """One expected pass, for checking it with no connection. ``h`` = SHA-256 of the
    pass's jti (the device hashes the jti of a scanned, signature-checked pass)."""

    h: str
    kind: Literal["visit", "invite"]
    ref_id: UUID  # visit id, or invite guest id
    name: str
    company: str | None
    host_name: str
    purpose: str | None
    state: str  # approved | checked_in | invite
    accompanying_count: int
    valid_from: datetime | None = None
    valid_until: datetime
    daily_start_time: time | None = None
    daily_end_time: time | None = None
    consented: bool = True
    photo_url: str | None = None
    alert: Alert | None = None


class OfflinePack(BaseModel):
    site_id: UUID
    generated_at: datetime
    use_until: datetime  # the device drops the pack after this (end of the IST day)
    key: dict[str, str]  # JWK of the Ed25519 public key that signs passes
    entries: list[OfflineEntry]


class PassCheckInIn(BaseModel):
    site_id: UUID
    payload: str = Field(min_length=10, max_length=2000)
    occurred_at: datetime | None = None


class CheckInIn(BaseModel):
    # When the guard actually tapped (actions replayed from the offline queue).
    occurred_at: datetime | None = None
    # Let someone in without the host's answer (pending / waiting visits only).
    override_reason: Reason | None = None


class CheckOutIn(BaseModel):
    occurred_at: datetime | None = None


class GuardOtpIn(BaseModel):
    site_id: UUID
    phone: Phone
    locale: Locale = "en"


class WalkInIn(VisitIn):
    """A guard checks someone in at the desk. Same details as self check-in; the
    guard confirms the visitor was shown the privacy notice."""

    site_id: UUID
    gate_id: UUID | None = None
    phone: Phone
    otp_code: Annotated[str, StringConstraints(pattern=r"^\d{6}$")] | None = None
    # Let them in now instead of waiting for the host (needs a reason, audited).
    admit: bool = False
    override_reason: Reason | None = None


class GuardForm(BaseModel):
    require_selfie: bool
    id_proof_mode: str
    otp_required: bool
    purposes: list[dict]
    fields: list[dict]
    notices: dict[str, dict]
