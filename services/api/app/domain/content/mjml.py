"""Server-side MJML rendering.

The MJML CLI (installed in the API image, see ``infra/docker/Dockerfile.api``) is
invoked over stdin/stdout. Rendering is deterministic for a fixed source and MJML
version, which is what lets a saved template be reopened and re-rendered
reproducibly (SPEC.md section 3).

``runner`` is injectable so the rendering contract can be unit-tested without a
Node.js toolchain on the test host.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable

from app.errors import ValidationAppError

DEFAULT_TIMEOUT_SECONDS = 20
_STDERR_LIMIT = 500

Runner = Callable[..., str]


class MjmlRenderError(ValidationAppError):
    """Raised when MJML rendering fails or is unavailable."""


def _default_runner(source: str, *, binary: str, timeout: int) -> str:
    if shutil.which(binary) is None:
        raise MjmlRenderError(
            "MJML renderer is not available on this server",
            extra={"reason": "mjml_unavailable", "binary": binary},
        )
    try:
        completed = subprocess.run(  # noqa: S603 - fixed binary, source passed via stdin
            [binary, "-s"],
            input=source,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MjmlRenderError(
            "MJML rendering timed out", extra={"reason": "mjml_timeout"}
        ) from exc
    except OSError as exc:
        raise MjmlRenderError(
            "MJML renderer could not be executed", extra={"reason": "mjml_exec_failed"}
        ) from exc

    if completed.returncode != 0:
        raise MjmlRenderError(
            "MJML rendering failed",
            extra={"reason": "mjml_failed", "stderr": (completed.stderr or "")[:_STDERR_LIMIT]},
        )
    output = completed.stdout or ""
    if not output.strip():
        raise MjmlRenderError(
            "MJML rendering produced no output", extra={"reason": "mjml_empty_output"}
        )
    return output


def render_mjml(
    source: str,
    *,
    binary: str = "mjml",
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    runner: Runner | None = None,
) -> str:
    """Render MJML ``source`` to HTML."""
    if not source or not source.strip():
        raise MjmlRenderError("MJML source is required", extra={"reason": "mjml_empty_source"})
    active_runner = runner or _default_runner
    return active_runner(source, binary=binary, timeout=timeout)
