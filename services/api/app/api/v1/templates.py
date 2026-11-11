"""Template endpoints: lifecycle, render preview and restricted test sends.

Templates are tenant-scoped and versioned. The server renders from the stored
``mjml_source`` so a reopened template reproduces its output exactly; preview and
test sends run the same pipeline and never enqueue a production campaign
(IMPLEMENTATION_PLAN Stage 3 exit gate).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TenantContext, get_current_context, verify_csrf
from app.config import Settings, get_settings
from app.db.models import Template
from app.db.session import get_db
from app.domain.content.template_service import TemplateService
from app.domain.content.test_send import (
    MockSender,
    build_test_message,
    require_verified_recipient,
)
from app.errors import NotFoundError
from app.repositories.audit_repo import AuditRepository
from app.repositories.template_repo import TemplateRepository
from app.schemas.content import (
    TemplateCreate,
    TemplateOut,
    TemplateRenderRequest,
    TemplateRenderResult,
    TemplateSummary,
    TemplateTestSendRequest,
    TemplateTestSendResult,
    TemplateUpdate,
)

router = APIRouter(tags=["templates"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


async def _load(repo: TemplateRepository, template_id: uuid.UUID) -> Template:
    template = await repo.get(template_id)
    if template is None:
        raise NotFoundError("Template not found")
    return template


@router.get("/templates", response_model=list[TemplateSummary])
async def list_templates(
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> list[TemplateSummary]:
    templates = await TemplateRepository(db, context.tenant.id).list_active()
    return [TemplateSummary.model_validate(template) for template in templates]


@router.post("/templates", response_model=TemplateOut, status_code=201)
async def create_template(
    payload: TemplateCreate,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TemplateOut:
    service = TemplateService(db, context.tenant.id, settings)
    template = await service.create(
        name=payload.name.strip(),
        editor_json=payload.editor_json,
        mjml_source=payload.mjml_source,
        status=payload.status,
    )
    await AuditRepository(db, context.tenant.id).record(
        action="template.created",
        actor_user_id=context.user.id,
        object_type="template",
        object_id=str(template.id),
        request_id=_request_id(request),
        details={"version": template.version},
    )
    await db.commit()
    return TemplateOut.model_validate(template)


@router.get("/templates/{template_id}", response_model=TemplateOut)
async def get_template(
    template_id: uuid.UUID,
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> TemplateOut:
    template = await _load(TemplateRepository(db, context.tenant.id), template_id)
    return TemplateOut.model_validate(template)


@router.patch("/templates/{template_id}", response_model=TemplateOut)
async def update_template(
    template_id: uuid.UUID,
    payload: TemplateUpdate,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TemplateOut:
    repo = TemplateRepository(db, context.tenant.id)
    template = await _load(repo, template_id)
    fields = payload.model_dump(exclude_unset=True)
    service = TemplateService(db, context.tenant.id, settings)
    template = await service.update(
        template,
        name=fields.get("name"),
        mjml_source=fields.get("mjml_source"),
        editor_json=fields.get("editor_json"),
        status=fields.get("status"),
    )
    await AuditRepository(db, context.tenant.id).record(
        action="template.updated",
        actor_user_id=context.user.id,
        object_type="template",
        object_id=str(template.id),
        request_id=_request_id(request),
        details={"version": template.version, "fields": sorted(fields)},
    )
    await db.commit()
    return TemplateOut.model_validate(template)


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: uuid.UUID,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Archive rather than hard-delete: campaigns reference template versions."""
    repo = TemplateRepository(db, context.tenant.id)
    template = await _load(repo, template_id)
    template.status = "archived"
    await db.flush()
    await AuditRepository(db, context.tenant.id).record(
        action="template.archived",
        actor_user_id=context.user.id,
        object_type="template",
        object_id=str(template.id),
        request_id=_request_id(request),
    )
    await db.commit()
    return Response(status_code=204)


@router.post("/templates/{template_id}/render", response_model=TemplateRenderResult)
async def render_template(
    template_id: uuid.UUID,
    payload: TemplateRenderRequest,
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TemplateRenderResult:
    """Render a personalized preview; nothing is persisted or sent."""
    template = await _load(TemplateRepository(db, context.tenant.id), template_id)
    outcome = TemplateService(db, context.tenant.id, settings).render(template, payload.values)
    return TemplateRenderResult(
        template_id=template.id,
        version=outcome.version,
        html=outcome.html,
        text=outcome.text,
        missing=outcome.missing,
        used_fallback=outcome.used_fallback,
    )


@router.post("/templates/{template_id}/test-send", response_model=TemplateTestSendResult)
async def test_send_template(
    template_id: uuid.UUID,
    payload: TemplateTestSendRequest,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TemplateTestSendResult:
    """Send to a verified address only; never enqueues a production campaign."""
    recipient = require_verified_recipient(payload.recipient, settings.verified_test_recipients)
    template = await _load(TemplateRepository(db, context.tenant.id), template_id)
    outcome = TemplateService(db, context.tenant.id, settings).render(template, payload.values)
    message = MockSender().send(
        build_test_message(
            recipient=recipient,
            subject=payload.subject,
            html=outcome.html,
            text=outcome.text,
        )
    )
    await AuditRepository(db, context.tenant.id).record(
        action="template.test_sent",
        actor_user_id=context.user.id,
        object_type="template",
        object_id=str(template.id),
        request_id=_request_id(request),
        details={
            "recipient": recipient,
            "provider": message.provider,
            "enqueued": message.enqueued,
        },
    )
    await db.commit()
    return TemplateTestSendResult(
        template_id=template.id,
        version=outcome.version,
        provider=message.provider,
        recipient=message.to,
        subject=message.subject,
        digest=message.digest,
        enqueued=message.enqueued,
        html=outcome.html,
        text=outcome.text,
        missing=outcome.missing,
        used_fallback=outcome.used_fallback,
    )
