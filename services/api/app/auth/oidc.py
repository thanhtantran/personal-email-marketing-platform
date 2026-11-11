"""Google OIDC client (Authorization Code + PKCE).

Validation follows SPEC.md section 8: state, nonce, PKCE, issuer, audience,
signature and expiry are all checked before any user is created.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass

import anyio
import httpx
import jwt
from jwt import PyJWKClient

from app.config import Settings
from app.errors import AuthenticationError
from app.security.tokens import constant_time_equals

STATE_TTL_DEFAULT = 600


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    email_verified: bool
    name: str | None


@dataclass(frozen=True)
class AuthRequest:
    url: str
    state: str
    nonce: str
    code_verifier: str


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class GoogleOIDCClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._jwks_client: PyJWKClient | None = None

    def _get_jwks_client(self) -> PyJWKClient:
        if self._jwks_client is None:
            self._jwks_client = PyJWKClient(self.settings.google_jwks_uri)
        return self._jwks_client

    def build_auth_request(self) -> AuthRequest:
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier, challenge = _pkce_pair()
        params = {
            "client_id": self.settings.oauth_google_client_id,
            "redirect_uri": self.settings.oauth_google_redirect_uri,
            "response_type": "code",
            "scope": self.settings.google_scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "online",
            "prompt": "select_account",
        }
        url = str(httpx.URL(self.settings.google_auth_endpoint, params=params))
        return AuthRequest(url=url, state=state, nonce=nonce, code_verifier=verifier)

    async def exchange_code(self, code: str, code_verifier: str) -> dict:
        data = {
            "client_id": self.settings.oauth_google_client_id,
            "client_secret": self.settings.oauth_google_client_secret,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": self.settings.oauth_google_redirect_uri,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(self.settings.google_token_endpoint, data=data)
        if response.status_code != 200:
            raise AuthenticationError("Google token exchange failed")
        payload = response.json()
        if "id_token" not in payload:
            raise AuthenticationError("Google response did not include an id_token")
        return payload

    async def verify_id_token(self, id_token: str, expected_nonce: str) -> GoogleIdentity:
        jwks_client = self._get_jwks_client()
        try:
            signing_key = await anyio.to_thread.run_sync(
                jwks_client.get_signing_key_from_jwt, id_token
            )
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.settings.oauth_google_client_id,
                issuer=["https://accounts.google.com", "accounts.google.com"],
                options={"require": ["exp", "iat", "sub", "aud", "iss", "nonce"]},
            )
        except jwt.PyJWTError as exc:  # signature/issuer/audience/expiry failures
            raise AuthenticationError("Invalid Google id_token") from exc

        nonce = claims.get("nonce", "")
        if not isinstance(nonce, str) or not constant_time_equals(nonce, expected_nonce):
            raise AuthenticationError("Google id_token nonce mismatch")

        return GoogleIdentity(
            subject=str(claims["sub"]),
            email=str(claims.get("email", "")),
            email_verified=bool(claims.get("email_verified", False)),
            name=claims.get("name"),
        )
