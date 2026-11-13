"""Request/response schemas for provider accounts, credentials and routing.

A credential secret is accepted on write and **never** echoed: no schema here has
a field for credential ciphertext or plaintext (SPEC.md section 4).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProviderAccountCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    external_account_ref: str = Field(min_length=1, max_length=255)
    display_name: str = Field(default="", max_length=255)
    eligible_message_classes: list[str] = Field(default_factory=list)
    sender_domains: list[str] = Field(default_factory=list)
    routing_priority: int | None = None
    routing_weight: int | None = None
    #: Write-only. Stored as an AES-256-GCM envelope and never returned.
    secret: str = Field(min_length=1, max_length=4096)
    secret_label: str = Field(default="", max_length=128)


class ProviderAccountUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    status: str | None = None
    eligible_message_classes: list[str] | None = None
    sender_domains: list[str] | None = None
    routing_priority: int | None = None
    routing_weight: int | None = None


class CredentialCreate(BaseModel):
    secret: str = Field(min_length=1, max_length=4096)
    label: str = Field(default="", max_length=128)


class CredentialOut(BaseModel):
    """Credential metadata only; the secret itself is never serialized."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    key_version: int
    status: str
    created_at: datetime
    rotated_at: datetime | None = None


class ProviderAccountOut(BaseModel):
    """Operator-visible account state: dates, declared classes and known capacity."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    external_account_ref: str
    display_name: str
    status: str
    eligible_message_classes: list[str]
    sender_domains: list[str]
    limits: dict
    quota_state: dict
    health_state: str
    eligibility_verified_at: datetime | None = None
    quota_refreshed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProviderAccountDetail(ProviderAccountOut):
    credentials: list[CredentialOut] = Field(default_factory=list)


class ProviderAccountPage(BaseModel):
    items: list[ProviderAccountOut]
    next_cursor: str | None = None
    total: int


class VerificationOut(BaseModel):
    valid: bool
    health_state: str
    eligible_message_classes: list[str]
    sender_domains: list[str]
    #: ``adapter`` when the facts came from the provider, otherwise operator state.
    observed_by: str
    detail: str | None = None


class VerifyResult(BaseModel):
    account: ProviderAccountOut
    verification: VerificationOut


class CapacityOut(BaseModel):
    observed_at: datetime
    source: str
    daily_limit: int | None = None
    daily_used: int | None = None
    monthly_limit: int | None = None
    monthly_used: int | None = None
    rate_per_second: int | None = None
    notes: str | None = None


class CapacityRefreshResult(BaseModel):
    account: ProviderAccountOut
    capacity: CapacityOut


class RoutingExclusionOut(BaseModel):
    account_id: str
    provider: str
    reason: str
    detail: str | None = None


class RoutingStatusOut(BaseModel):
    """Why marketing traffic can or cannot route right now (SPEC.md section 6)."""

    marketing_paused: bool
    paused_reason: str | None = None
    marketing_eligible: bool
    capacity_fresh: bool
    exclusions: list[RoutingExclusionOut] = Field(default_factory=list)


class RoutingControlRequest(BaseModel):
    paused: bool
    reason: str | None = Field(default=None, max_length=255)
