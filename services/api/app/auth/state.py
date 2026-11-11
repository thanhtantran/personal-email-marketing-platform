"""Short-lived signed OAuth state, stored in a hardened cookie.

Carries the CSRF ``state``, the OIDC ``nonce`` and the PKCE ``code_verifier``
between the start and callback requests. Signed with ``SESSION_KEY`` so a
tampered cookie is rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.config import Settings
from app.errors import AuthenticationError

_ALGORITHM = "HS256"


@dataclass(frozen=True)
class OAuthState:
    state: str
    nonce: str
    code_verifier: str


def encode_state(settings: Settings, state: OAuthState) -> str:
    now = datetime.now(UTC)
    payload = {
        "state": state.state,
        "nonce": state.nonce,
        "code_verifier": state.code_verifier,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.oauth_state_ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.session_key, algorithm=_ALGORITHM)


def decode_state(settings: Settings, token: str) -> OAuthState:
    try:
        claims = jwt.decode(token, settings.session_key, algorithms=[_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid or expired OAuth state") from exc
    return OAuthState(
        state=str(claims["state"]),
        nonce=str(claims["nonce"]),
        code_verifier=str(claims["code_verifier"]),
    )
