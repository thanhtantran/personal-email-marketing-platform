from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Contact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A stored recipient.

    ``status`` and ``consent_status`` are deliberately distinct: a valid,
    reachable address may still lack marketing consent. ``deleted_at`` provides
    soft delete so suppression/audit references survive (SPEC.md section 3).
    """

    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "normalized_email", name="uq_contacts_tenant_email"),
        UniqueConstraint("tenant_id", "id", name="uq_contacts_tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    normalized_email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_display: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    consent_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    consent_evidence_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Tag(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("tenant_id", "normalized_name", name="uq_tags_tenant_name"),
        UniqueConstraint("tenant_id", "id", name="uq_tags_tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(128), nullable=False)


class ContactTag(CreatedAtMixin, Base):
    __tablename__ = "contact_tags"
    __table_args__ = (
        UniqueConstraint("contact_id", "tag_id", name="uq_contact_tags_contact_tag"),
        ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["contacts.tenant_id", "contacts.id"],
            name="fk_contact_tags_contact",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "tag_id"],
            ["tags.tenant_id", "tags.id"],
            name="fk_contact_tags_tag",
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    contact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)


class Suppression(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Authoritative do-not-send record.

    Suppression outranks contact fields and campaign snapshots: it is rechecked
    immediately before any provider submission (SPEC.md invariants 5 and 8).
    """

    __tablename__ = "suppressions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "normalized_email", "reason", name="uq_suppressions_tenant_email_reason"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    normalized_email: Mapped[str] = mapped_column(String(320), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
