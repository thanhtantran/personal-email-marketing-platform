"""Webhook intake log and normalized recipient events.

Two kinds of event rows are stored (SPEC.md section 3):

* ``webhook_events`` is the durable acceptance log for one provider delivery.
  ``UNIQUE(provider_account_id, provider_event_id)`` is the replay defence: a
  redelivered webhook is recorded once and every later copy is ignored, so a
  replay can never double-count analytics or re-apply suppression.
* ``message_events`` is the normalized, deduplicated recipient event stream the
  reducer and analytics read. ``event_key`` is derived per tenant so the same
  logical event can only ever exist once, and all events are retained (a later
  authoritative event resolves ``unknown`` rather than overwriting history).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin

#: Webhook acceptance states. ``received`` is written before any normalization
#: work, so an accepted-but-unprocessed delivery is always observable.
WEBHOOK_STATUS_RECEIVED = "received"
WEBHOOK_STATUS_PROCESSED = "processed"
WEBHOOK_STATUS_IGNORED = "ignored"
WEBHOOK_STATUS_FAILED = "failed"

#: Where a normalized event came from. Kept on the row so analytics can explain
#: how a recipient status was reached (provider report vs. first-party action).
SOURCE_PROVIDER_WEBHOOK = "provider_webhook"
SOURCE_UNSUBSCRIBE = "unsubscribe"


class WebhookEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A verified provider delivery accepted durably before normalization.

    Only the payload digest and an optional object-storage key are retained: the
    raw payload is bounded and TTL-managed (SPEC.md section 8), and the digest
    lets an operator confirm exactly what was received without keeping PII in
    the database.
    """

    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "provider_account_id",
            "provider_event_id",
            name="uq_webhook_events_provider_event",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_webhook_events_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "provider_account_id"],
            ["provider_accounts.tenant_id", "provider_accounts.id"],
            name="fk_webhook_events_account",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    provider_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    #: Provider event id, or a stable digest derived from the canonical payload
    #: when the provider omits one (SPEC.md section 7).
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Raw provider event name as received; normalization happens asynchronously.
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=WEBHOOK_STATUS_RECEIVED
    )


class MessageEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One normalized recipient event in the campaign timeline.

    ``event_key`` collapses duplicate deliveries of the same logical event; the
    row is never updated in place, so analytics can separate distinct recipients
    from total events (SPEC.md section 7).
    """

    __tablename__ = "message_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_key", name="uq_message_events_tenant_key"),
        UniqueConstraint("tenant_id", "id", name="uq_message_events_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            ["campaigns.tenant_id", "campaigns.id"],
            name="fk_message_events_campaign",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "recipient_id"],
            ["campaign_recipients.tenant_id", "campaign_recipients.id"],
            name="fk_message_events_recipient",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    recipient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_key: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Provider metadata (raw event name, provider message id, bounce detail).
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
