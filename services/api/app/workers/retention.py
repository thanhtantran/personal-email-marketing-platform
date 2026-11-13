"""Data retention jobs.

Retention is a privacy control, not housekeeping (SPEC.md section 8, docs/data-
classification.md): raw provider payloads, staged CSV uploads and per-row import
outcomes are TTL-bound, while the durable facts an operator actually needs -- the
webhook payload digest, the import summary counts, the campaign ledger -- are
kept. Nothing here deletes an audit or accounting fact.

Ordering rule: an object-storage artifact is deleted *before* the database
reference that points at it is cleared. A crash in between leaves a row that
still claims to own an object (retried by the next pass) rather than a dangling
reference or an orphaned copy of recipient data.

Every job is bounded by ``BATCH_LIMIT`` per pass and idempotent, so it is safe to
run from the scheduler on a cadence, from a cron entry point, or by hand.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import ImportJob, ImportRow, WebhookEvent
from app.db.session import SessionFactory
from app.logging import configure_logging, get_logger
from app.observability.metrics import RETENTION_DELETED
from app.storage.base import ObjectStorage
from app.storage.s3 import get_storage

logger = get_logger(__name__)

#: Rows/objects handled per job per pass, so one retention run cannot hold a long
#: transaction or delete an unbounded amount in a single statement.
BATCH_LIMIT = 500

#: Import states in which the staged object may still be read for an in-flight
#: commit; those are never removed by the retention job.
IMPORT_STATUS_COMMITTING = "committing"


def retention_cutoff(now: datetime, *, days: int) -> datetime:
    """Everything strictly older than this instant is out of the window."""
    return now - timedelta(days=days)


def is_expired(created_at: datetime, *, now: datetime, days: int) -> bool:
    """Whether a row created at ``created_at`` has left the retention window."""
    moment = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)
    return moment < retention_cutoff(now, days=days)


@dataclass
class RetentionReport:
    """What one retention pass removed, for the log and the metrics."""

    raw_webhook_payloads: int = 0
    staged_uploads: int = 0
    import_rows: int = 0
    failures: int = 0

    def summary(self) -> dict[str, int]:
        return {
            "raw_webhook_payloads": self.raw_webhook_payloads,
            "staged_uploads": self.staged_uploads,
            "import_rows": self.import_rows,
            "failures": self.failures,
        }


async def purge_raw_webhook_payloads(
    session: AsyncSession,
    settings: Settings,
    *,
    storage: ObjectStorage,
    now: datetime,
    limit: int = BATCH_LIMIT,
) -> tuple[int, int]:
    """Drop retained raw webhook bodies, keeping the digest and the row.

    The row is the replay defence and the operator's evidence that a delivery was
    received, so it stays; only the raw body (which contains recipient PII) is
    removed once it is older than ``RAW_WEBHOOK_RETENTION_DAYS``.
    """
    cutoff = retention_cutoff(now, days=settings.raw_webhook_retention_days)
    result = await session.execute(
        select(WebhookEvent)
        .where(WebhookEvent.payload_object_key.is_not(None), WebhookEvent.created_at < cutoff)
        .order_by(WebhookEvent.created_at)
        .limit(limit)
    )
    removed = failures = 0
    for event in result.scalars().all():
        key = event.payload_object_key
        if key is None:  # pragma: no cover - guarded by the query
            continue
        try:
            await asyncio.to_thread(storage.delete, key)
        except Exception:  # noqa: BLE001 - leave the key so the next pass retries
            failures += 1
            logger.warning(
                "raw payload retention failed", extra={"webhook_event_id": str(event.id)}
            )
            continue
        event.payload_object_key = None
        removed += 1
    await session.flush()
    return removed, failures


async def purge_staged_uploads(
    session: AsyncSession,
    settings: Settings,
    *,
    storage: ObjectStorage,
    now: datetime,
    limit: int = BATCH_LIMIT,
) -> tuple[int, int]:
    """Delete staged CSV objects past the window; the import summary is kept."""
    cutoff = retention_cutoff(now, days=settings.staged_upload_retention_days)
    result = await session.execute(
        select(ImportJob)
        .where(
            ImportJob.uploaded_object_key.is_not(None),
            ImportJob.created_at < cutoff,
            ImportJob.status != IMPORT_STATUS_COMMITTING,
        )
        .order_by(ImportJob.created_at)
        .limit(limit)
    )
    removed = failures = 0
    for job in result.scalars().all():
        key = job.uploaded_object_key
        if key is None:  # pragma: no cover - guarded by the query
            continue
        try:
            await asyncio.to_thread(storage.delete, key)
        except Exception:  # noqa: BLE001 - leave the key so the next pass retries
            failures += 1
            logger.warning("staged upload retention failed", extra={"import_id": str(job.id)})
            continue
        job.uploaded_object_key = None
        removed += 1
    await session.flush()
    return removed, failures


async def purge_import_rows(
    session: AsyncSession,
    settings: Settings,
    *,
    now: datetime,
    limit: int = BATCH_LIMIT,
) -> int:
    """Delete per-row import outcomes past the window.

    Contacts already committed from the CSV are unaffected: rows are provenance,
    not the data itself (SPEC.md section 3).
    """
    cutoff = retention_cutoff(now, days=settings.import_row_retention_days)
    result = await session.execute(
        delete(ImportRow).where(
            ImportRow.id.in_(
                select(ImportRow.id)
                .where(ImportRow.created_at < cutoff)
                .order_by(ImportRow.created_at)
                .limit(limit)
                .scalar_subquery()
            )
        )
    )
    return int(result.rowcount or 0)


async def run_retention(
    settings: Settings,
    *,
    now: datetime | None = None,
    storage: ObjectStorage | None = None,
) -> RetentionReport:
    """Run every retention job once and report what was removed."""
    moment = now or datetime.now(UTC)
    objects = storage or get_storage()
    report = RetentionReport()

    async with SessionFactory() as session:
        removed, failures = await purge_raw_webhook_payloads(
            session, settings, storage=objects, now=moment
        )
        await session.commit()
        report.raw_webhook_payloads += removed
        report.failures += failures

        removed, failures = await purge_staged_uploads(
            session, settings, storage=objects, now=moment
        )
        await session.commit()
        report.staged_uploads += removed
        report.failures += failures

        report.import_rows = await purge_import_rows(session, settings, now=moment)
        await session.commit()

    RETENTION_DELETED.inc(report.raw_webhook_payloads, dataset="raw_webhook")
    RETENTION_DELETED.inc(report.staged_uploads, dataset="staged_upload")
    RETENTION_DELETED.inc(report.import_rows, dataset="import_row")
    logger.info("retention pass", extra=report.summary())
    return report


async def main() -> None:
    """Standalone entry point for a cron-driven deployment."""
    settings = get_settings()
    configure_logging(settings)
    await run_retention(settings)


if __name__ == "__main__":
    asyncio.run(main())
