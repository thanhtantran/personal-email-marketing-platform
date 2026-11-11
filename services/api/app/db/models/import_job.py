from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class ImportJob(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A CSV import session.

    The staged object key points at a private object-storage location. Rows are
    summarized in ``counts``; full CSV rows are not retained indefinitely
    (SPEC.md section 3).
    """

    __tablename__ = "imports"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_imports_tenant_idempotency"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    uploaded_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mapping: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="awaiting_upload")
    counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImportRow(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Per-row outcome. ``row_digest`` lets a resumed commit detect that a row
    was already applied without storing the full source row."""

    __tablename__ = "import_rows"
    __table_args__ = (
        UniqueConstraint("import_id", "row_number", name="uq_import_rows_import_row"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    import_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("imports.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    row_digest: Mapped[str] = mapped_column(String(64), nullable=False)
