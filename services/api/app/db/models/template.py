from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Template(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A versioned email template.

    ``editor_json`` is the GrapesJS editor state, ``mjml_source`` is the
    authoritative source that the server renders. ``html`` and ``text_body`` are
    derived, sanitized output kept so a saved template can be reopened and
    rendered reproducibly without re-running the editor (SPEC.md section 3).
    """

    __tablename__ = "templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_templates_tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    editor_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    mjml_source: Mapped[str] = mapped_column(Text, nullable=False)
    html: Mapped[str] = mapped_column(Text, nullable=False)
    text_body: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
