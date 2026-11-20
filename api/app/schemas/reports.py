from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Status = Literal[
    "pending",
    "waiting",
    "approved",
    "rejected",
    "checked_in",
    "checked_out",
    "expired",
    "cancelled",
]
Source = Literal["qr_self", "guard_manual", "invite"]
MAX_DAYS = 366


class VisitFilters(BaseModel):
    """Visit log / export filters. Dates are IST calendar days, both inclusive."""

    model_config = ConfigDict(extra="forbid")

    from_date: date | None = None
    to_date: date | None = None
    site_id: UUID | None = None
    gate_id: UUID | None = None
    host_id: UUID | None = None
    department_id: UUID | None = None
    purpose_id: UUID | None = None
    status: list[Status] = Field(default_factory=list)
    source: Source | None = None
    q: str | None = Field(None, max_length=100)

    @model_validator(mode="after")
    def _range(self) -> "VisitFilters":
        if self.from_date and self.to_date:
            if self.to_date < self.from_date:
                raise ValueError("'to' must be on or after 'from'")
            if (self.to_date - self.from_date).days >= MAX_DAYS:
                raise ValueError(f"Choose at most {MAX_DAYS} days")
        return self


class VisitRow(BaseModel):
    id: UUID
    status: str
    source: str
    visitor_name: str | None
    visitor_company: str | None
    visitor_phone: str | None
    host_id: UUID
    host_name: str
    department: str | None
    site_id: UUID
    site_name: str
    gate_name: str | None
    purpose: str | None
    purpose_note: str | None
    accompanying_count: int
    vehicle_number: str | None
    requested_at: datetime
    responded_at: datetime | None
    response_channel: str | None
    checked_in_at: datetime | None
    checked_out_at: datetime | None
    checkout_method: str | None
    wait_seconds: int | None  # request → host's answer
    guard_note: str | None
    flagged: bool  # blacklist hit
    anonymized: bool


class VisitPage(BaseModel):
    items: list[VisitRow]
    next_cursor: str | None
    total: int | None  # only on the first page


class TimelineEvent(BaseModel):
    at: datetime
    from_status: str | None
    to_status: str
    actor_type: str
    actor_name: str | None
    channel: str
    meta: dict[str, Any]


class VisitDetail(VisitRow):
    photo_url: str | None
    id_type: str | None
    id_last4: str | None
    custom_values: dict[str, Any]
    host_message: str | None
    invite_title: str | None
    alert_reason: str | None
    consent: dict[str, Any] | None  # {version, locale, at}
    timeline: list[TimelineEvent]
    messages: list[dict[str, Any]]  # WhatsApp messages about this visit


# ---------- Reports ----------


class RangeIn(BaseModel):
    from_date: date
    to_date: date
    site_id: UUID | None = None


class Point(BaseModel):
    day: date
    requests: int
    checked_in: int
    rejected: int
    expired: int


class Traffic(BaseModel):
    days: list[Point]
    totals: dict[str, int]
    by_source: dict[str, int]
    by_purpose: list[dict[str, Any]]


class PeakHours(BaseModel):
    # grid[weekday 0=Mon][hour 0..23] = check-ins (IST)
    grid: list[list[int]]
    busiest: dict[str, Any] | None


class TopHost(BaseModel):
    host_id: UUID
    host_name: str
    department: str | None
    visits: int
    approved: int
    median_wait_seconds: int | None


class DepartmentRow(BaseModel):
    department: str
    visits: int
    hosts: int


class ApprovalTimes(BaseModel):
    answered: int
    unanswered: int  # expired without an answer
    median_seconds: int | None
    p90_seconds: int | None
    buckets: list[dict[str, Any]]  # [{label, max_seconds, count}]
    by_channel: dict[str, int]
    escalated: int
    overrides: int  # let in by a guard without the host


class Live(BaseModel):
    at: datetime
    on_site: int  # visits checked in
    people_on_site: int  # incl. people with them
    waiting_for_host: int
    approved_not_arrived: int
    today: dict[str, int]  # requests, checked_in, checked_out, rejected, expired, blocked
    median_wait_seconds_today: int | None
    by_gate: list[dict[str, Any]]  # check-ins per gate today
    by_hour: list[int]  # check-ins per IST hour today
    by_site: list[dict[str, Any]]  # on site per site
    recent: list[dict[str, Any]]  # latest status changes


class EvacuationRow(BaseModel):
    visit_id: UUID
    visitor_name: str | None
    visitor_company: str | None
    visitor_phone: str | None
    photo_url: str | None
    host_name: str
    host_phone: str | None
    site_name: str
    gate_name: str | None
    accompanying_count: int
    checked_in_at: datetime | None


class Evacuation(BaseModel):
    at: datetime
    site_id: UUID | None
    site_name: str | None
    visits: int
    people: int
    rows: list[EvacuationRow]
    contacts: list[dict[str, str]]


class ExportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["visits_csv", "visits_xlsx", "visits_pdf", "report_pdf"]
    filters: VisitFilters = Field(default_factory=VisitFilters)


class ExportOut(BaseModel):
    id: UUID
    kind: str
    status: str
    file_name: str | None
    row_count: int | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    expires_at: datetime | None
