"""Request/response schemas for identity and workspace."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None = None
    status: str


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    status: str


class MeOut(BaseModel):
    user: UserOut
    workspace: WorkspaceOut
    role: str
    csrf_token_present: bool


class HealthDependency(BaseModel):
    name: str
    healthy: bool
    detail: str | None = None


class ReadinessOut(BaseModel):
    status: str
    environment: str
    dependencies: list[HealthDependency]
