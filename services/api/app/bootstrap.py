"""Workspace bootstrap.

Ensures the single Phase 1 tenant exists. The owner identity is bound on first
successful Google login (see AuthService), so this is idempotent and safe to run
on every startup and as a standalone job.

Usage: ``python -m app.bootstrap``
"""

from __future__ import annotations

import asyncio

from app.config import Settings, get_settings
from app.db.session import SessionFactory, engine
from app.logging import configure_logging, get_logger
from app.repositories.tenant_repo import TenantRepository

logger = get_logger(__name__)


async def bootstrap_workspace(settings: Settings) -> None:
    try:
        async with SessionFactory() as session:
            tenants = TenantRepository(session)
            tenant = await tenants.get_by_slug(settings.tenant_slug)
            if tenant is None:
                tenant = await tenants.create(
                    slug=settings.tenant_slug, name=settings.tenant_name
                )
                await session.commit()
                logger.info(
                    "created workspace tenant",
                    extra={"tenant_id": str(tenant.id), "slug": tenant.slug},
                )
            else:
                logger.info(
                    "workspace tenant present",
                    extra={"tenant_id": str(tenant.id), "slug": tenant.slug},
                )
    except Exception:
        logger.exception("workspace bootstrap failed; readiness will report unhealthy")

    if not settings.owner_configured:
        logger.warning(
            "no workspace owner configured; set OWNER_GOOGLE_SUB or OWNER_EMAIL before deployment"
        )


async def _main() -> None:
    settings = get_settings()
    configure_logging(settings)
    problems = settings.require_production_safety()
    if problems:
        for problem in problems:
            logger.error("configuration problem", extra={"problem": problem})
        raise SystemExit(1)
    await bootstrap_workspace(settings)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
