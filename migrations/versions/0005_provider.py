"""provider schema: accounts, credentials, send attempts, routing controls

Creates the Stage 5 tables. Accounts and credentials are deliberately separate:
``provider_accounts`` is the quota/rate/routing boundary while
``provider_credentials`` holds only encrypted, write-only secrets, so adding an
API key can never multiply capacity (SPEC.md invariant 3). ``send_attempts`` is
written before the network call and keyed ``UNIQUE(recipient_id, attempt_no)`` so
a retried worker converges on the same attempt row.

Revision ID: 0005_provider
Revises: 0004_campaign
Create Date: 2026-11-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_provider"
down_revision: str | None = "0004_campaign"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
TEXT_ARRAY = postgresql.ARRAY(sa.String(length=32))
NOW = sa.text("now()")
GEN_UUID = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.create_table(
        "provider_accounts",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_account_ref", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), server_default="", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("eligible_message_classes", TEXT_ARRAY, server_default="{}", nullable=False),
        sa.Column("sender_domains", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("quota_state", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("limits", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("eligibility_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quota_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health_state", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_provider_accounts_tenant_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provider_accounts"),
        sa.UniqueConstraint(
            "tenant_id", "provider", "external_account_ref", name="uq_provider_accounts_external_ref"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_provider_accounts_tenant_id"),
    )
    op.create_index("ix_provider_accounts_tenant_status", "provider_accounts", ["tenant_id", "status"])

    op.create_table(
        "provider_credentials",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("provider_account_id", UUID, nullable=False),
        sa.Column("secret_ciphertext", sa.String(length=4096), nullable=False),
        sa.Column("key_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("label", sa.String(length=128), server_default="", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_provider_credentials_tenant_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "provider_account_id"],
            ["provider_accounts.tenant_id", "provider_accounts.id"],
            name="fk_provider_credentials_account",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provider_credentials"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_provider_credentials_tenant_id"),
    )
    op.create_index(
        "ix_provider_credentials_account", "provider_credentials", ["provider_account_id", "status"]
    )

    op.create_table(
        "send_attempts",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("recipient_id", UUID, nullable=False),
        sa.Column("provider_account_id", UUID, nullable=False),
        sa.Column("attempt_no", sa.Integer(), server_default="1", nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("state", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_class", sa.String(length=64), nullable=True),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("unknown_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_send_attempts_tenant_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "recipient_id"],
            ["campaign_recipients.tenant_id", "campaign_recipients.id"],
            name="fk_send_attempts_recipient",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_send_attempts"),
        sa.UniqueConstraint("recipient_id", "attempt_no", name="uq_send_attempts_recipient_no"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_send_attempts_tenant_id"),
    )
    op.create_index(
        "ix_send_attempts_tenant_state", "send_attempts", ["tenant_id", "state"]
    )
    op.create_index(
        "ix_send_attempts_account_started", "send_attempts", ["provider_account_id", "started_at"]
    )

    op.create_table(
        "provider_routing_controls",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("marketing_paused", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("paused_reason", sa.String(length=255), nullable=True),
        sa.Column("paused_by", UUID, nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_provider_routing_controls_tenant_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paused_by"],
            ["users.id"],
            name="fk_provider_routing_controls_paused_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provider_routing_controls"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_provider_routing_controls_tenant_id"),
    )


def downgrade() -> None:
    op.drop_table("provider_routing_controls")
    op.drop_index("ix_send_attempts_account_started", table_name="send_attempts")
    op.drop_index("ix_send_attempts_tenant_state", table_name="send_attempts")
    op.drop_table("send_attempts")
    op.drop_index("ix_provider_credentials_account", table_name="provider_credentials")
    op.drop_table("provider_credentials")
    op.drop_index("ix_provider_accounts_tenant_status", table_name="provider_accounts")
    op.drop_table("provider_accounts")
