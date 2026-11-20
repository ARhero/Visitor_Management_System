from app.models.audit import AuditLog
from app.models.base import TENANT_TABLES, Base
from app.models.config import CustomField, Purpose
from app.models.export import ExportJob
from app.models.invite import BlacklistEntry, Invite, InviteGuest
from app.models.notify import (
    NotificationLog,
    PushSubscription,
    WebhookEvent,
    WhatsAppContact,
)
from app.models.org import Organization, PlatformUser, RefreshToken
from app.models.privacy import PrivacyRequest
from app.models.site import Department, Gate, Site
from app.models.user import GuardSiteAssignment, User
from app.models.visit import ConsentNotice, ConsentRecord, Visit, VisitEvent, Visitor

# Every table with an org_id column gets an RLS policy.
TENANT_TABLES[:] = sorted(
    t.name for t in Base.metadata.sorted_tables if "org_id" in t.c and t.name != "refresh_tokens"
)

__all__ = [
    "AuditLog",
    "Base",
    "BlacklistEntry",
    "ConsentNotice",
    "ConsentRecord",
    "CustomField",
    "Department",
    "ExportJob",
    "PrivacyRequest",
    "Gate",
    "GuardSiteAssignment",
    "Invite",
    "InviteGuest",
    "NotificationLog",
    "Organization",
    "PlatformUser",
    "Purpose",
    "RefreshToken",
    "Site",
    "TENANT_TABLES",
    "User",
    "Visit",
    "VisitEvent",
    "Visitor",
    "WebhookEvent",
    "WhatsAppContact",
    "PushSubscription",
]
