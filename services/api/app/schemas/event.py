"""Schemas for webhook intake, one-click unsubscribe and campaign analytics."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class WebhookAccepted(BaseModel):
    """What a provider sees after a verified delivery is accepted.

    A duplicate is still a success from the provider's point of view: the event
    was already recorded, so acknowledging it stops the provider retrying.
    """

    accepted: bool
    duplicate: bool = False
    event_type: str = ""
    provider_event_id: str = ""


class UnsubscribeResult(BaseModel):
    unsubscribed: bool


class CampaignAnalyticsOut(BaseModel):
    """Ledger state plus provider-reported totals, with reading caveats."""

    model_config = ConfigDict(from_attributes=True)

    campaign_id: uuid.UUID
    total_recipients: int
    queued: int
    accepted: int
    failed: int
    skipped: int
    unknown: int
    delivered: int
    deferred: int
    bounced: int
    bounced_hard: int
    bounced_soft: int
    complained: int
    unsubscribed: int
    opened: int
    clicked: int
    caveats: list[str] = Field(default_factory=list)
