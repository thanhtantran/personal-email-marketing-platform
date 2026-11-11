"""Segment AST validation rejects anything that could become unsafe SQL."""

from __future__ import annotations

import uuid

import pytest

from app.domain.audience.segments import MAX_CONDITIONS, build_filter, validate_definition
from app.errors import ValidationAppError


def test_valid_definition_is_normalized() -> None:
    definition = validate_definition(
        {
            "match": "all",
            "conditions": [
                {"field": "status", "operator": "eq", "value": "active"},
                {"field": "consent_status", "operator": "in", "value": ["granted"]},
            ],
        }
    )
    assert definition["match"] == "all"
    assert len(definition["conditions"]) == 2


def test_tag_condition_normalizes_uuid() -> None:
    tag_id = uuid.uuid4()
    definition = validate_definition(
        {"conditions": [{"field": "tag", "operator": "has", "value": str(tag_id)}]}
    )
    assert definition["conditions"][0]["value"] == str(tag_id)


@pytest.mark.parametrize(
    "raw",
    [
        {"conditions": [{"field": "unknown_field", "operator": "eq", "value": "x"}]},
        {"conditions": [{"field": "status", "operator": "like", "value": "active"}]},
        {"conditions": [{"field": "status", "operator": "eq", "value": "nonsense"}]},
        {"conditions": [{"field": "tag", "operator": "has", "value": "not-a-uuid"}]},
        {"conditions": [{"field": "attribute", "operator": "eq", "value": "x"}]},
        {"conditions": []},
        {"conditions": "not-a-list"},
    ],
)
def test_invalid_definitions_are_rejected(raw: dict) -> None:
    with pytest.raises(ValidationAppError):
        validate_definition(raw)


def test_too_many_conditions_rejected() -> None:
    conditions = [
        {"field": "status", "operator": "eq", "value": "active"}
        for _ in range(MAX_CONDITIONS + 1)
    ]
    with pytest.raises(ValidationAppError):
        validate_definition({"conditions": conditions})


def test_build_filter_is_tenant_scoped() -> None:
    tenant_id = uuid.uuid4()
    definition = validate_definition(
        {"conditions": [{"field": "status", "operator": "eq", "value": "active"}]}
    )
    clause = build_filter(definition, tenant_id)
    assert "contacts.tenant_id" in str(clause)
