"""CSV import planning: classification, dedupe and merge safety rules."""

from __future__ import annotations

import pytest

from app.domain.audience.imports import (
    OUTCOME_ACCEPTED,
    OUTCOME_DUPLICATE,
    OUTCOME_INVALID,
    OUTCOME_MISSING_CONSENT,
    ContactState,
    ImportMapping,
    RowPlan,
    parse_and_plan,
    plan_merge_actions,
    reclassify_duplicates,
)
from app.errors import ValidationAppError

LIMITS = {"max_rows": 1000, "max_columns": 50, "max_field_length": 100}


def _make_row(**overrides: object) -> RowPlan:
    base = {
        "row_number": 1,
        "outcome": OUTCOME_ACCEPTED,
        "error_code": None,
        "row_digest": "digest",
        "normalized_email": "a@example.com",
        "email_display": "a@example.com",
        "consent_status": "granted",
        "consent_at": None,
        "consent_source": None,
        "consent_evidence_ref": None,
        "attributes": {},
    }
    base.update(overrides)
    return RowPlan(**base)  # type: ignore[arg-type]


def test_mapping_requires_email_column() -> None:
    with pytest.raises(ValidationAppError):
        ImportMapping.parse({"attributes": {"name": "name"}})


def test_mapping_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationAppError):
        ImportMapping.parse({"email": "email", "bogus": "x"})


def test_plan_classifies_rows() -> None:
    mapping = ImportMapping.parse({"email": "email", "attributes": {"first": "first"}})
    content = (
        b"email,first\n"
        b"Alice@example.com,Alice\n"
        b"alice@example.com,Alice Again\n"
        b"not-an-email,Bad\n"
        b"bob@example.com,Bob\n"
    )
    plan = parse_and_plan(content, mapping, **LIMITS)
    assert plan.counts["total"] == 4
    assert plan.counts[OUTCOME_ACCEPTED] == 2
    assert plan.counts[OUTCOME_DUPLICATE] == 1
    assert plan.counts[OUTCOME_INVALID] == 1


def test_missing_consent_is_flagged() -> None:
    mapping = ImportMapping.parse({"email": "email", "consent_status": "consent"})
    content = b"email,consent\nc@example.com,denied\n"
    plan = parse_and_plan(content, mapping, **LIMITS)
    assert plan.counts[OUTCOME_MISSING_CONSENT] == 1
    assert plan.counts[OUTCOME_ACCEPTED] == 0


def test_missing_mapped_column_is_rejected() -> None:
    mapping = ImportMapping.parse({"email": "email", "attributes": {"first": "first_name"}})
    with pytest.raises(ValidationAppError):
        parse_and_plan(b"email\nx@example.com\n", mapping, **LIMITS)


def test_reclassify_duplicates_uses_existing_emails() -> None:
    mapping = ImportMapping.parse({"email": "email"})
    plan = parse_and_plan(b"email\na@example.com\nb@example.com\n", mapping, **LIMITS)
    assert plan.counts[OUTCOME_ACCEPTED] == 2
    updated = reclassify_duplicates(plan, {"a@example.com"})
    assert updated.counts[OUTCOME_ACCEPTED] == 1
    assert updated.counts[OUTCOME_DUPLICATE] == 1


def test_merge_never_unsuppresses_or_regrants_consent() -> None:
    incoming = _make_row(consent_status="granted")
    locked = ContactState(status="unsubscribed", consent_status="denied", attributes={})
    fields = plan_merge_actions(locked, incoming, "overwrite", suppressed=False)
    assert "consent_status" not in fields

    suppressed = ContactState(status="active", consent_status="unknown", attributes={})
    fields = plan_merge_actions(suppressed, incoming, "overwrite", suppressed=True)
    assert "consent_status" not in fields


def test_merge_overwrite_can_grant_consent_on_clean_contact() -> None:
    incoming = _make_row(consent_status="granted", consent_source="import")
    state = ContactState(status="active", consent_status="unknown", attributes={})
    fields = plan_merge_actions(state, incoming, "overwrite", suppressed=False)
    assert fields["consent_status"] == "granted"
    assert fields["consent_source"] == "import"


def test_merge_fill_missing_only_writes_absent_attributes() -> None:
    incoming = _make_row(attributes={"first": "Alice", "city": "Hanoi"})
    state = ContactState(
        status="active", consent_status="granted", attributes={"first": "Existing"}
    )
    fields = plan_merge_actions(state, incoming, "fill_missing", suppressed=False)
    assert fields["attributes"] == {"first": "Existing", "city": "Hanoi"}
