"""audience schema: contacts, tags, segments, suppressions, imports

Creates the Stage 2 audience tables with tenant-scoped composite constraints so
cross-tenant references are impossible (SPEC.md section 3). Tenant IDs are
non-null on every table.

Revision ID: 0002_audience
Revises: 0001_initial
Create Date: 2026-11-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_audience"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
NOW = sa.text("now()")
GEN_UUID = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("normalized_email", sa.String(length=320), nullable=False),
        sa.Column("email_display", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("consent_status", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_source", sa.String(length=128), nullable=True),
        sa.Column("consent_evidence_ref", sa.String(length=255), nullable=True),
        sa.Column("attributes", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_contacts_tenant_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_contacts"),
        sa.UniqueConstraint("tenant_id", "normalized_email", name="uq_contacts_tenant_email"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_contacts_tenant_id"),
    )
    op.create_index("ix_contacts_tenant_status", "contacts", ["tenant_id", "status"])
    op.create_index(
        "ix_contacts_tenant_normalized_email", "contacts", ["tenant_id", "normalized_email"]
    )

    op.create_table(
        "tags",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("normalized_name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_tags_tenant_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tags"),
        sa.UniqueConstraint("tenant_id", "normalized_name", name="uq_tags_tenant_name"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tags_tenant_id"),
    )

    op.create_table(
        "contact_tags",
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("contact_id", UUID, nullable=False),
        sa.Column("tag_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["contacts.tenant_id", "contacts.id"],
            name="fk_contact_tags_contact",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tag_id"],
            ["tags.tenant_id", "tags.id"],
            name="fk_contact_tags_tag",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "contact_id", "tag_id", name="pk_contact_tags"),
        sa.UniqueConstraint("contact_id", "tag_id", name="uq_contact_tags_contact_tag"),
    )
    op.create_index("ix_contact_tags_tenant_tag", "contact_tags", ["tenant_id", "tag_id"])

    op.create_table(
        "segments",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("definition", JSONB, nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_segments_tenant_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_segments"),
    )

    op.create_table(
        "suppressions",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("normalized_email", sa.String(length=320), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_suppressions_tenant_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_suppressions"),
        sa.UniqueConstraint(
            "tenant_id", "normalized_email", "reason", name="uq_suppressions_tenant_email_reason"
        ),
    )
    op.create_index(
        "ix_suppressions_tenant_email", "suppressions", ["tenant_id", "normalized_email"]
    )

    op.create_table(
        "imports",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("uploaded_object_key", sa.String(length=512), nullable=True),
        sa.Column("mapping", JSONB, nullable=True),
        sa.Column("status", sa.String(length=32), server_default="awaiting_upload", nullable=False),
        sa.Column("counts", JSONB, nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_imports_tenant_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_imports_created_by", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_imports"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_imports_tenant_idempotency"),
    )

    op.create_table(
        "import_rows",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("import_id", UUID, nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("contact_id", UUID, nullable=True),
        sa.Column("row_digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_import_rows_tenant_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["import_id"], ["imports.id"], name="fk_import_rows_import_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], name="fk_import_rows_contact_id", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_import_rows"),
        sa.UniqueConstraint("import_id", "row_number", name="uq_import_rows_import_row"),
    )


def downgrade() -> None:
    op.drop_table("import_rows")
    op.drop_table("imports")
    op.drop_index("ix_suppressions_tenant_email", table_name="suppressions")
    op.drop_table("suppressions")
    op.drop_table("segments")
    op.drop_index("ix_contact_tags_tenant_tag", table_name="contact_tags")
    op.drop_table("contact_tags")
    op.drop_table("tags")
    op.drop_index("ix_contacts_tenant_normalized_email", table_name="contacts")
    op.drop_index("ix_contacts_tenant_status", table_name="contacts")
    op.drop_table("contacts")
