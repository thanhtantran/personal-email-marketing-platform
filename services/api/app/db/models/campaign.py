from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

#: Recipient ledger states. ``queued``/``retry`` still await submission;
#: ``unknown`` means an ambiguous provider outcome that must be reconciled before
#: any retry (SPEC.md invariant 6).
RECIPIENT_STATUS_QUEUED = "queued"
RECIPIENT_STATUS_RETRY = "retry"
RECIPIENT_STATUS_ACCEPTED = "accepted"
RECIPIENT_STATUS_FAILED = "failed"
RECIPIENT_STATUS_SKIPPED = "skipped"
RECIPIENT_STATUS_UNKNOWN = "unknown"
#: Statuses that a dispatcher may still pick up.
RECIPIENT_DISPATCHABLE_STATUSES: tuple[str, ...] = (
    RECIPIENT_STATUS_QUEUED,
    RECIPIENT_STATUS_RETRY,
)


class Campaign(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A campaign draft and its lifecycle state.

    The current snapshot is the highest ``campaign_snapshots.snapshot_version``
    for the campaign, not a column here. Content and audience are frozen into a
    snapshot at launch so later template/contact edits cannot silently mutate an
    in-flight campaign (SPEC.md invariant 7).

    ``template_id``/``segment_id`` take part in composite foreign keys with
    ``tenant_id`` so a campaign can never reference another workspace's row.
    """

    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_campaigns_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "template_id"],
            ["templates.tenant_id", "templates.id"],
            name="fk_campaigns_template",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "segment_id"],
            ["segments.tenant_id", "segments.id"],
            name="fk_campaigns_segment",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    subject: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    from_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    from_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    reply_to: Mapped[str | None] = mapped_column(String(320), nullable=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    launched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class CampaignSnapshot(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Immutable content + audience definition captured at launch."""

    __tablename__ = "campaign_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "snapshot_version", name="uq_campaign_snapshots_version"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_campaign_snapshots_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            ["campaigns.tenant_id", "campaigns.id"],
            name="fk_campaign_snapshots_campaign",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    audience_definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CampaignRecipient(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per recipient of a launched campaign (the recipient ledger).

    ``idempotency_key`` is a deterministic digest of campaign + address, so a
    replayed launch can never insert a recipient twice, and
    ``UNIQUE(campaign_id, email_snapshot)`` enforces it at the database level.

    The dispatch-time columns (provider account/message, attempts, outcome) are
    populated by the provider gateway in Stage 5; the ledger exists from launch
    so pause/cancel and outcome reporting have a stable row to act on.
    """

    __tablename__ = "campaign_recipients"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "email_snapshot", name="uq_campaign_recipients_email"
        ),
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_campaign_recipients_idempotency"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_campaign_recipients_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            ["campaigns.tenant_id", "campaigns.id"],
            name="fk_campaign_recipients_campaign",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    email_snapshot: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
