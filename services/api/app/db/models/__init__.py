"""Model registry.

Importing this package registers every model against ``Base.metadata`` so that
Alembic autogenerate and migrations see the full schema.
"""

from __future__ import annotations

from app.db.models.audit import AuditLog
from app.db.models.campaign import Campaign, CampaignRecipient, CampaignSnapshot
from app.db.models.contact import Contact, ContactTag, Suppression, Tag
from app.db.models.idempotency import IdempotencyKey
from app.db.models.import_job import ImportJob, ImportRow
from app.db.models.membership import Membership
from app.db.models.outbox import OutboxEvent
from app.db.models.segment import Segment
from app.db.models.session import AuthSession
from app.db.models.template import Template
from app.db.models.tenant import Tenant
from app.db.models.user import User

__all__ = [
    "AuditLog",
    "AuthSession",
    "Campaign",
    "CampaignRecipient",
    "CampaignSnapshot",
    "Contact",
    "ContactTag",
    "IdempotencyKey",
    "ImportJob",
    "ImportRow",
    "Membership",
    "OutboxEvent",
    "Segment",
    "Suppression",
    "Tag",
    "Template",
    "Tenant",
    "User",
]
