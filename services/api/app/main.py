"""FastAPI application entry point.

Wires structured logging, request-id correlation, restrictive CORS, RFC 7807
error handling, liveness/readiness probes and the v1 API (OAuth, sessions,
identity, workspace).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.router import api_router
from app.api.v1.unsubscribe import router as unsubscribe_router
from app.api.v1.webhooks import router as webhooks_router
from app.bootstrap import bootstrap_workspace
from app.config import get_settings
from app.db.session import SessionFactory, engine
from app.errors import AppError, app_error_handler, problem_response
from app.logging import configure_logging, get_logger
from app.middleware import RequestIDMiddleware
from app.redis_client import get_redis
from app.schemas.identity import HealthDependency, ReadinessOut

settings = get_settings()
configure_logging(settings)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    problems = settings.require_production_safety()
    if problems:
        for problem in problems:
            logger.error("configuration problem", extra={"problem": problem})
        raise RuntimeError(
            "Refusing to start with insecure or incomplete production configuration: "
            + "; ".join(problems)
        )
    await bootstrap_workspace(settings)
    logger.info("api started", extra={"env": settings.app_env})
    try:
        yield
    finally:
        await engine.dispose()
        logger.info("api stopped")


app = FastAPI(
    title="Personal Email Marketing Platform API",
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_base_url],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID", "Idempotency-Key"],
)

app.add_exception_handler(AppError, app_error_handler)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return problem_response(
        request,
        status_code=422,
        code="validation_error",
        detail="Request validation failed",
        extra={"errors": exc.errors()},
    )


@app.get("/healthz", tags=["ops"])
async def healthz() -> dict[str, str]:
    """Liveness probe: the process is running."""
    return {"status": "ok"}


@app.get("/readyz", response_model=ReadinessOut, tags=["ops"])
async def readyz() -> JSONResponse:
    """Readiness probe: reports PostgreSQL and Redis connectivity accurately."""
    dependencies: list[HealthDependency] = []

    db_ok = True
    try:
        async with SessionFactory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - surfaced as readiness detail
        db_ok = False
        dependencies.append(
            HealthDependency(name="postgres", healthy=False, detail=type(exc).__name__)
        )
    else:
        dependencies.append(HealthDependency(name="postgres", healthy=True))

    redis_ok = True
    try:
        await get_redis().ping()
    except Exception as exc:  # noqa: BLE001 - surfaced as readiness detail
        redis_ok = False
        dependencies.append(
            HealthDependency(name="redis", healthy=False, detail=type(exc).__name__)
        )
    else:
        dependencies.append(HealthDependency(name="redis", healthy=True))

    healthy = db_ok and redis_ok
    payload = ReadinessOut(
        status="ok" if healthy else "unavailable",
        environment=settings.app_env,
        dependencies=dependencies,
    )
    return JSONResponse(
        status_code=200 if healthy else 503,
        content=payload.model_dump(mode="json"),
    )


app.include_router(api_router)
# Public, unauthenticated endpoints addressed by signed/opaque handles: provider
# webhooks are verified by signature and one-click unsubscribe by signed token,
# so neither can piggyback on a session (SPEC.md sections 4 and 8).
app.include_router(webhooks_router)
app.include_router(unsubscribe_router)
