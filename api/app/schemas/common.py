from datetime import datetime
from typing import Annotated, Generic, TypeVar
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

from app.core.phone import normalize_phone

T = TypeVar("T")

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Phone = Annotated[str, AfterValidator(normalize_phone)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Timestamps(ORM):
    id: UUID
    created_at: datetime
    updated_at: datetime


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ReorderIn(BaseModel):
    ids: list[UUID]
