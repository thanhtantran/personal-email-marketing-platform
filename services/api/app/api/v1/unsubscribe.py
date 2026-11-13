"""Public one-click unsubscribe.

``GET`` renders a confirmation page instead of unsubscribing, because mailbox
scanners and link prefetchers issue GET requests on a recipient's behalf; the
actual state change happens on ``POST``, which is what the ``List-Unsubscribe``
one-click header targets. The token is signed and carries no email address, so a
leaked URL discloses nothing and cannot be edited to target another recipient
(SPEC.md section 8).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.domain.events.unsubscribe import (
    record_unsubscribe,
    verify_unsubscribe_token,
)
from app.errors import ValidationAppError
from app.schemas.event import UnsubscribeResult
from app.security.signing import SignatureError

router = APIRouter(tags=["unsubscribe"])

_CONFIRM_PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="robots" content="noindex" />
    <title>Unsubscribe</title>
  </head>
  <body>
    <main style="font-family: system-ui, sans-serif; max-width: 32rem; margin: 4rem auto;">
      <h1>Unsubscribe</h1>
      <p>Confirm that you no longer want to receive marketing email from this sender.</p>
      <form method="post">
        <button type="submit">Unsubscribe me</button>
      </form>
    </main>
  </body>
</html>
"""


def _secret(settings: Settings) -> str:
    return settings.session_key


def _target_or_error(settings: Settings, token: str):
    try:
        return verify_unsubscribe_token(_secret(settings), token)
    except SignatureError as exc:
        raise ValidationAppError(
            "This unsubscribe link is invalid or has expired",
            extra={"reason": "invalid_unsubscribe_token"},
        ) from exc


@router.get("/unsubscribe/{token}", response_class=HTMLResponse)
async def show_unsubscribe(
    token: str, settings: Settings = Depends(get_settings)
) -> HTMLResponse:
    _target_or_error(settings, token)
    return HTMLResponse(_CONFIRM_PAGE)


@router.post("/unsubscribe/{token}", response_model=UnsubscribeResult)
async def one_click_unsubscribe(
    token: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UnsubscribeResult:
    target = _target_or_error(settings, token)
    outcome = await record_unsubscribe(db, target, occurred_at=datetime.now(UTC))
    await db.commit()
    return UnsubscribeResult(unsubscribed=outcome.suppression_recorded)
