"""Identity and workspace endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import TenantContext, csrf_cookie_present, get_current_context
from app.config import Settings, get_settings
from app.schemas.identity import MeOut, UserOut, WorkspaceOut

router = APIRouter(tags=["identity"])


@router.get("/me", response_model=MeOut)
async def get_me(
    request: Request,
    context: TenantContext = Depends(get_current_context),
    settings: Settings = Depends(get_settings),
) -> MeOut:
    return MeOut(
        user=UserOut.model_validate(context.user),
        workspace=WorkspaceOut.model_validate(context.tenant),
        role=context.membership.role,
        csrf_token_present=csrf_cookie_present(request, settings),
    )


@router.get("/workspace", response_model=WorkspaceOut)
async def get_workspace(
    context: TenantContext = Depends(get_current_context),
) -> WorkspaceOut:
    return WorkspaceOut.model_validate(context.tenant)
