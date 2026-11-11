"""Production configuration must fail closed on insecure or incomplete settings."""

from __future__ import annotations

from app.config import INSECURE_SESSION_KEY, Settings


def test_dev_config_has_no_fatal_problems() -> None:
    assert Settings(app_env="development").require_production_safety() == []


def test_production_rejects_default_insecure_config() -> None:
    problems = Settings(app_env="production").require_production_safety()
    joined = " ".join(problems)
    assert "SESSION_KEY" in joined
    assert "OAuth" in joined
    assert any("OWNER" in problem for problem in problems)
    assert any("ENCRYPTION_KEY_REF" in problem for problem in problems)
    assert any("APP_BASE_URL" in problem for problem in problems)


def test_production_detects_insecure_session_key_constant() -> None:
    settings = Settings(app_env="production", session_key=INSECURE_SESSION_KEY)
    assert any("SESSION_KEY" in problem for problem in settings.require_production_safety())


def test_production_accepts_hardened_config() -> None:
    settings = Settings(
        app_env="production",
        session_key="x" * 48,
        oauth_google_client_id="client-id",
        oauth_google_client_secret="client-secret",
        owner_google_sub="sub-owner",
        encryption_key_ref="kms://projects/p/locations/l/keyRings/r/cryptoKeys/k",
        app_base_url="https://mail.example.com",
    )
    assert settings.require_production_safety() == []


def test_secure_cookies_follow_base_url() -> None:
    assert Settings(app_base_url="https://mail.example.com").secure_cookies is True
    assert Settings(app_base_url="http://localhost:3000").secure_cookies is False
    assert (
        Settings(app_base_url="http://localhost:3000", session_cookie_secure=True).secure_cookies
        is True
    )
