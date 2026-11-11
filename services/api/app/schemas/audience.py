"""Request/response schemas for audience, segments, suppressions and imports."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    normalized_email: str
    email_display: str
    status: str
    consent_status: str
    consent_at: datetime | None = None
    consent_source: str | None = None
    consent_evidence_ref: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    tags: list[TagOut] = Field(default_factory=list)


class ContactCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    status: str = "active"
    consent_status: str = "unknown"
    consent_at: datetime | None = None
    consent_source: str | None = Field(default=None, max_length=128)
    consent_evidence_ref: str | None = Field(default=None, max_length=255)
    attributes: dict[str, Any] = Field(default_factory=dict)
    tag_ids: list[uuid.UUID] = Field(default_factory=list)


class ContactUpdate(BaseModel):
    status: str | None = None
    consent_status: str | None = None
    consent_at: datetime | None = None
    consent_source: str | None = Field(default=None, max_length=128)
    consent_evidence_ref: str | None = Field(default=None, max_length=255)
    attributes: dict[str, Any] | None = None


class ContactPage(BaseModel):
    items: list[ContactOut]
    next_cursor: str | None = None
    total: int


class SuppressionCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    reason: str
    source: str | None = Field(default=None, max_length=64)
    occurred_at: datetime | None = None
    evidence: dict[str, Any] | None = None


class SuppressionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    normalized_email: str
    reason: str
    source: str | None = None
    occurred_at: datetime
    expires_at: datetime | None = None
    evidence: dict[str, Any] | None = None


class SegmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    definition: dict[str, Any]


class SegmentUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    definition: dict[str, Any]


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    definition: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime


class SegmentEstimate(BaseModel):
    segment_id: uuid.UUID
    match_count: int
    eligible_count: int


class ImportCreate(BaseModel):
    mapping: dict[str, Any]


class ImportCreated(BaseModel):
    import_id: uuid.UUID
    status: str
    upload_url: str
    upload_expires_seconds: int


class ImportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    counts: dict[str, Any] | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ImportPreviewRow(BaseModel):
    row_number: int
    outcome: str
    error_code: str | None = None


class ImportPreview(BaseModel):
    import_id: uuid.UUID
    status: str
    counts: dict[str, int]
    truncated: bool
    errors: list[ImportPreviewRow]
    errors_truncated: bool


class ImportCommitRequest(BaseModel):
    merge_policy: str = "skip"
