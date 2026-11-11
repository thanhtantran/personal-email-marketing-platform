"""content schema: templates

Creates the Stage 3 ``templates`` table. Tenant IDs are non-null, and the
composite ``(tenant_id, id)`` uniqueness supports tenant-safe references from
later campaign snapshots (SPEC.md section 3).

Revision ID: 0003_content
Revises: 0002_audience
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_content"
down_revision: str | None = "0002_audience"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
NOW = sa.text("now()")
GEN_UUID = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.create_table(
        "templates",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("editor_json", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("mjml_source", sa.Text(), nullable=False),
        sa.Column("html", sa.Text(), nullable=False),
        sa.Column("text_body", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_templates_tenant_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_templates"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_templates_tenant_id"),
    )
    op.create_index("ix_templates_tenant_status", "templates", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_templates_tenant_status", table_name="templates")
    op.drop_table("templates")
