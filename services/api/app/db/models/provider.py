from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

#: Message classes a provider account can be explicitly eligible for. They are
#: stored separately because an account may be transactional-only; marketing
#: traffic must never be inferred from transactional eligibility (SPEC.md
#: invariants 4 and 9).
MESSAGE_CLASS_MARKETING = "marketing"
MESSAGE_CLASS_TRANSACTIONAL = "transactional"
MESSAGE_CLASSES = frozenset({MESSAGE_CLASS_MARKETING, MESSAGE_CLASS_TRANSACTIONAL})

#: Account lifecycle. ``disabled`` is an operator switch that outranks health;
#: ``paused`` stops new marketing reservations without touching credentials.
ACCOUNT_STATUS_ACTIVE = "active"
ACCOUNT_STATUS_PAUSED = "paused"
ACCOUNT_STATUS_DISABLED = "disabled"

#: Health is tracked separately from operator status so a circuit breaker can
#: hold routing without an operator having to disable the account.
HEALTH_HEALTHY = "healthy"
HEALTH_DEGRADED = "degraded"
HEALTH_UNHEALTHY = "unhealthy"

CREDENTIAL_STATUS_ACTIVE = "active"
CREDENTIAL_STATUS_REVOKED = "revoked"

#: ``pending`` is written before the network call; the terminal states mirror
#: ``SubmitResult`` (SPEC.md section 6) plus ``unknown`` for an ambiguous
#: post-send outcome that must be reconciled before any retry.
ATTEMPT_PENDING = "pending"
ATTEMPT_ACCEPTED = "accepted"
ATTEMPT_TRANSIENT = "definitive_transient_rejection"
ATTEMPT_PERMANENT = "definitive_permanent_rejection"
ATTEMPT_UNKNOWN = "unknown"


class ProviderAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The provider-side account and quota boundary.

    This row -- never a credential -- is the unit of quota, rate and routing
    (SPEC.md invariant 3). ``eligible_message_classes`` records the explicitly
    verified message classes, and ``eligibility_verified_at`` /
    ``quota_refreshed_at`` make staleness observable so routing can exclude an
    account whose facts may no longer hold (SPEC.md invariant 9).

    ``quota_state`` and ``limits`` are external, dated facts supplied through
    the operator refresh path; the application never hard-codes or infers them.
    """

    __tablename__ = "provider_accounts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider",
            "external_account_ref",
            name="uq_provider_accounts_external_ref",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_provider_accounts_tenant_id"),
        #: Public, unguessable handle used by the webhook route. It is not the
        #: account id, so leaking a webhook URL never discloses an internal key
        #: (SPEC.md section 8).
        UniqueConstraint("webhook_public_id", name="uq_provider_accounts_webhook_public_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    external_account_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=ACCOUNT_STATUS_ACTIVE)
    eligible_message_classes: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, default=list
    )
    sender_domains: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    quota_state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    limits: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    eligibility_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    quota_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    health_state: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    webhook_public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    #: Encrypted webhook signing secret (same envelope as a credential). It is
    #: write-only and never returned by an API, so verification is the only read.
    webhook_secret_ciphertext: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    webhook_secret_key_version: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ProviderCredential(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """An encrypted secret used to access one provider account.

    Several credentials may exist for a single account (rotation), but credentials
    never multiply quota: capacity is reserved on ``ProviderAccount``. The stored
    value is an AES-256-GCM envelope; ``key_version`` selects the key used at
    write time. The plaintext and the ciphertext are never returned by an API
    (docs/decisions/0004-secret-encryption.md).
    """

    __tablename__ = "provider_credentials"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_provider_credentials_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "provider_account_id"],
            ["provider_accounts.tenant_id", "provider_accounts.id"],
            name="fk_provider_credentials_account",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    provider_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    secret_ciphertext: Mapped[str] = mapped_column(String(4096), nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    label: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CREDENTIAL_STATUS_ACTIVE
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SendAttempt(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One provider submission attempt, persisted before the network call.

    The row exists (``state=pending``) before the request leaves the process, so
    a crash cannot lose the fact that a request may have reached the provider.
    ``UNIQUE(recipient_id, attempt_no)`` makes a retried worker converge on the
    same attempt instead of inserting a second one, and
    ``idempotency_key`` is stable per recipient so the provider can deduplicate.
    """

    __tablename__ = "send_attempts"
    __table_args__ = (
        UniqueConstraint("recipient_id", "attempt_no", name="uq_send_attempts_recipient_no"),
        UniqueConstraint("tenant_id", "id", name="uq_send_attempts_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "recipient_id"],
            ["campaign_recipients.tenant_id", "campaign_recipients.id"],
            name="fk_send_attempts_recipient",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default=ATTEMPT_PENDING)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Coarse failure reason (for example ``rate_limit``, ``quota_daily``,
    #: ``auth``, ``policy``, ``validation`` or ``server_error``) used to decide
    #: retryability without storing provider prose.
    error_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Populated only for an ambiguous result, so an operator can see whether the
    #: request still needs reconciliation before any retry is allowed.
    unknown_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ProviderRoutingControl(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tenant-level routing switches (global marketing pause).

    Global pause is durable operator state, not a cache entry: it must survive a
    restart and be visible to the owner, so it lives in PostgreSQL alongside the
    accounts it gates (SPEC.md section 10, ARCHITECTURE.md section 7).
    """

    __tablename__ = "provider_routing_controls"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_provider_routing_controls_tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    #: When true, no marketing send is routed regardless of account state.
    marketing_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    paused_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    paused_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
