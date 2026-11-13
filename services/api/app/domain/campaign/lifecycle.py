"""Campaign lifecycle state machine.

The legal transitions live in one place so the API, scheduler and workers cannot
disagree about what may follow a given state. Every transition goes through
``ensure_transition``; an illegal move raises a 409 instead of silently mutating
the campaign (SPEC.md section 5).
"""

from __future__ import annotations

from app.errors import ConflictError

CAMPAIGN_STATUSES: tuple[str, ...] = (
    "draft",
    "scheduled",
    "preparing",
    "sending",
    "paused",
    "completed",
    "cancelled",
    "failed",
)

TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "cancelled", "failed"})

# Statuses in which new recipient submissions are permitted. Pause, cancel and
# any terminal state return ``False`` from ``allows_dispatch``.
DISPATCHING_STATUSES: frozenset[str] = frozenset({"sending"})

# Statuses whose fields an operator may still edit.
EDITABLE_STATUSES: frozenset[str] = frozenset({"draft", "scheduled"})

_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"scheduled", "preparing", "cancelled", "failed"}),
    "scheduled": frozenset({"draft", "preparing", "cancelled", "failed"}),
    "preparing": frozenset({"sending", "paused", "cancelled", "failed"}),
    "sending": frozenset({"paused", "completed", "cancelled", "failed"}),
    "paused": frozenset({"sending", "cancelled", "failed"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
    "failed": frozenset(),
}


class InvalidTransitionError(ConflictError):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(
            f"Cannot move campaign from '{current}' to '{target}'",
            extra={"reason": "invalid_transition", "from": current, "to": target},
        )


def can_transition(current: str, target: str) -> bool:
    return target in _TRANSITIONS.get(current, frozenset())


def ensure_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise InvalidTransitionError(current, target)


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


def is_editable(status: str) -> bool:
    return status in EDITABLE_STATUSES


def allows_dispatch(status: str) -> bool:
    """Whether a recipient may be submitted to the provider in this state.

    Dispatch re-checks this immediately before every submit; a pause or cancel
    therefore stops future submissions while messages already accepted stay in
    the ledger (SPEC.md section 5, retry rules).
    """
    return status in DISPATCHING_STATUSES
