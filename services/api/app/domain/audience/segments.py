"""Segment definition AST.

Segment definitions are stored as validated JSON, never as SQL. Validation
rejects unknown fields, operators and out-of-range values so that an operator
cannot smuggle arbitrary queries into audience resolution (SPEC.md section 3).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, or_, select

from app.db.models import Contact, ContactTag
from app.domain.audience.consent import CONSENT_STATUSES, CONTACT_STATUSES
from app.errors import ValidationAppError

ALLOWED_MATCH: tuple[str, ...] = ("all", "any")
CONTACT_FIELDS: tuple[str, ...] = ("status", "consent_status", "created_at", "updated_at")
MAX_CONDITIONS = 20
MAX_IN_VALUES = 100
MAX_KEY_LENGTH = 64
MAX_VALUE_LENGTH = 512

_SCALAR_OPERATORS = ("eq", "ne")
_LIST_OPERATORS = ("in", "not_in")
_DATETIME_OPERATORS = ("gt", "gte", "lt", "lte")
_ATTRIBUTE_OPERATORS = ("eq", "ne", "in", "not_in", "contains", "exists")
_TAG_OPERATORS = ("has", "not_has")


def _invalid(reason: str) -> ValidationAppError:
    return ValidationAppError("Invalid segment definition", extra={"reason": reason})


def _parse_datetime(value: Any, reason: str) -> datetime:
    if not isinstance(value, str):
        raise _invalid(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(reason) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _as_value_list(value: Any, reason: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise _invalid(reason)
    if len(value) > MAX_IN_VALUES:
        raise _invalid("too_many_values")
    return value


def _normalize_condition(condition: Any) -> dict[str, Any]:
    if not isinstance(condition, dict):
        raise _invalid("condition_not_object")
    field = condition.get("field")
    operator = condition.get("operator")
    if not isinstance(field, str) or not isinstance(operator, str):
        raise _invalid("condition_missing_field_or_operator")

    if field == "tag":
        if operator not in _TAG_OPERATORS:
            raise _invalid("unsupported_tag_operator")
        tag_value = condition.get("value")
        try:
            tag_id = str(uuid.UUID(str(tag_value)))
        except (TypeError, ValueError) as exc:
            raise _invalid("invalid_tag_id") from exc
        return {"field": "tag", "operator": operator, "value": tag_id}

    if field == "attribute":
        key = condition.get("key")
        if not isinstance(key, str) or not key or len(key) > MAX_KEY_LENGTH:
            raise _invalid("invalid_attribute_key")
        if operator not in _ATTRIBUTE_OPERATORS:
            raise _invalid("unsupported_attribute_operator")
        if operator == "exists":
            return {"field": "attribute", "key": key, "operator": operator}
        value = condition.get("value")
        if operator in _LIST_OPERATORS:
            values = _as_value_list(value, "invalid_attribute_values")
            return {"field": "attribute", "key": key, "operator": operator, "value": values}
        if not isinstance(value, str) or len(value) > MAX_VALUE_LENGTH:
            raise _invalid("invalid_attribute_value")
        return {"field": "attribute", "key": key, "operator": operator, "value": value}

    if field in ("status", "consent_status"):
        allowed = CONTACT_STATUSES if field == "status" else CONSENT_STATUSES
        if operator not in (*_SCALAR_OPERATORS, *_LIST_OPERATORS):
            raise _invalid(f"unsupported_{field}_operator")
        if operator in _LIST_OPERATORS:
            values = _as_value_list(condition.get("value"), "invalid_values")
            for value in values:
                if value not in allowed:
                    raise _invalid(f"invalid_{field}_value")
            return {"field": field, "operator": operator, "value": values}
        value = condition.get("value")
        if value not in allowed:
            raise _invalid(f"invalid_{field}_value")
        return {"field": field, "operator": operator, "value": value}

    if field in ("created_at", "updated_at"):
        if operator not in _DATETIME_OPERATORS:
            raise _invalid("unsupported_datetime_operator")
        parsed = _parse_datetime(condition.get("value"), "invalid_datetime")
        return {"field": field, "operator": operator, "value": parsed.isoformat()}

    raise _invalid("unsupported_field")


def validate_definition(raw: Any) -> dict[str, Any]:
    """Validate and normalize a segment definition, raising on anything unsafe."""
    if not isinstance(raw, dict):
        raise _invalid("definition_not_object")
    match = raw.get("match", "all")
    if match not in ALLOWED_MATCH:
        raise _invalid("invalid_match")
    conditions = raw.get("conditions")
    if not isinstance(conditions, list) or not conditions:
        raise _invalid("conditions_required")
    if len(conditions) > MAX_CONDITIONS:
        raise _invalid("too_many_conditions")
    return {"match": match, "conditions": [_normalize_condition(c) for c in conditions]}


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _attribute_column(condition: dict[str, Any]):
    return Contact.attributes[condition["key"]].astext


def _build_attribute_filter(condition: dict[str, Any]) -> ColumnElement[bool]:
    column = _attribute_column(condition)
    operator = condition["operator"]
    if operator == "exists":
        return Contact.attributes.has_key(condition["key"])
    if operator == "eq":
        return column == condition["value"]
    if operator == "ne":
        return column != condition["value"]
    if operator == "in":
        return column.in_(condition["value"])
    if operator == "not_in":
        return column.not_in(condition["value"])
    if operator == "contains":
        return column.ilike(_like_pattern(condition["value"]), escape="\\")
    raise _invalid("unsupported_attribute_operator")


def _build_tag_filter(condition: dict[str, Any], tenant_id: uuid.UUID) -> ColumnElement[bool]:
    tag_id = uuid.UUID(condition["value"])
    membership = (
        select(ContactTag.contact_id)
        .where(
            ContactTag.tenant_id == tenant_id,
            ContactTag.contact_id == Contact.id,
            ContactTag.tag_id == tag_id,
        )
        .exists()
    )
    return membership if condition["operator"] == "has" else ~membership


def _build_condition(condition: dict[str, Any], tenant_id: uuid.UUID) -> ColumnElement[bool]:
    field = condition["field"]
    operator = condition["operator"]
    if field == "tag":
        return _build_tag_filter(condition, tenant_id)
    if field == "attribute":
        return _build_attribute_filter(condition)
    if field in ("status", "consent_status"):
        column = Contact.status if field == "status" else Contact.consent_status
        if operator == "eq":
            return column == condition["value"]
        if operator == "ne":
            return column != condition["value"]
        if operator == "in":
            return column.in_(condition["value"])
        return column.not_in(condition["value"])
    column = Contact.created_at if field == "created_at" else Contact.updated_at
    value = datetime.fromisoformat(condition["value"])
    return {
        "gt": column > value,
        "gte": column >= value,
        "lt": column < value,
        "lte": column <= value,
    }[operator]


def build_filter(definition: dict[str, Any], tenant_id: uuid.UUID) -> ColumnElement[bool]:
    """Build a tenant-scoped SQL predicate for a validated definition."""
    conditions = [_build_condition(c, tenant_id) for c in definition["conditions"]]
    combined = or_(*conditions) if definition["match"] == "any" else and_(*conditions)
    return and_(Contact.tenant_id == tenant_id, combined)
