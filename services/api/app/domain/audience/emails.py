"""Email normalization and matching.

Contacts are matched on a normalized address while the original display value is
retained. Normalization is deterministic so imports stay idempotent.
"""

from __future__ import annotations

from email_validator import EmailNotValidError, validate_email

MAX_EMAIL_LENGTH = 320


def normalize_email(raw: str | None) -> str | None:
    """Return a canonical address, or ``None`` when the input is not a valid email.

    The domain part is lower-cased by the validator; the local part is also
    lower-cased so that case-only duplicates collapse to one contact. This is the
    documented matching rule for the platform.
    """
    if raw is None:
        return None
    candidate = raw.strip()
    if not candidate or len(candidate) > MAX_EMAIL_LENGTH:
        return None
    try:
        validated = validate_email(candidate, check_deliverability=False)
    except EmailNotValidError:
        return None
    return validated.normalized.lower()


def is_valid_email(raw: str | None) -> bool:
    return normalize_email(raw) is not None
