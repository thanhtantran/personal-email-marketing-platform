"""Normalized recipient event vocabulary (SPEC.md section 7).

Adapters translate a provider payload into these names; nothing outside the
adapter layer may interpret a provider's own event names. Keeping the vocabulary
in one place lets the reducer, analytics and suppression policy agree on which
events mean what.
"""

from __future__ import annotations

#: The complete normalized vocabulary. ``submitted`` is "the provider accepted
#: the request" and ``delivered`` is "the provider reports the message arrived";
#: the two are never conflated (SPEC.md section 7).
EVENT_QUEUED = "queued"
EVENT_SUBMITTED = "submitted"
EVENT_DELIVERED = "delivered"
EVENT_DEFERRED = "deferred"
EVENT_BOUNCED_SOFT = "bounced_soft"
EVENT_BOUNCED_HARD = "bounced_hard"
EVENT_COMPLAINED = "complained"
EVENT_UNSUBSCRIBED = "unsubscribed"
EVENT_REJECTED = "rejected"
EVENT_UNKNOWN = "unknown"
EVENT_OPENED = "opened"
EVENT_CLICKED = "clicked"

NORMALIZED_EVENT_TYPES: frozenset[str] = frozenset(
    {
        EVENT_QUEUED,
        EVENT_SUBMITTED,
        EVENT_DELIVERED,
        EVENT_DEFERRED,
        EVENT_BOUNCED_SOFT,
        EVENT_BOUNCED_HARD,
        EVENT_COMPLAINED,
        EVENT_UNSUBSCRIBED,
        EVENT_REJECTED,
        EVENT_UNKNOWN,
        EVENT_OPENED,
        EVENT_CLICKED,
    }
)

#: Events that create a suppression regardless of campaign state. Complaint,
#: hard bounce and unsubscribe are authoritative do-not-send signals (SPEC.md
#: section 7 and invariant 5).
SUPPRESSION_REASON_BY_EVENT: dict[str, str] = {
    EVENT_COMPLAINED: "complaint",
    EVENT_BOUNCED_HARD: "hard_bounce",
    EVENT_UNSUBSCRIBED: "unsubscribe",
}

#: Events that prove the provider took the message (acceptance class).
ACCEPTANCE_EVENTS: frozenset[str] = frozenset({EVENT_SUBMITTED, EVENT_DELIVERED})

#: Events that prove the message will not (or cannot) be delivered.
FAILURE_EVENTS: frozenset[str] = frozenset({EVENT_REJECTED, EVENT_BOUNCED_HARD})

#: Events that are retained for analytics but never move the recipient's ledger
#: status. A complaint or unsubscribe arrives *after* delivery, so it must not
#: rewrite a successful outcome; opens and clicks are weak engagement signals.
INFORMATIONAL_EVENTS: frozenset[str] = frozenset(
    {
        EVENT_QUEUED,
        EVENT_OPENED,
        EVENT_CLICKED,
        EVENT_DEFERRED,
        EVENT_BOUNCED_SOFT,
        EVENT_COMPLAINED,
        EVENT_UNSUBSCRIBED,
    }
)
