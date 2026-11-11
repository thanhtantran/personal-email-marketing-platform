"""Audience endpoints: contacts, tags, suppressions and CSV export.

Every handler resolves the workspace from the server-side session
(``get_current_context``) and passes ``tenant_id`` explicitly to tenant-scoped
repositories, so a request can never reach another workspace's rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import TenantContext, get_current_context, verify_csrf
from app.db.models import Contact
from app.db.session import get_db
from app.domain.audience.consent import (
    CONSENT_STATUSES,
    CONTACT_STATUSES,
    SUPPRESSION_REASONS,
    status_for_suppression_reason,
)
from app.domain.audience.emails import normalize_email
from app.domain.audience.export import render_csv
from app.domain.pagination import decode_cursor, encode_cursor
from app.errors import ConflictError, NotFoundError, ValidationAppError
from app.repositories.audit_repo import AuditRepository
from app.repositories.contact_repo import ContactRepository, TagRepository
from app.repositories.suppression_repo import SuppressionRepository
from app.schemas.audience import (
    ContactCreate,
    ContactOut,
    ContactPage,
    ContactUpdate,
    SuppressionCreate,
    SuppressionOut,
    TagCreate,
    TagOut,
)

router = APIRouter(tags=["audience"])

EXPORT_MAX_ROWS = 100_000
EXPORT_PAGE_SIZE = 1000


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _contact_out(contact: Contact, tags: list) -> ContactOut:
    payload = ContactOut.model_validate(contact)
    payload.tags = [TagOut.model_validate(tag) for tag in tags]
    return payload


def _validate_status(status: str, allowed: tuple[str, ...], field: str) -> None:
    if status not in allowed:
        raise ValidationAppError(
            f"Unsupported {field}", extra={"reason": f"invalid_{field}", "allowed": list(allowed)}
        )


@router.get("/contacts", response_model=ContactPage)
async def list_contacts(
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = None,
    consent_status: str | None = None,
    tag_id: uuid.UUID | None = None,
    search: str | None = None,
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> ContactPage:
    contacts = ContactRepository(db, context.tenant.id)
    tags = TagRepository(db, context.tenant.id)
    rows = await contacts.list_page(
        limit=limit,
        cursor=decode_cursor(cursor),
        status=status,
        consent_status=consent_status,
        tag_id=tag_id,
        search=search,
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = (
        encode_cursor(items[-1].created_at, items[-1].id) if has_more and items else None
    )
    output = [_contact_out(contact, await tags.tags_for_contact(contact.id)) for contact in items]
    return ContactPage(items=output, next_cursor=next_cursor, total=await contacts.count())


@router.get("/contacts/export")
async def export_contacts(
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export contacts as CSV with spreadsheet-formula escaping."""
    contacts = ContactRepository(db, context.tenant.id)
    tags = TagRepository(db, context.tenant.id)
    columns = [
        "normalized_email",
        "email_display",
        "status",
        "consent_status",
        "consent_at",
        "consent_source",
        "consent_evidence_ref",
        "tags",
        "created_at",
    ]
    rows: list[dict[str, object]] = []
    cursor: tuple[datetime, uuid.UUID] | None = None
    while len(rows) < EXPORT_MAX_ROWS:
        page = await contacts.list_page(limit=EXPORT_PAGE_SIZE, cursor=cursor)
        if not page:
            break
        for contact in page:
            contact_tags = await tags.tags_for_contact(contact.id)
            rows.append(
                {
                    "normalized_email": contact.normalized_email,
                    "email_display": contact.email_display,
                    "status": contact.status,
                    "consent_status": contact.consent_status,
                    "consent_at": contact.consent_at.isoformat() if contact.consent_at else "",
                    "consent_source": contact.consent_source or "",
                    "consent_evidence_ref": contact.consent_evidence_ref or "",
                    "tags": ", ".join(tag.name for tag in contact_tags),
                    "created_at": contact.created_at.isoformat(),
                }
            )
        if len(page) < EXPORT_PAGE_SIZE:
            break
        last = page[-1]
        cursor = (last.created_at, last.id)
    body = render_csv(columns, rows)
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="contacts.csv"'},
    )


@router.post("/contacts", response_model=ContactOut, status_code=201)
async def create_contact(
    payload: ContactCreate,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
) -> ContactOut:
    _validate_status(payload.status, CONTACT_STATUSES, "status")
    _validate_status(payload.consent_status, CONSENT_STATUSES, "consent_status")
    normalized = normalize_email(payload.email)
    if normalized is None:
        raise ValidationAppError("Invalid email address", extra={"reason": "invalid_email"})

    contacts = ContactRepository(db, context.tenant.id)
    if await contacts.get_by_email(normalized) is not None:
        raise ConflictError("Contact already exists", extra={"reason": "duplicate_email"})

    contact = await contacts.create(
        normalized_email=normalized,
        email_display=payload.email.strip(),
        status=payload.status,
        consent_status=payload.consent_status,
        consent_at=payload.consent_at,
        consent_source=payload.consent_source,
        consent_evidence_ref=payload.consent_evidence_ref,
        attributes=payload.attributes,
    )
    tags = TagRepository(db, context.tenant.id)
    for tag_id in payload.tag_ids:
        if await tags.get(tag_id) is None:
            raise NotFoundError("Tag not found", extra={"reason": "tag_not_found"})
        await tags.attach(contact.id, tag_id)
    await AuditRepository(db, context.tenant.id).record(
        action="contact.created",
        actor_user_id=context.user.id,
        object_type="contact",
        object_id=str(contact.id),
        request_id=_request_id(request),
    )
    await db.commit()
    return _contact_out(contact, await tags.tags_for_contact(contact.id))


@router.get("/contacts/{contact_id}", response_model=ContactOut)
async def get_contact(
    contact_id: uuid.UUID,
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> ContactOut:
    contacts = ContactRepository(db, context.tenant.id)
    contact = await contacts.get(contact_id)
    if contact is None:
        raise NotFoundError("Contact not found")
    tags = TagRepository(db, context.tenant.id)
    return _contact_out(contact, await tags.tags_for_contact(contact.id))


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
async def update_contact(
    contact_id: uuid.UUID,
    payload: ContactUpdate,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
) -> ContactOut:
    contacts = ContactRepository(db, context.tenant.id)
    contact = await contacts.get(contact_id)
    if contact is None:
        raise NotFoundError("Contact not found")

    fields = payload.model_dump(exclude_unset=True)
    if "status" in fields:
        _validate_status(fields["status"], CONTACT_STATUSES, "status")
    if "consent_status" in fields:
        _validate_status(fields["consent_status"], CONSENT_STATUSES, "consent_status")
    if fields:
        await contacts.apply_fields(contact, fields)
    await AuditRepository(db, context.tenant.id).record(
        action="contact.updated",
        actor_user_id=context.user.id,
        object_type="contact",
        object_id=str(contact.id),
        request_id=_request_id(request),
        details={"fields": sorted(fields)},
    )
    await db.commit()
    tags = TagRepository(db, context.tenant.id)
    return _contact_out(contact, await tags.tags_for_contact(contact.id))


@router.delete("/contacts/{contact_id}", status_code=204)
async def delete_contact(
    contact_id: uuid.UUID,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
) -> Response:
    contacts = ContactRepository(db, context.tenant.id)
    contact = await contacts.get(contact_id)
    if contact is None:
        raise NotFoundError("Contact not found")
    await contacts.soft_delete(contact)
    await AuditRepository(db, context.tenant.id).record(
        action="contact.deleted",
        actor_user_id=context.user.id,
        object_type="contact",
        object_id=str(contact.id),
        request_id=_request_id(request),
    )
    await db.commit()
    return Response(status_code=204)


@router.post("/contacts/{contact_id}/suppress", response_model=SuppressionOut, status_code=201)
async def suppress_contact(
    contact_id: uuid.UUID,
    payload: SuppressionCreate,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
) -> SuppressionOut:
    if payload.reason not in SUPPRESSION_REASONS:
        raise ValidationAppError(
            "Unsupported suppression reason",
            extra={"reason": "invalid_suppression_reason", "allowed": list(SUPPRESSION_REASONS)},
        )
    contacts = ContactRepository(db, context.tenant.id)
    contact = await contacts.get(contact_id)
    if contact is None:
        raise NotFoundError("Contact not found")

    suppressions = SuppressionRepository(db, context.tenant.id)
    record = await suppressions.upsert(
        normalized_email=contact.normalized_email,
        reason=payload.reason,
        source=payload.source,
        occurred_at=payload.occurred_at or datetime.now(UTC),
        evidence=payload.evidence,
    )
    mirrored = status_for_suppression_reason(payload.reason)
    if mirrored and contact.status != mirrored:
        await contacts.apply_fields(contact, {"status": mirrored})
    await AuditRepository(db, context.tenant.id).record(
        action="suppression.created",
        actor_user_id=context.user.id,
        object_type="contact",
        object_id=str(contact.id),
        request_id=_request_id(request),
        details={"reason": payload.reason},
    )
    await db.commit()
    return SuppressionOut.model_validate(record)


@router.get("/tags", response_model=list[TagOut])
async def list_tags(
    context: TenantContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> list[TagOut]:
    tags = await TagRepository(db, context.tenant.id).list_all()
    return [TagOut.model_validate(tag) for tag in tags]


@router.post("/tags", response_model=TagOut, status_code=201)
async def create_tag(
    payload: TagCreate,
    request: Request,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
) -> TagOut:
    if not payload.name.strip():
        raise ValidationAppError("Tag name is required", extra={"reason": "invalid_tag_name"})
    tags = TagRepository(db, context.tenant.id)
    tag = await tags.get_or_create(payload.name)
    await AuditRepository(db, context.tenant.id).record(
        action="tag.created",
        actor_user_id=context.user.id,
        object_type="tag",
        object_id=str(tag.id),
        request_id=_request_id(request),
    )
    await db.commit()
    return TagOut.model_validate(tag)


@router.put("/contacts/{contact_id}/tags/{tag_id}", status_code=204)
async def attach_tag(
    contact_id: uuid.UUID,
    tag_id: uuid.UUID,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
) -> Response:
    contacts = ContactRepository(db, context.tenant.id)
    tags = TagRepository(db, context.tenant.id)
    if await contacts.get(contact_id) is None:
        raise NotFoundError("Contact not found")
    if await tags.get(tag_id) is None:
        raise NotFoundError("Tag not found", extra={"reason": "tag_not_found"})
    await tags.attach(contact_id, tag_id)
    await db.commit()
    return Response(status_code=204)


@router.delete("/contacts/{contact_id}/tags/{tag_id}", status_code=204)
async def detach_tag(
    contact_id: uuid.UUID,
    tag_id: uuid.UUID,
    context: TenantContext = Depends(get_current_context),
    _csrf: None = Depends(verify_csrf),
    db: AsyncSession = Depends(get_db),
) -> Response:
    contacts = ContactRepository(db, context.tenant.id)
    if await contacts.get(contact_id) is None:
        raise NotFoundError("Contact not found")
    await TagRepository(db, context.tenant.id).detach(contact_id, tag_id)
    await db.commit()
    return Response(status_code=204)
