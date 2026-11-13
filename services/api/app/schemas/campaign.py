"""Request/response schemas for campaigns, scheduling and the recipient ledger."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    subject: str = Field(default="", max_length=255)
    from_name: str = Field(default="", max_length=255)
    from_email: str = Field(default="", max_length=320)
    reply_to: str | None = Field(default=None, max_length=320)
    template_id: uuid.UUID | None = None
    segment_id: uuid.UUID | None = None


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    subject: str | None = Field(default=None, max_length=255)
    from_name: str | None = Field(default=None, max_length=255)
    from_email: str | None = Field(default=None, max_length=320)
    reply_to: str | None = Field(default=None, max_length=320)
    template_id: uuid.UUID | None = None
    segment_id: uuid.UUID | None = None


class CampaignSummary(BaseModel):
    """Collection view: the fields an operator needs to identify a campaign."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: str
    subject: str
    from_name: str
    from_email: str
    template_id: uuid.UUID | None = None
    template_version: int | None = None
    segment_id: uuid.UUID | None = None
    scheduled_at: datetime | None = None
    scheduled_timezone: str | None = None
    launched_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CampaignOut(CampaignSummary):
    reply_to: str | None = None
    created_by: uuid.UUID | None = None


class CampaignPage(BaseModel):
    items: list[CampaignSummary]
    next_cursor: str | None = None
    total: int


class ScheduleRequest(BaseModel):
    """A wall-clock time in ``timezone``, or ``None`` to launch as soon as possible."""

    scheduled_at: datetime | None = None
    timezone: str | None = None
    on_ambiguous: str = "earliest"


class ScheduleResult(BaseModel):
    campaign: CampaignOut
    scheduled_at: datetime
    timezone: str
    #: ``unambiguous`` | ``ambiguous`` | ``nonexistent`` (SPEC.md section 5).
    resolution: str


class LaunchIssueOut(BaseModel):
    code: str
    detail: str


class LaunchValidationResult(BaseModel):
    campaign_id: uuid.UUID
    ok: bool
    issues: list[LaunchIssueOut] = Field(default_factory=list)


class LaunchResult(BaseModel):
    campaign_id: uuid.UUID
    status: str
    recipient_count: int
    snapshot_version: int | None = None


class RecipientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contact_id: uuid.UUID | None = None
    email_snapshot: str
    status: str
    attempt_count: int
    accepted_at: datetime | None = None
    outcome_at: datetime | None = None
    error_code: str | None = None
    created_at: datetime


class RecipientPage(BaseModel):
    items: list[RecipientOut]
    next_cursor: str | None = None
    total: int
