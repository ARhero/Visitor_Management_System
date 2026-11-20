from datetime import date, datetime, time
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.common import Name, Phone, ShortText

Kind = Literal["single", "multi_day", "group"]


class GuestIn(BaseModel):
    name: Name
    phone: Phone
    company: ShortText | None = None


class InviteIn(BaseModel):
    """Dates and times are IST wall-clock. single / group: one day, ``start_time`` to
    ``end_time``. multi_day: every day from ``date`` to ``end_date``, between the times."""

    model_config = ConfigDict(extra="forbid")

    site_id: UUID
    host_id: UUID | None = None  # admins only; hosts always invite as themselves
    purpose_id: UUID | None = None
    kind: Kind = "single"
    title: ShortText | None = None
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    date: date
    end_date: date | None = None
    start_time: time = time(9, 0)
    end_time: time = time(18, 0)
    guests: list[GuestIn] = Field(min_length=1, max_length=200)
    send: bool = True  # WhatsApp the passes now

    @model_validator(mode="after")
    def _check(self) -> "InviteIn":
        if self.end_time <= self.start_time:
            raise ValueError("End time must be after start time")
        if self.kind == "multi_day":
            if not self.end_date or self.end_date < self.date:
                raise ValueError("Choose an end date on or after the start date")
            if (self.end_date - self.date).days > 90:
                raise ValueError("A multi-day invite can cover at most 90 days")
        else:
            self.end_date = None
        if self.kind == "single" and len(self.guests) != 1:
            raise ValueError("A single invite has exactly one guest")
        return self


class InviteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: ShortText | None = None
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class GuestsIn(BaseModel):
    guests: list[GuestIn] = Field(min_length=1, max_length=200)
    send: bool = True


class GuestOut(BaseModel):
    id: UUID
    name: str
    phone: str
    company: str | None
    status: str
    use_count: int
    max_uses: int | None
    last_used_at: datetime | None
    sent_at: datetime | None
    consented_at: datetime | None
    pass_url: str | None  # for copying / sharing by other means
    share_text: str | None = None  # the invitation, ready to send from your own WhatsApp


class InviteOut(BaseModel):
    id: UUID
    site_id: UUID
    site_name: str
    host_id: UUID
    host_name: str
    purpose_id: UUID | None
    kind: Kind
    title: str | None
    notes: str | None
    valid_from: datetime
    valid_until: datetime
    daily_start_time: time | None
    daily_end_time: time | None
    status: str
    created_via: str
    created_at: datetime
    guest_count: int
    arrived_count: int
    guests: list[GuestOut] | None = None  # only on the detail view


class GuestImportResult(BaseModel):
    added: int
    skipped: int
    errors: list[dict]


class BlacklistIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: Phone
    name: ShortText | None = None
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
    action: Literal["block", "alert"] = "block"
    site_id: UUID | None = None
    expires_at: datetime | None = None


class BlacklistUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ShortText | None = None
    reason: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
        | None
    ) = None
    action: Literal["block", "alert"] | None = None
    site_id: UUID | None = None
    expires_at: datetime | None = None
    is_active: bool | None = None


class BlacklistOut(BaseModel):
    id: UUID
    phone: str
    name: str | None
    reason: str
    action: str
    site_id: UUID | None
    site_name: str | None
    expires_at: datetime | None
    is_active: bool
    added_by_name: str | None
    created_at: datetime
    hits: int  # attempts on record
