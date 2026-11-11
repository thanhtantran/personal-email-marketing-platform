"""Request/response schemas for templates and rendering."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    mjml_source: str = Field(min_length=1)
    editor_json: dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    mjml_source: str | None = None
    editor_json: dict[str, Any] | None = None
    status: str | None = None


class TemplateSummary(BaseModel):
    """List/collection view: omits the heavy rendered bodies."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    version: int
    status: str
    created_at: datetime
    updated_at: datetime


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    version: int
    status: str
    editor_json: dict[str, Any]
    mjml_source: str
    html: str
    text_body: str
    created_at: datetime
    updated_at: datetime


class TemplateRenderRequest(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


class TemplateRenderResult(BaseModel):
    template_id: uuid.UUID
    version: int
    html: str
    text: str
    missing: list[str] = Field(default_factory=list)
    used_fallback: list[str] = Field(default_factory=list)


class TemplateTestSendRequest(BaseModel):
    recipient: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=255)
    values: dict[str, str] = Field(default_factory=dict)


class TemplateTestSendResult(BaseModel):
    template_id: uuid.UUID
    version: int
    provider: str
    recipient: str
    subject: str
    digest: str
    enqueued: bool
    html: str
    text: str
    missing: list[str] = Field(default_factory=list)
    used_fallback: list[str] = Field(default_factory=list)
