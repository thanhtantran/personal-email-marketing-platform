"""UTC scheduling with explicit daylight-saving handling.

``scheduled_at`` is always stored in UTC alongside the operator's original
timezone. A local wall-clock time that a DST transition makes ambiguous (occurs
twice) or nonexistent (falls in a spring-forward gap) is resolved by a named,
recorded policy rather than an implicit ``fold``, so a schedule is reproducible
and auditable (SPEC.md section 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.errors import ValidationAppError

AMBIGUOUS_EARLIEST = "earliest"
AMBIGUOUS_LATEST = "latest"
AMBIGUOUS_POLICIES: tuple[str, ...] = (AMBIGUOUS_EARLIEST, AMBIGUOUS_LATEST)

RESOLUTION_UNAMBIGUOUS = "unambiguous"
RESOLUTION_AMBIGUOUS = "ambiguous"
RESOLUTION_NONEXISTENT = "nonexistent"


@dataclass(frozen=True)
class ResolvedSchedule:
    """A resolved schedule: the UTC instant plus how it was derived."""

    scheduled_at: datetime
    timezone: str
    local_time: datetime
    resolution: str

    @property
    def adjusted(self) -> bool:
        return self.resolution != RESOLUTION_UNAMBIGUOUS


def load_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationAppError(
            "Unknown timezone", extra={"reason": "invalid_timezone", "timezone": name}
        ) from exc


def normalize_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime; a naive value is assumed to already be UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _classify(local: datetime, tz: ZoneInfo) -> str:
    earlier = local.replace(tzinfo=tz, fold=0)
    later = local.replace(tzinfo=tz, fold=1)
    if earlier.utcoffset() == later.utcoffset():
        return RESOLUTION_UNAMBIGUOUS
    # Offsets differ: the wall time either occurs twice (ambiguous) or not at
    # all (nonexistent, inside a spring-forward gap). A round trip through UTC
    # preserves the wall clock only for a genuinely ambiguous time.
    round_trip = earlier.astimezone(UTC).astimezone(tz).replace(tzinfo=None)
    if round_trip == local:
        return RESOLUTION_AMBIGUOUS
    return RESOLUTION_NONEXISTENT


def resolve_schedule(
    local_time: datetime,
    timezone_name: str,
    *,
    on_ambiguous: str = AMBIGUOUS_EARLIEST,
) -> ResolvedSchedule:
    """Resolve a wall-clock time in ``timezone_name`` to a UTC instant.

    ``on_ambiguous`` selects ``earliest`` or ``latest`` for a time that occurs
    twice. A nonexistent time is shifted forward to the next valid instant and
    reported as ``nonexistent`` so the caller can surface the adjustment.
    """
    tz = load_timezone(timezone_name)
    if on_ambiguous not in AMBIGUOUS_POLICIES:
        raise ValidationAppError(
            "Unsupported ambiguous-time policy",
            extra={"reason": "invalid_ambiguous_policy", "allowed": list(AMBIGUOUS_POLICIES)},
        )
    local = (
        local_time.astimezone(tz).replace(tzinfo=None)
        if local_time.tzinfo is not None
        else local_time
    )
    resolution = _classify(local, tz)
    fold = 1 if resolution == RESOLUTION_AMBIGUOUS and on_ambiguous == AMBIGUOUS_LATEST else 0
    aware = local.replace(tzinfo=tz, fold=fold)
    return ResolvedSchedule(
        scheduled_at=aware.astimezone(UTC),
        timezone=timezone_name,
        local_time=aware.astimezone(tz).replace(tzinfo=None),
        resolution=resolution,
    )
