"""Request-scoped authentication dependencies.

Tenant context is resolved server-side from the session cookie and the user's
active membership. It is never read from request bodies or headers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import AuthService
from app.config import Settings, get_settings
from app.db.models import AuthSession, Membership, Tenant, User
from app.db.session import get_db
from app.errors import AuthenticationError, ForbiddenError
from app.repositories.membership_repo import MembershipRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.tenant_repo import TenantRepository
from app.repositories.user_repo import UserRepository
from app.security.tokens import constant_time_equals, generate_token, hash_token

#: Set on ``request.state`` when the dev auto-login shortcut issued a session
#: during this request, so the freshly queued cookies count as present.
DEV_AUTO_LOGIN_STATE = "dev_auto_login"


@dataclass(frozen=True)
class TenantContext:
    tenant: Tenant
    user: User
    membership: Membership
    session: AuthSession


def set_session_cookies(response: Response, settings: Settings, token: str, max_age: int) -> str:
    """Issue the session cookie and a fresh double-submit CSRF cookie.

    Returns the CSRF token so callers can reflect it, e.g. the dev shortcut.
    """
    csrf_token = generate_token(16)
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    return csrf_token


def clear_session_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


def csrf_cookie_present(request: Request, settings: Settings) -> bool:
    """Whether the request carries the CSRF cookie or was just issued one."""
    return settings.csrf_cookie_name in request.cookies or bool(
        getattr(request.state, DEV_AUTO_LOGIN_STATE, False)
    )


async def _resolve_context(
    request: Request, db: AsyncSession, settings: Settings
) -> TenantContext | None:
    """Resolve the context for the session cookie, or ``None`` if unusable.

    ``None`` means there is no session to trust (missing cookie, unknown or
    expired token, or a session pointing at deleted state). An inactive
    workspace behind a live session raises instead, so it can never fall back.
    """
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None

    record = await SessionRepository(db).get_active_by_hash(hash_token(token))
    if record is None:
        return None

    user = await UserRepository(db).get_by_id(record.user_id)
    membership = await MembershipRepository(db).get(record.tenant_id, record.user_id)
    tenant = await TenantRepository(db).get_by_id(record.tenant_id)

    if user is None or tenant is None or membership is None:
        return None
    if user.status != "active" or membership.status != "active" or tenant.status != "active":
        raise ForbiddenError("Workspace or user is not active")

    return TenantContext(tenant=tenant, user=user, membership=membership, session=record)


async def get_current_context(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TenantContext:
    context = await _resolve_context(request, db, settings)
    if context is not None:
        return context

    # Phase 1 local convenience: sign the workspace owner in without Google.
    # Only reachable when DEV_AUTO_LOGIN is on and the app is not production.
    if settings.dev_auto_login_enabled:
        issued = await AuthService(db, settings).dev_owner_login()
        max_age = int((issued.expires_at - datetime.now(UTC)).total_seconds())
        set_session_cookies(response, settings, issued.token, max_age)
        request.state.dev_auto_login = True
        return TenantContext(
            tenant=issued.tenant,
            user=issued.user,
            membership=issued.membership,
            session=issued.session,
        )

    raise AuthenticationError("No active session")


async def verify_csrf(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """Double-submit CSRF check for cookie-authenticated mutations."""
    cookie = request.cookies.get(settings.csrf_cookie_name)
    header = request.headers.get(settings.csrf_header_name)
    if not cookie or not header or not constant_time_equals(cookie, header):
        raise ForbiddenError("CSRF token missing or invalid")
