"""CSV import planning.

Pure functions that turn a staged CSV plus a column mapping into a per-row plan.
The plan drives both the preview counts and the idempotent commit, so preview and
commit can never disagree about a row's outcome (SPEC.md section 3.1).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from app.domain.audience.consent import CONSENT_STATUSES
from app.domain.audience.emails import normalize_email
from app.errors import ValidationAppError

OUTCOME_ACCEPTED = "accepted"
OUTCOME_DUPLICATE = "duplicate"
OUTCOME_INVALID = "invalid"
OUTCOME_MISSING_CONSENT = "missing_consent"
OUTCOMES: tuple[str, ...] = (
    OUTCOME_ACCEPTED,
    OUTCOME_DUPLICATE,
    OUTCOME_INVALID,
    OUTCOME_MISSING_CONSENT,
)

MERGE_POLICIES: tuple[str, ...] = ("skip", "fill_missing", "overwrite")

RESERVED_FIELDS: tuple[str, ...] = (
    "email",
    "consent_status",
    "consent_at",
    "consent_source",
    "consent_evidence_ref",
)


@dataclass(frozen=True)
class ImportMapping:
    email: str
    consent_status: str | None = None
    consent_at: str | None = None
    consent_source: str | None = None
    consent_evidence_ref: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: Any) -> ImportMapping:
        if not isinstance(raw, dict):
            raise ValidationAppError(
                "Mapping must be an object", extra={"reason": "mapping_not_object"}
            )
        unknown = set(raw) - set(RESERVED_FIELDS) - {"attributes"}
        if unknown:
            raise ValidationAppError(
                "Mapping has unsupported fields", extra={"reason": "unsupported_mapping_field"}
            )
        email = raw.get("email")
        if not isinstance(email, str) or not email.strip():
            raise ValidationAppError(
                "Mapping requires an email column", extra={"reason": "missing_email_mapping"}
            )
        attributes: dict[str, str] = {}
        raw_attributes = raw.get("attributes", {})
        if not isinstance(raw_attributes, dict):
            raise ValidationAppError(
                "Mapping attributes must be an object",
                extra={"reason": "invalid_attributes_mapping"},
            )
        for key, column in raw_attributes.items():
            if not isinstance(key, str) or not isinstance(column, str) or not column.strip():
                raise ValidationAppError(
                    "Invalid attribute mapping", extra={"reason": "invalid_attributes_mapping"}
                )
            attributes[key] = column
        optional: dict[str, str] = {}
        for name in RESERVED_FIELDS[1:]:
            value = raw.get(name)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValidationAppError(
                    "Invalid mapping column", extra={"reason": "invalid_mapping_column"}
                )
            optional[name] = value
        return cls(email=email, attributes=attributes, **optional)

    def columns(self) -> list[str]:
        return [self.email, *self.attributes.values(), *self.optional_columns()]

    def optional_columns(self) -> list[str]:
        return [value for value in (self.consent_status, self.consent_at, self.consent_source,
                                    self.consent_evidence_ref) if value]


@dataclass(frozen=True)
class RowPlan:
    row_number: int
    outcome: str
    error_code: str | None
    row_digest: str
    normalized_email: str | None
    email_display: str | None
    consent_status: str
    consent_at: datetime | None
    consent_source: str | None
    consent_evidence_ref: str | None
    attributes: dict[str, str]


@dataclass(frozen=True)
class ImportPlan:
    counts: dict[str, int]
    rows: list[RowPlan]
    truncated: bool


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _row(
    *,
    row_number: int,
    outcome: str,
    error_code: str | None = None,
    normalized_email: str | None = None,
    email_display: str | None = None,
    consent_status: str = "unknown",
    consent_at: datetime | None = None,
    consent_source: str | None = None,
    consent_evidence_ref: str | None = None,
    attributes: dict[str, str] | None = None,
) -> RowPlan:
    attributes = attributes or {}
    digest = _digest(
        {
            "email": normalized_email or email_display,
            "consent_status": consent_status,
            "consent_at": consent_at.isoformat() if consent_at else None,
            "attributes": attributes,
        }
    )
    return RowPlan(
        row_number=row_number,
        outcome=outcome,
        error_code=error_code,
        row_digest=digest,
        normalized_email=normalized_email,
        email_display=email_display,
        consent_status=consent_status,
        consent_at=consent_at,
        consent_source=consent_source,
        consent_evidence_ref=consent_evidence_ref,
        attributes=attributes,
    )


def parse_and_plan(
    content: bytes,
    mapping: ImportMapping,
    *,
    consent_default: str = "granted",
    existing_emails: set[str] | None = None,
    max_rows: int,
    max_columns: int,
    max_field_length: int,
) -> ImportPlan:
    """Parse a CSV and classify every row without touching the database."""
    if not content:
        raise ValidationAppError("Uploaded file is empty", extra={"reason": "empty_file"})
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationAppError(
            "Uploaded file must be UTF-8 encoded", extra={"reason": "invalid_encoding"}
        ) from exc

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    if not fieldnames:
        raise ValidationAppError("CSV has no header row", extra={"reason": "missing_header"})
    if len(fieldnames) > max_columns:
        raise ValidationAppError("CSV has too many columns", extra={"reason": "too_many_columns"})
    for column in mapping.columns():
        if column not in fieldnames:
            raise ValidationAppError(
                "Mapped column is not present in the CSV",
                extra={"reason": "missing_column", "column": column},
            )

    known = set(existing_emails or ())
    counts = {"total": 0, **dict.fromkeys(OUTCOMES, 0)}
    plans: list[RowPlan] = []
    truncated = False

    for index, raw_row in enumerate(reader, start=1):
        if len(plans) >= max_rows:
            truncated = True
            break
        counts["total"] += 1
        plan = _plan_row(
            raw_row,
            row_number=index,
            mapping=mapping,
            consent_default=consent_default,
            known=known,
            max_field_length=max_field_length,
        )
        counts[plan.outcome] += 1
        if plan.normalized_email:
            known.add(plan.normalized_email)
        plans.append(plan)

    return ImportPlan(counts=counts, rows=plans, truncated=truncated)


def _optional(values: dict[str, str], column: str | None) -> str | None:
    if not column:
        return None
    return values.get(column, "").strip() or None


@dataclass(frozen=True)
class ContactState:
    status: str
    consent_status: str
    attributes: dict[str, str]


def plan_merge_actions(
    state: ContactState, incoming: RowPlan, policy: str, *, suppressed: bool
) -> dict[str, Any]:
    """Fields to write when an existing contact is seen again during import.

    Two safety rules always hold: a suppressed or unsubscribed contact never
    regains consent, and an import can never clear a suppression.
    """
    if policy not in MERGE_POLICIES:
        raise ValidationAppError(
            "Unsupported merge policy", extra={"reason": "invalid_merge_policy"}
        )

    fields: dict[str, Any] = {}
    current_attributes = dict(state.attributes or {})
    if policy == "fill_missing":
        merged = dict(current_attributes)
        for key, value in incoming.attributes.items():
            if not merged.get(key):
                merged[key] = value
    elif policy == "overwrite":
        merged = {**current_attributes, **incoming.attributes}
    else:  # skip
        merged = current_attributes
    if merged != current_attributes:
        fields["attributes"] = merged

    locked = suppressed or state.status in ("unsubscribed", "suppressed")
    if locked:
        return fields

    incoming_granted = incoming.consent_status == "granted"
    grants_consent = incoming_granted and (
        policy == "overwrite"
        or (policy == "fill_missing" and state.consent_status in ("unknown", "pending"))
    )
    if grants_consent:
        fields.update(
            consent_status="granted",
            consent_at=incoming.consent_at,
            consent_source=incoming.consent_source,
            consent_evidence_ref=incoming.consent_evidence_ref,
        )
    return fields


def reclassify_duplicates(plan: ImportPlan, existing_emails: set[str]) -> ImportPlan:
    """Move accepted rows that already exist in the database to ``duplicate``."""
    if not existing_emails:
        return plan
    counts = {"total": plan.counts["total"], **dict.fromkeys(OUTCOMES, 0)}
    rows: list[RowPlan] = []
    for row in plan.rows:
        outcome = row.outcome
        if outcome == OUTCOME_ACCEPTED and row.normalized_email in existing_emails:
            outcome = OUTCOME_DUPLICATE
        counts[outcome] += 1
        rows.append(row if outcome == row.outcome else replace(row, outcome=outcome))
    return ImportPlan(counts=counts, rows=rows, truncated=plan.truncated)


def _plan_row(
    raw_row: dict[str, str | None],
    *,
    row_number: int,
    mapping: ImportMapping,
    consent_default: str,
    known: set[str],
    max_field_length: int,
) -> RowPlan:
    values = {key: (value or "") for key, value in raw_row.items() if key is not None}

    for value in values.values():
        if len(value) > max_field_length:
            return _row(row_number=row_number, outcome=OUTCOME_INVALID, error_code="field_too_long")

    display = values.get(mapping.email, "").strip()
    normalized = normalize_email(display)
    if normalized is None:
        return _row(
            row_number=row_number,
            outcome=OUTCOME_INVALID,
            error_code="invalid_email",
            email_display=display or None,
        )

    raw_consent = ""
    if mapping.consent_status:
        raw_consent = values.get(mapping.consent_status, "").strip().lower()
    consent_status = raw_consent or consent_default
    if consent_status not in CONSENT_STATUSES:
        return _row(
            row_number=row_number,
            outcome=OUTCOME_INVALID,
            error_code="invalid_consent_status",
            normalized_email=normalized,
            email_display=display,
        )

    consent_at: datetime | None = None
    if mapping.consent_at:
        raw_date = values.get(mapping.consent_at, "").strip()
        if raw_date:
            consent_at = _parse_datetime(raw_date)
            if consent_at is None:
                return _row(
                    row_number=row_number,
                    outcome=OUTCOME_INVALID,
                    error_code="invalid_consent_at",
                    normalized_email=normalized,
                    email_display=display,
                )

    attributes = {
        key: values.get(column, "").strip()
        for key, column in mapping.attributes.items()
        if values.get(column, "").strip()
    }
    consent_source = _optional(values, mapping.consent_source)
    evidence = _optional(values, mapping.consent_evidence_ref)

    if normalized in known:
        return _row(
            row_number=row_number,
            outcome=OUTCOME_DUPLICATE,
            normalized_email=normalized,
            email_display=display,
            consent_status=consent_status,
            consent_at=consent_at,
            consent_source=consent_source,
            consent_evidence_ref=evidence,
            attributes=attributes,
        )

    if consent_status != "granted":
        return _row(
            row_number=row_number,
            outcome=OUTCOME_MISSING_CONSENT,
            error_code="missing_consent",
            normalized_email=normalized,
            email_display=display,
            consent_status=consent_status,
            consent_at=consent_at,
            consent_source=consent_source,
            consent_evidence_ref=evidence,
            attributes=attributes,
        )

    return _row(
        row_number=row_number,
        outcome=OUTCOME_ACCEPTED,
        normalized_email=normalized,
        email_display=display,
        consent_status=consent_status,
        consent_at=consent_at,
        consent_source=consent_source,
        consent_evidence_ref=evidence,
        attributes=attributes,
    )
