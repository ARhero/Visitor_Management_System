import re
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import Name, Timestamps

KEY = re.compile(r"^[a-z][a-z0-9_]{0,49}$")
LOCALES = {"en", "hi", "or", "ta", "kn", "te", "ml", "mr", "bn", "gu", "pa"}


def _check_i18n(v: dict[str, str]) -> dict[str, str]:
    bad = set(v) - LOCALES
    if bad:
        raise ValueError(f"Unknown locale(s): {', '.join(sorted(bad))}")
    return {k: s.strip()[:200] for k, s in v.items() if s and s.strip()}


I18n = Annotated[dict[str, str], AfterValidator(_check_i18n)]


class PurposeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Name
    label_i18n: I18n = {}
    requires_id_proof: bool = False
    is_active: bool = True


class PurposeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Name | None = None
    label_i18n: I18n | None = None
    requires_id_proof: bool | None = None
    is_active: bool | None = None

    @field_validator("label_i18n")
    @classmethod
    def _i18n(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        return None if v is None else _check_i18n(v)


class PurposeOut(Timestamps):
    label: str
    label_i18n: dict[str, str]
    requires_id_proof: bool
    sort_order: int
    is_active: bool


FieldType = Literal["text", "number", "select", "checkbox", "declaration"]


class CustomFieldIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: Name
    label_i18n: I18n = {}
    help_i18n: I18n = {}
    type: FieldType
    options: list[str] = Field(default_factory=list, max_length=50)
    required: bool = False
    applies_to: Literal["checkin", "invite", "both"] = "checkin"
    site_id: UUID | None = None
    is_active: bool = True

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        if not KEY.match(v):
            raise ValueError(
                "Use lowercase letters, digits and underscores, starting with a letter"
            )
        return v

    @model_validator(mode="after")
    def _opts(self) -> "CustomFieldIn":
        if self.type == "select" and len(self.options) < 2:
            raise ValueError("A dropdown needs at least two options")
        if self.type != "select":
            self.options = []
        if self.type == "declaration":
            self.required = True  # a declaration that can be skipped is not a declaration
        return self


class CustomFieldUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Name | None = None
    label_i18n: I18n | None = None
    help_i18n: I18n | None = None
    options: list[str] | None = Field(None, max_length=50)
    required: bool | None = None
    applies_to: Literal["checkin", "invite", "both"] | None = None
    is_active: bool | None = None


class CustomFieldOut(Timestamps):
    key: str
    label: str
    label_i18n: dict[str, str]
    help_i18n: dict[str, str]
    type: str
    options: list[Any]
    required: bool
    applies_to: str
    site_id: UUID | None
    sort_order: int
    is_active: bool


class AuditOut(Timestamps):
    actor_user_id: UUID | None
    actor_type: str
    action: str
    entity_type: str
    entity_id: UUID | None
    diff: dict[str, Any]
    ip: str | None
    actor_name: str | None = None
