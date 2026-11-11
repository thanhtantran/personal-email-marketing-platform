"""SQLAlchemy declarative base.

All tenant-owned models are declared against this metadata. Concrete tables are
added in Stage 1 and later stages.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
