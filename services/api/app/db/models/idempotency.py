from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, UUIDPrimaryKeyMixin


class IdempotencyKey(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Records a client-supplied ``Idempotency-Key`` for a mutating request.

    ``request_hash`` detects reuse of the same key with a different body, which
    must fail with 409 rather than silently replaying a different operation
    (SPEC.md section 4). ``object_id`` points at the resource the first request
    produced so a retry returns the same result.
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("tenant_id", "scope", "key", name="uq_idempotency_keys_scope"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
