from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Segment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A saved, reusable audience definition.

    ``definition`` is a validated AST (see ``app.domain.audience.segments``),
    never raw SQL. Storing the AST keeps tenant scoping and operator allowlists
    in application code (SPEC.md section 3).
    """

    __tablename__ = "segments"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
