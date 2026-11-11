"""Owner allowlist must fail closed (Stage 1 exit gate).

The allowlist check runs before any database access, so it is exercised
directly without a live PostgreSQL instance.
"""

from __future__ import annotations

import pytest

from app.auth.oidc import GoogleIdentity
from app.auth.service import AuthService
from app.config import Settings
from app.errors import ForbiddenError


def _identity(
    subject: str = "sub-1",
    email: str = "owner@example.com",
    verified: bool = True,
) -> GoogleIdentity:
    return GoogleIdentity(subject=subject, email=email, email_verified=verified, name="Owner")


def _service(**overrides: object) -> AuthService:
    # The session is unused by the allowlist check.
    return AuthService(None, Settings(**overrides))  # type: ignore[arg-type]


def test_matching_subject_is_allowed() -> None:
    service = _service(owner_google_sub="sub-1")
    service._authorize_owner(_identity(subject="sub-1"))  # no raise


def test_non_owner_subject_is_rejected() -> None:
    service = _service(owner_google_sub="sub-owner")
    with pytest.raises(ForbiddenError):
        service._authorize_owner(_identity(subject="sub-intruder"))


def test_owner_by_email_requires_verified_email() -> None:
    service = _service(owner_email="Owner@Example.com")
    service._authorize_owner(_identity(email="owner@example.com", verified=True))
    with pytest.raises(ForbiddenError):
        service._authorize_owner(_identity(email="owner@example.com", verified=False))


def test_owner_subject_takes_precedence_over_email() -> None:
    service = _service(owner_google_sub="sub-owner", owner_email="other@example.com")
    service._authorize_owner(_identity(subject="sub-owner", email="anyone@example.com"))
    with pytest.raises(ForbiddenError):
        service._authorize_owner(_identity(subject="sub-other", email="other@example.com"))


def test_unconfigured_owner_claims_first_identity_in_development() -> None:
    service = _service(app_env="development", owner_google_sub="", owner_email="")
    service._authorize_owner(_identity())  # no raise


def test_unconfigured_owner_fails_closed_in_production() -> None:
    service = _service(app_env="production", owner_google_sub="", owner_email="")
    with pytest.raises(ForbiddenError):
        service._authorize_owner(_identity())
