from uuid import UUID

from pydantic import BaseModel, Field

from app.core.i18n import Locale
from app.schemas.common import Phone
from app.schemas.org import OrgRef


class LoginIn(BaseModel):
    identifier: str = Field(min_length=3, max_length=254, description="Email or mobile number")
    password: str = Field(min_length=1, max_length=128)
    org_slug: str | None = Field(
        None, description="Only needed if the same login exists in more than one organization"
    )


class PlatformLoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MeOut(BaseModel):
    id: UUID
    scope: str
    full_name: str
    email: str | None
    phone: str | None
    roles: list[str]
    org: OrgRef | None
    site_ids: list[UUID]
    whatsapp_enabled: bool = True  # False: share links yourself, alerts by web push


class MagicLinkIn(BaseModel):
    phone: Phone
    locale: Locale = "en"


class MagicExchangeIn(BaseModel):
    token: str = Field(min_length=20, max_length=1000)
