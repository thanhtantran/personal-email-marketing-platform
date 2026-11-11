"""Audience response schemas build correctly from ORM-style objects."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.schemas.audience import ContactOut


def test_contact_out_defaults_tags_when_absent() -> None:
    now = datetime.now(UTC)
    contact = SimpleNamespace(
        id=uuid.uuid4(),
        normalized_email="a@example.com",
        email_display="A <a@example.com>",
        status="active",
        consent_status="granted",
        consent_at=None,
        consent_source=None,
        consent_evidence_ref=None,
        attributes={"first": "Alice"},
        created_at=now,
        updated_at=now,
    )
    out = ContactOut.model_validate(contact)
    assert out.tags == []
    assert out.attributes == {"first": "Alice"}
