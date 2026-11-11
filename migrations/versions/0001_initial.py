"""initial identity and workspace schema

Creates tenants, users, memberships, sessions and audit_log. Tenant IDs are
non-null from the first migration so Phase 2 multi-tenancy stays additive
(SPEC.md section 12).

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("now()")
GEN_UUID = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )

    op.create_table(
        "users",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("google_subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("google_subject", name="uq_users_google_subject"),
    )

    op.create_table(
        "memberships",
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("role", sa.String(length=32), server_default="owner", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_memberships_tenant_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_memberships_user_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "user_id", name="pk_memberships"),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "sessions",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_sessions_tenant_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_sessions_user_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("actor_user_id", UUID, nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=True),
        sa.Column("object_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_audit_log_tenant_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name="fk_audit_log_actor_user_id", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
    )
    op.create_index("ix_audit_log_tenant_created", "audit_log", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_tenant_created", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("tenants")
