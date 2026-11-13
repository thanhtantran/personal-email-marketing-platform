"""campaign schema: campaigns, snapshots, recipient ledger, outbox, idempotency

Creates the Stage 4 tables. ``segments`` gains a ``(tenant_id, id)`` unique
constraint so campaigns can reference a segment through a composite foreign key
that cannot cross tenants. Recipients are unique per campaign and address, and
the outbox has a per-tenant dedupe key, so a replayed launch cannot create
duplicate work (SPEC.md sections 3 and 4).

Revision ID: 0004_campaign
Revises: 0003_content
Create Date: 2026-11-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_campaign"
down_revision: str | None = "0003_content"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
NOW = sa.text("now()")
GEN_UUID = sa.text("gen_random_uuid()")


def upgrade() -> None:
    # A segment must be addressable by (tenant_id, id) for the composite FK below.
    op.create_unique_constraint("uq_segments_tenant_id", "segments", ["tenant_id", "id"])

    op.create_table(
        "campaigns",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("subject", sa.String(length=255), server_default="", nullable=False),
        sa.Column("from_name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("from_email", sa.String(length=320), server_default="", nullable=False),
        sa.Column("reply_to", sa.String(length=320), nullable=True),
        sa.Column("template_id", UUID, nullable=True),
        sa.Column("template_version", sa.Integer(), nullable=True),
        sa.Column("segment_id", UUID, nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_timezone", sa.String(length=64), nullable=True),
        sa.Column("launched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_campaigns_tenant_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_campaigns_created_by", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "template_id"],
            ["templates.tenant_id", "templates.id"],
            name="fk_campaigns_template",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "segment_id"],
            ["segments.tenant_id", "segments.id"],
            name="fk_campaigns_segment",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_campaigns"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_campaigns_tenant_id"),
    )
    op.create_index("ix_campaigns_tenant_status", "campaigns", ["tenant_id", "status"])
    op.create_index("ix_campaigns_due", "campaigns", ["status", "scheduled_at"])

    op.create_table(
        "campaign_snapshots",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("campaign_id", UUID, nullable=False),
        sa.Column("snapshot_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("content", JSONB, nullable=False),
        sa.Column("audience_definition", JSONB, nullable=False),
        sa.Column("recipient_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_campaign_snapshots_tenant_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            ["campaigns.tenant_id", "campaigns.id"],
            name="fk_campaign_snapshots_campaign",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_campaign_snapshots"),
        sa.UniqueConstraint(
            "campaign_id", "snapshot_version", name="uq_campaign_snapshots_version"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_campaign_snapshots_tenant_id"),
    )

    op.create_table(
        "campaign_recipients",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("campaign_id", UUID, nullable=False),
        sa.Column("contact_id", UUID, nullable=True),
        sa.Column("email_snapshot", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("provider_account_id", UUID, nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_campaign_recipients_tenant_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            ["campaigns.tenant_id", "campaigns.id"],
            name="fk_campaign_recipients_campaign",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name="fk_campaign_recipients_contact_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_campaign_recipients"),
        sa.UniqueConstraint(
            "campaign_id", "email_snapshot", name="uq_campaign_recipients_email"
        ),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_campaign_recipients_idempotency"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_campaign_recipients_tenant_id"),
    )
    op.create_index(
        "ix_campaign_recipients_tenant_campaign_status",
        "campaign_recipients",
        ["tenant_id", "campaign_id", "status"],
    )
    op.create_index(
        "ix_campaign_recipients_tenant_next_attempt",
        "campaign_recipients",
        ["tenant_id", "next_attempt_at"],
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", UUID, nullable=False),
        sa.Column("payload", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("dedupe_key", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_outbox_events_tenant_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
        sa.UniqueConstraint("tenant_id", "dedupe_key", name="uq_outbox_events_dedupe"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_outbox_events_tenant_id"),
    )
    op.create_index("ix_outbox_events_claim", "outbox_events", ["status", "available_at"])

    op.create_table(
        "idempotency_keys",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("object_id", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_idempotency_keys_tenant_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_idempotency_keys"),
        sa.UniqueConstraint("tenant_id", "scope", "key", name="uq_idempotency_keys_scope"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.drop_index("ix_outbox_events_claim", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index(
        "ix_campaign_recipients_tenant_next_attempt", table_name="campaign_recipients"
    )
    op.drop_index(
        "ix_campaign_recipients_tenant_campaign_status", table_name="campaign_recipients"
    )
    op.drop_table("campaign_recipients")
    op.drop_table("campaign_snapshots")
    op.drop_index("ix_campaigns_due", table_name="campaigns")
    op.drop_index("ix_campaigns_tenant_status", table_name="campaigns")
    op.drop_table("campaigns")
    op.drop_constraint("uq_segments_tenant_id", "segments", type_="unique")
