"""Model registry.

Importing this package registers every model against ``Base.metadata`` so that
Alembic autogenerate and migrations see the full schema.
"""

from __future__ import annotations

from app.db.models.audit import AuditLog
from app.db.models.membership import Membership
from app.db.models.session import AuthSession
from app.db.models.tenant import Tenant
from app.db.models.user import User

__all__ = ["AuditLog", "AuthSession", "Membership", "Tenant", "User"]
