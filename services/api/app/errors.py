"""RFC 7807 style problem responses with stable error codes."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base class for expected, client-facing errors."""

    status_code: int = 400
    code: str = "error"

    def __init__(self, detail: str, *, extra: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra or {}


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthenticated"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationAppError(AppError):
    status_code = 422
    code = "validation_error"


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"


class ServiceUnavailableError(AppError):
    """A dependency needed to complete the request is not available.

    Used when accepting work would be unsafe without that dependency: a webhook
    whose raw payload cannot be retained must fail closed so the provider
    retries, rather than being acknowledged and lost.
    """

    status_code = 503
    code = "service_unavailable"


def problem_response(request: Request, *, status_code: int, code: str, detail: str,
                     extra: dict[str, Any] | None = None) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"about:blank#{code}",
        "title": code,
        "status": status_code,
        "detail": detail,
        "instance": str(request.url.path),
    }
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status_code, content=body,
                        media_type="application/problem+json")


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return problem_response(request, status_code=exc.status_code, code=exc.code,
                            detail=exc.detail, extra=exc.extra)
