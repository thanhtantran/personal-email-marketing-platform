"""Import orchestration: staged upload, preview and idempotent commit.

Preview and commit share the same planning functions, so the counts an operator
approves are the outcomes that get applied. Commit is written to be safely
replayable: contacts are matched on the normalized address, existing import rows
are replaced, and a completed import returns its stored result unchanged
(SPEC.md exit gate for Stage 2).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.db.models import ImportJob, ImportRow
from app.domain.audience.imports import (
    MERGE_POLICIES,
    OUTCOME_ACCEPTED,
    OUTCOME_DUPLICATE,
    ContactState,
    ImportMapping,
    ImportPlan,
    RowPlan,
    parse_and_plan,
    plan_merge_actions,
    reclassify_duplicates,
)
from app.errors import ConflictError, NotFoundError, ValidationAppError
from app.logging import get_logger
from app.repositories.contact_repo import ContactRepository
from app.repositories.import_repo import ImportRepository
from app.repositories.suppression_repo import SuppressionRepository
from app.storage.base import ObjectStorage

logger = get_logger(__name__)

UPLOAD_URL_TTL_SECONDS = 900


def object_key_for(tenant_id: uuid.UUID, import_id: uuid.UUID) -> str:
    return f"imports/{tenant_id}/{import_id}.csv"


class ImportService:
    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        storage: ObjectStorage,
        settings: Settings,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.storage = storage
        self.settings = settings
        self.imports = ImportRepository(session, tenant_id)
        self.contacts = ContactRepository(session, tenant_id)
        self.suppressions = SuppressionRepository(session, tenant_id)

    async def create(
        self,
        *,
        mapping: dict,
        created_by: uuid.UUID | None,
        idempotency_key: str | None,
    ) -> tuple[ImportJob, str]:
        ImportMapping.parse(mapping)
        if idempotency_key:
            existing = await self.imports.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                if existing.mapping != mapping:
                    raise ConflictError(
                        "Idempotency key already used with a different request",
                        extra={"reason": "idempotency_conflict"},
                    )
                return existing, self._upload_url(existing)

        import_id = uuid.uuid4()
        job = ImportJob(
            id=import_id,
            tenant_id=self.tenant_id,
            uploaded_object_key=object_key_for(self.tenant_id, import_id),
            mapping=mapping,
            status="awaiting_upload",
            idempotency_key=idempotency_key,
            created_by=created_by,
        )
        self.session.add(job)
        await self.session.commit()
        logger.info("import created", extra={"import_id": str(job.id)})
        return job, self._upload_url(job)

    def _upload_url(self, job: ImportJob) -> str:
        assert job.uploaded_object_key is not None
        return self.storage.presign_put(
            job.uploaded_object_key, expires_seconds=UPLOAD_URL_TTL_SECONDS
        )

    async def get(self, import_id: uuid.UUID) -> ImportJob:
        job = await self.imports.get(import_id)
        if job is None:
            raise NotFoundError("Import not found")
        return job

    async def _load_plan(self, job: ImportJob) -> ImportPlan:
        if not job.uploaded_object_key or not job.mapping:
            raise ValidationAppError("Import has no staged upload", extra={"reason": "no_upload"})
        info = await run_in_threadpool(self.storage.head, job.uploaded_object_key)
        if info is None:
            raise ValidationAppError(
                "Staged upload was not found", extra={"reason": "upload_not_found"}
            )
        max_bytes = self.settings.import_max_file_mb * 1024 * 1024
        if info.size > max_bytes:
            raise ValidationAppError(
                "Uploaded file exceeds the size limit",
                extra={"reason": "file_too_large", "limit_mb": self.settings.import_max_file_mb},
            )
        content = await run_in_threadpool(self.storage.get_bytes, job.uploaded_object_key)

        mapping = ImportMapping.parse(job.mapping)
        plan = parse_and_plan(
            content,
            mapping,
            max_rows=self.settings.import_max_rows,
            max_columns=self.settings.import_max_columns,
            max_field_length=self.settings.import_max_field_length,
        )
        existing = await self.contacts.existing_emails(
            row.normalized_email for row in plan.rows if row.normalized_email
        )
        return reclassify_duplicates(plan, existing)

    async def preview(self, import_id: uuid.UUID) -> tuple[ImportJob, ImportPlan]:
        job = await self.get(import_id)
        if job.status == "completed":
            raise ConflictError(
                "Import is already committed", extra={"reason": "already_completed"}
            )
        plan = await self._load_plan(job)
        job.status = "preview_ready"
        job.counts = plan.counts
        job.started_at = datetime.now(UTC)
        await self.session.commit()
        return job, plan

    async def commit(
        self, import_id: uuid.UUID, *, merge_policy: str
    ) -> tuple[ImportJob, ImportPlan | None]:
        if merge_policy not in MERGE_POLICIES:
            raise ValidationAppError(
                "Unsupported merge policy", extra={"reason": "invalid_merge_policy"}
            )
        job = await self.get(import_id)
        if job.status == "completed":
            return job, None
        if job.status != "preview_ready":
            raise ConflictError("Import is not ready to commit", extra={"reason": "invalid_state"})

        plan = await self._load_plan(job)
        job.status = "committing"
        await self.session.flush()
        await self.imports.delete_rows(job.id)

        rows: list[ImportRow] = []
        for row in plan.rows:
            contact_id: uuid.UUID | None = None
            if row.outcome == OUTCOME_ACCEPTED and row.normalized_email:
                contact_id = await self._create_contact(row)
            elif row.outcome == OUTCOME_DUPLICATE and row.normalized_email:
                contact_id = await self._apply_merge(row, merge_policy)
            rows.append(
                ImportRow(
                    tenant_id=self.tenant_id,
                    import_id=job.id,
                    row_number=row.row_number,
                    outcome=row.outcome,
                    error_code=row.error_code,
                    contact_id=contact_id,
                    row_digest=row.row_digest,
                )
            )
        await self.imports.add_rows(rows)

        job.status = "completed"
        job.counts = plan.counts
        job.completed_at = datetime.now(UTC)
        await self.session.commit()
        logger.info(
            "import committed",
            extra={
                "import_id": str(job.id),
                "merge_policy": merge_policy,
                "accepted": plan.counts.get(OUTCOME_ACCEPTED, 0),
                "duplicate": plan.counts.get(OUTCOME_DUPLICATE, 0),
            },
        )
        if job.uploaded_object_key:
            await run_in_threadpool(self.storage.delete, job.uploaded_object_key)
        return job, plan

    async def _create_contact(self, row: RowPlan) -> uuid.UUID:
        assert row.normalized_email
        suppressed = await self.suppressions.exists(row.normalized_email)
        contact = await self.contacts.create(
            normalized_email=row.normalized_email,
            email_display=row.email_display or row.normalized_email,
            status="suppressed" if suppressed else "active",
            consent_status=row.consent_status,
            consent_at=row.consent_at,
            consent_source=row.consent_source,
            consent_evidence_ref=row.consent_evidence_ref,
            attributes=row.attributes,
        )
        return contact.id

    async def _apply_merge(self, row: RowPlan, merge_policy: str) -> uuid.UUID | None:
        assert row.normalized_email
        contact = await self.contacts.get_by_email(row.normalized_email)
        if contact is None:
            return None
        suppressed = await self.suppressions.exists(row.normalized_email)
        fields = plan_merge_actions(
            ContactState(
                status=contact.status,
                consent_status=contact.consent_status,
                attributes=dict(contact.attributes or {}),
            ),
            row,
            merge_policy,
            suppressed=suppressed,
        )
        if fields:
            await self.contacts.apply_fields(contact, fields)
        return contact.id
