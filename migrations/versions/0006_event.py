"""event schema: webhook intake log, normalized message events, webhook config

Creates the Stage 6 tables and the provider-account columns the webhook route
needs. ``webhook_events`` keys ``(provider_account_id, provider_event_id)`` so a
replayed delivery is stored exactly once, and ``message_events`` keys
``(tenant_id, event_key)`` so a normalized event cannot be counted twice
(SPEC.md sections 3 and 7).

``provider_accounts.webhook_public_id`` is an unguessable handle for the public
intake URL; it is separate from the row id so a leaked webhook URL never
discloses an internal identifier. The signing secret is stored as the same
AES-256-GCM envelope as a provider credential and is never returned by an API.

Revision ID: 0006_event
Revises: 0005_provider
Create Date: 2026-11-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_event"
down_revision: str | None = "0005_provider"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
NOW = sa.text("now()")
GEN_UUID = sa.text("gen_random_uuid()")


def upgrade() -> None:
    # Existing accounts get a generated public id, so the webhook route works
    # without an operator action after the upgrade.
    op.add_column(
        "provider_accounts",
        sa.Column(
            "webhook_public_id", UUID, server_default=GEN_UUID, nullable=False
        ),
    )
    op.add_column(
        "provider_accounts",
        sa.Column("webhook_secret_ciphertext", sa.String(length=4096), nullable=True),
    )
    op.add_column(
        "provider_accounts",
        sa.Column("webhook_secret_key_version", sa.Integer(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_provider_accounts_webhook_public_id", "provider_accounts", ["webhook_public_id"]
    )

    op.create_table(
        "webhook_events",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("provider_account_id", UUID, nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=64), server_default="", nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("payload_object_key", sa.String(length=512), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="received", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_webhook_events_tenant_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "provider_account_id"],
            ["provider_accounts.tenant_id", "provider_accounts.id"],
            name="fk_webhook_events_account",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_webhook_events"),
        sa.UniqueConstraint(
            "provider_account_id",
            "provider_event_id",
            name="uq_webhook_events_provider_event",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_webhook_events_tenant_id"),
    )
    op.create_index(
        "ix_webhook_events_account_occurred",
        "webhook_events",
        ["provider_account_id", "occurred_at"],
    )
    op.create_index(
        "ix_webhook_events_status_received", "webhook_events", ["status", "received_at"]
    )

    op.create_table(
        "message_events",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("campaign_id", UUID, nullable=False),
        sa.Column("recipient_id", UUID, nullable=False),
        sa.Column("provider_account_id", UUID, nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_key", sa.String(length=128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_message_events_tenant_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            ["campaigns.tenant_id", "campaigns.id"],
            name="fk_message_events_campaign",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "recipient_id"],
            ["campaign_recipients.tenant_id", "campaign_recipients.id"],
            name="fk_message_events_recipient",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_message_events"),
        sa.UniqueConstraint("tenant_id", "event_key", name="uq_message_events_tenant_key"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_message_events_tenant_id"),
    )
    op.create_index(
        "ix_message_events_tenant_campaign_type",
        "message_events",
        ["tenant_id", "campaign_id", "event_type"],
    )
    op.create_index(
        "ix_message_events_tenant_recipient",
        "message_events",
        ["tenant_id", "recipient_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_message_events_tenant_recipient", table_name="message_events")
    op.drop_index("ix_message_events_tenant_campaign_type", table_name="message_events")
    op.drop_table("message_events")
    op.drop_index("ix_webhook_events_status_received", table_name="webhook_events")
    op.drop_index("ix_webhook_events_account_occurred", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_constraint(
        "uq_provider_accounts_webhook_public_id", "provider_accounts", type_="unique"
    )
    op.drop_column("provider_accounts", "webhook_secret_key_version")
    op.drop_column("provider_accounts", "webhook_secret_ciphertext")
    op.drop_column("provider_accounts", "webhook_public_id")
