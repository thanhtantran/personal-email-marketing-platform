"""OAuth and session endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_context, verify_csrf
from app.auth.oidc import GoogleOIDCClient
from app.auth.service import AuthService
from app.auth.state import OAuthState, decode_state, encode_state
from app.config import Settings, get_settings
from app.db.session import get_db
from app.errors import AppError
from app.logging import get_logger
from app.redis_client import get_redis
from app.repositories.audit_repo import AuditRepository
from app.repositories.session_repo import SessionRepository
from app.security.rate_limit import enforce_rate_limit
from app.security.tokens import generate_token

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)

OAUTH_STATE_COOKIE = "oauth_state"


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _set_session_cookies(response: Response, settings: Settings, token: str, max_age: int) -> None:
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
        generate_token(16),
        max_age=max_age,
        httponly=False,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def _clear_session_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


@router.get("/google/start")
async def google_start(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    await enforce_rate_limit(
        get_redis(),
        key=f"auth:start:{_client_ip(request)}",
        limit=settings.rate_limit_auth_per_minute,
    )
    client = GoogleOIDCClient(settings)
    auth_request = client.build_auth_request()
    response = RedirectResponse(auth_request.url, status_code=302)
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        encode_state(
            settings,
            OAuthState(
                state=auth_request.state,
                nonce=auth_request.nonce,
                code_verifier=auth_request.code_verifier,
            ),
        ),
        max_age=settings.oauth_state_ttl_seconds,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    await enforce_rate_limit(
        get_redis(),
        key=f"auth:callback:{_client_ip(request)}",
        limit=settings.rate_limit_auth_per_minute,
    )

    def failure(reason: str) -> RedirectResponse:
        target = f"{settings.app_base_url}/?auth_error={reason}"
        response = RedirectResponse(target, status_code=302)
        response.delete_cookie(OAUTH_STATE_COOKIE, path="/")
        return response

    if error or not code or not state:
        return failure("oauth_denied")

    raw_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not raw_state:
        return failure("missing_state_cookie")

    try:
        expected = decode_state(settings, raw_state)
        if expected.state != state:
            return failure("state_mismatch")

        client = GoogleOIDCClient(settings)
        token_response = await client.exchange_code(code, expected.code_verifier)
        identity = await client.verify_id_token(token_response["id_token"], expected.nonce)

        issued = await AuthService(db, settings).complete_login(identity)
    except AppError as exc:
        logger.warning("oauth callback rejected", extra={"reason": exc.code})
        return failure(exc.code)

    max_age = int((issued.expires_at - datetime.now(UTC)).total_seconds())
    response = RedirectResponse(settings.app_base_url, status_code=302)
    _set_session_cookies(response, settings, issued.token, max_age)
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    return response


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    context=Depends(get_current_context),
    _: None = Depends(verify_csrf),
) -> Response:
    sessions = SessionRepository(db)
    await sessions.revoke(context.session)
    audit = AuditRepository(db, context.tenant.id)
    await audit.record(
        action="auth.logout",
        actor_user_id=context.user.id,
        object_type="session",
        object_id=str(context.session.id),
    )
    await db.commit()

    response = Response(status_code=204)
    _clear_session_cookies(response, settings)
    return response
