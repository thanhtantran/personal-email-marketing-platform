"""Application settings and runtime validation.

Configuration is environment/secret based (see .env.example). Production
deployments must fail startup on missing secrets or insecure defaults.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SESSION_KEY = "dev-only-change-me-please-32-bytes-min"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ core
    app_env: str = "development"
    app_base_url: str = "http://localhost:3000"
    api_base_url: str = "http://localhost:8000"
    default_timezone: str = "Asia/Shanghai"
    log_level: str = "INFO"

    # -------------------------------------------------------- infrastructure
    database_url: str = "postgresql+asyncpg://email:email@localhost:5432/email_platform"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ---------------------------------------------------------- object store
    object_storage_endpoint: str = "http://localhost:9000"
    object_storage_access_key: str = "test"
    object_storage_secret_key: str = "test"
    object_storage_bucket: str = "email-platform"
    object_storage_region: str = "us-east-1"
    object_storage_use_tls: bool = False

    # --------------------------------------------- identity (owner-only P1)
    oauth_google_client_id: str = ""
    oauth_google_client_secret: str = ""
    oauth_google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    owner_google_sub: str = ""
    owner_email: str = ""

    google_issuer: str = "https://accounts.google.com"
    google_auth_endpoint: str = "https://accounts.google.com/o/oauth2/v2/auth"
    google_token_endpoint: str = "https://oauth2.googleapis.com/token"
    google_jwks_uri: str = "https://www.googleapis.com/oauth2/v3/certs"
    google_scopes: str = "openid email profile"

    # ------------------------------------------------------------ sessions
    session_cookie_name: str = "session"
    csrf_cookie_name: str = "csrf_token"
    csrf_header_name: str = "X-CSRF-Token"
    session_absolute_hours: int = 168
    session_idle_hours: int = 12
    oauth_state_ttl_seconds: int = 600
    session_cookie_secure: bool | None = None

    # ------------------------------------------------------- tenant bootstrap
    tenant_slug: str = "personal"
    tenant_name: str = "Personal Workspace"

    # ----------------------------------------------------------------- secrets
    session_key: str = INSECURE_SESSION_KEY
    encryption_key_ref: str = "file://./secrets/dev-encryption-key"
    encryption_key_version: int = 1

    # ---------------------------------------------------------------- sending
    provider_default: str = "resend"
    tracking_enabled: bool = False

    # ---------------------------------------------------------------- content
    # MJML CLI binary used for server-side template rendering (see Dockerfile.api).
    mjml_binary: str = "mjml"
    mjml_timeout_seconds: int = 20
    template_max_source_bytes: int = 512_000
    # Optional isolated origin for rendering previews in the browser.
    preview_origin: str = ""
    # Comma-separated recipients permitted for test sends (owner email is implicit).
    test_send_allowlist: str = ""

    # ------------------------------------------------------- provisional limits
    import_max_file_mb: int = 50
    import_max_rows: int = 200_000
    import_max_columns: int = 100
    import_max_field_length: int = 4096
    campaign_batch_size: int = 500
    send_request_timeout_seconds: int = 30
    send_max_attempts: int = 5
    rate_limit_auth_per_minute: int = 20

    # --------------------------------------------------------------- retention
    raw_webhook_retention_days: int = 14
    staged_upload_retention_days: int = 7
    import_row_retention_days: int = 90

    @field_validator("session_cookie_secure", mode="before")
    @classmethod
    def _blank_means_unset(cls, value: object) -> object:
        """Treat an empty/whitespace env value as "unset" (auto-derive)."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @property
    def secure_cookies(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.app_base_url.startswith("https")

    @property
    def owner_configured(self) -> bool:
        return bool(self.owner_google_sub or self.owner_email)

    @property
    def verified_test_recipients(self) -> set[str]:
        """Addresses allowed to receive a test send; the owner email is implicit."""
        recipients = {
            item.strip().lower() for item in self.test_send_allowlist.split(",") if item.strip()
        }
        if self.owner_email.strip():
            recipients.add(self.owner_email.strip().lower())
        return recipients

    def require_production_safety(self) -> list[str]:
        """Return a list of fatal configuration problems for production."""
        problems: list[str] = []
        if not self.is_production:
            return problems
        if self.session_key == INSECURE_SESSION_KEY or len(self.session_key) < 32:
            problems.append("SESSION_KEY must be set to a strong value (>= 32 bytes) in production")
        if not self.oauth_google_client_id or not self.oauth_google_client_secret:
            problems.append("Google OAuth client id/secret are required in production")
        if not self.owner_google_sub and not self.owner_email:
            problems.append("OWNER_GOOGLE_SUB (preferred) or OWNER_EMAIL must be configured")
        if self.encryption_key_ref.startswith("file://"):
            problems.append("ENCRYPTION_KEY_REF must reference an external KMS/secret manager")
        if not self.app_base_url.startswith("https"):
            problems.append("APP_BASE_URL must use https in production")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
