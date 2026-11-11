"""Request-scoped authentication dependencies.

Tenant context is resolved server-side from the session cookie and the user's
active membership. It is never read from request bodies or headers.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import AuthSession, Membership, Tenant, User
from app.db.session import get_db
from app.errors import AuthenticationError, ForbiddenError
from app.repositories.membership_repo import MembershipRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.tenant_repo import TenantRepository
from app.repositories.user_repo import UserRepository
from app.security.tokens import constant_time_equals, hash_token


@dataclass(frozen=True)
class TenantContext:
    tenant: Tenant
    user: User
    membership: Membership
    session: AuthSession


async def get_current_context(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TenantContext:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise AuthenticationError("No active session")

    sessions = SessionRepository(db)
    record = await sessions.get_active_by_hash(hash_token(token))
    if record is None:
        raise AuthenticationError("Session is invalid or expired")

    user = await UserRepository(db).get_by_id(record.user_id)
    membership = await MembershipRepository(db).get(record.tenant_id, record.user_id)
    tenant = await TenantRepository(db).get_by_id(record.tenant_id)

    if user is None or tenant is None or membership is None:
        raise AuthenticationError("Session references missing workspace state")
    if user.status != "active" or membership.status != "active" or tenant.status != "active":
        raise ForbiddenError("Workspace or user is not active")

    return TenantContext(tenant=tenant, user=user, membership=membership, session=record)


async def verify_csrf(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """Double-submit CSRF check for cookie-authenticated mutations."""
    cookie = request.cookies.get(settings.csrf_cookie_name)
    header = request.headers.get(settings.csrf_header_name)
    if not cookie or not header or not constant_time_equals(cookie, header):
        raise ForbiddenError("CSRF token missing or invalid")
