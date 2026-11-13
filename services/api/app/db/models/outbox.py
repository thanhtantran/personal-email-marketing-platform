from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class OutboxEvent(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Transactional outbox row.

    A row is written in the same transaction as the state change that produces
    the work, so a database commit and a queue publish can never diverge. The
    dispatcher claims rows with ``FOR UPDATE SKIP LOCKED`` and publishes them;
    ``dedupe_key`` stops the same logical work being enqueued twice
    (ARCHITECTURE.md section 7).
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dedupe_key", name="uq_outbox_events_dedupe"),
        UniqueConstraint("tenant_id", "id", name="uq_outbox_events_tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
