"""Scheduler entry point.

A single-active scheduler claims due campaigns and publishes outbox events. A
PostgreSQL advisory lock makes accidental duplicate scheduler instances
harmless, and ``FOR UPDATE SKIP LOCKED`` plus the outbox dedupe key means a
restart cannot lose or double-run due work (ARCHITECTURE.md section 6,
SPEC.md section 5).

The same lock also serializes the data retention jobs (SPEC.md section 8,
``app.workers.retention``): running them here rather than in an extra Compose
service keeps one owner for scheduled maintenance and means retention cannot run
twice for two schedulers.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.config import Settings, get_settings
from app.db.session import SessionFactory, engine
from app.domain.campaign.service import CampaignService
from app.errors import AppError
from app.logging import configure_logging, get_logger
from app.repositories.audit_repo import AuditRepository
from app.repositories.campaign_repo import claim_due_campaigns
from app.workers.outbox import dispatch_pending
from app.workers.retention import run_retention

logger = get_logger(__name__)

_ACQUIRE_LOCK = text("SELECT pg_try_advisory_lock(:key)")
_RELEASE_LOCK = text("SELECT pg_advisory_unlock(:key)")


async def _try_acquire(conn: AsyncConnection, key: int) -> bool:
    acquired = bool((await conn.execute(_ACQUIRE_LOCK, {"key": key})).scalar_one())
    await conn.commit()
    return acquired


async def prepare_due_campaigns(settings: Settings, *, now: datetime | None = None) -> int:
    """Prepare launches for campaigns whose scheduled time has arrived."""
    moment = now or datetime.now(UTC)
    prepared = 0
    async with SessionFactory() as session:
        due = await claim_due_campaigns(
            session, now=moment, limit=settings.campaign_due_batch_size
        )
        for campaign in due:
            service = CampaignService(session, campaign.tenant_id, settings)
            try:
                await service.launch(campaign.id)
            except AppError as exc:
                # The scheduled draft is no longer launchable; stop it retrying
                # every pass and record why (no actor: scheduler-driven).
                campaign.status = "failed"
                await AuditRepository(session, campaign.tenant_id).record(
                    action="campaign.launch_failed",
                    object_type="campaign",
                    object_id=str(campaign.id),
                    details={"reason": exc.code, **exc.extra},
                )
                logger.warning(
                    "scheduled campaign failed validation",
                    extra={"campaign_id": str(campaign.id), "reason": exc.code},
                )
            else:
                prepared += 1
        await session.commit()
    return prepared


async def run_once(settings: Settings, *, now: datetime | None = None) -> tuple[int, int]:
    """One scheduler pass: prepare due campaigns, then publish the outbox."""
    prepared = await prepare_due_campaigns(settings, now=now)
    async with SessionFactory() as session:
        published = await dispatch_pending(session, settings, now=now)
    return prepared, published


class _Stopper:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def install(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, ValueError):
                loop.add_signal_handler(sig, self._event.set)

    @property
    def stopped(self) -> bool:
        return self._event.is_set()


async def _retention_pass(settings: Settings, *, now: datetime) -> datetime:
    """Run the retention jobs and return the next due time.

    A failed pass is logged and retried at the next cadence rather than hot
    looping; the jobs are idempotent, so a delayed pass is never a data loss.
    """
    next_due = now + timedelta(seconds=settings.retention_interval_seconds)
    try:
        await run_retention(settings, now=now)
    except Exception:  # noqa: BLE001 - maintenance must not kill dispatch
        logger.exception("retention pass failed")
    return next_due


async def run(settings: Settings) -> None:
    stopper = _Stopper()
    stopper.install()
    interval = settings.campaign_scheduler_interval_seconds
    while not stopper.stopped:
        async with engine.connect() as lock_conn:
            if not await _try_acquire(lock_conn, settings.scheduler_advisory_lock_key):
                logger.info("scheduler lock held elsewhere; standing by")
                await asyncio.sleep(interval)
                continue
            logger.info("scheduler acquired lock")
            # Retention runs on startup and then on its own cadence.
            next_retention = datetime.now(UTC)
            try:
                while not stopper.stopped:
                    try:
                        prepared, published = await run_once(settings)
                        if prepared or published:
                            logger.info(
                                "scheduler pass",
                                extra={"prepared": prepared, "published": published},
                            )
                    except Exception:  # noqa: BLE001 - one bad pass must not kill the loop
                        logger.exception("scheduler pass failed")
                    moment = datetime.now(UTC)
                    if moment >= next_retention:
                        next_retention = await _retention_pass(settings, now=moment)
                    await asyncio.sleep(interval)
            finally:
                with contextlib.suppress(Exception):
                    await lock_conn.execute(
                        _RELEASE_LOCK, {"key": settings.scheduler_advisory_lock_key}
                    )
                    await lock_conn.commit()
    logger.info("scheduler stopped")


def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(settings))


if __name__ == "__main__":
    main()
