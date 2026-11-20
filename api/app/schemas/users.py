from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.schemas.common import Name, Phone, ShortText, Timestamps

Role = Literal["org_admin", "guard", "host"]


class _UserFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: Name
    email: EmailStr | None = None
    phone: Phone | None = None
    roles: list[Role] = Field(default_factory=lambda: ["host"], min_length=1)
    department_id: UUID | None = None
    designation: ShortText | None = None
    employee_code: ShortText | None = None
    primary_site_id: UUID | None = None
    backup_host_id: UUID | None = None


class UserCreate(_UserFields):
    password: str | None = Field(None, min_length=10, max_length=128)

    @model_validator(mode="after")
    def _rules(self) -> "UserCreate":
        if "host" in self.roles and not self.phone:
            raise ValueError("Hosts need a mobile number (approvals arrive on WhatsApp)")
        if not self.email and not self.phone:
            raise ValueError("Give an email or a mobile number")
        if {"org_admin", "guard"} & set(self.roles) and not self.password:
            raise ValueError("Admins and guards need an initial password")
        self.roles = sorted(set(self.roles))  # type: ignore[assignment]
        return self


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: Name | None = None
    email: EmailStr | None = None
    phone: Phone | None = None
    roles: list[Role] | None = Field(None, min_length=1)
    department_id: UUID | None = None
    designation: ShortText | None = None
    employee_code: ShortText | None = None
    primary_site_id: UUID | None = None
    backup_host_id: UUID | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=10, max_length=128)


class UserOut(Timestamps):
    full_name: str
    email: str | None
    phone: str | None
    roles: list[str]
    department_id: UUID | None
    designation: str | None
    employee_code: str | None
    primary_site_id: UUID | None
    backup_host_id: UUID | None
    is_active: bool
    last_login_at: datetime | None
    has_password: bool = False
    site_ids: list[UUID] = []


class HostDirectoryEntry(BaseModel):
    """What non-admin staff may see about colleagues."""

    id: UUID
    full_name: str
    department: str | None
    designation: str | None


class ImportRowResult(BaseModel):
    row: int
    action: Literal["create", "update", "skip", "error"]
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    errors: list[str] = []


class ImportResult(BaseModel):
    dry_run: bool
    total: int
    created: int
    updated: int
    errors: int
    new_departments: list[str]
    rows: list[ImportRowResult]
