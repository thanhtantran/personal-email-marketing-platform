"""Provider event intake, normalization and reduction (Stage 6)."""

from __future__ import annotations

from app.domain.events.processing import ProcessingReport, WebhookProcessingService
from app.domain.events.reducer import (
    derived_event_key,
    provider_event_key,
    reduce_recipient_status,
)
from app.domain.events.unsubscribe import (
    UnsubscribeOutcome,
    UnsubscribeTarget,
    build_unsubscribe_token,
    record_unsubscribe,
    verify_unsubscribe_token,
)
from app.domain.events.vocabulary import (
    NORMALIZED_EVENT_TYPES,
    SUPPRESSION_REASON_BY_EVENT,
)

__all__ = [
    "NORMALIZED_EVENT_TYPES",
    "SUPPRESSION_REASON_BY_EVENT",
    "ProcessingReport",
    "UnsubscribeOutcome",
    "UnsubscribeTarget",
    "WebhookProcessingService",
    "build_unsubscribe_token",
    "derived_event_key",
    "provider_event_key",
    "record_unsubscribe",
    "reduce_recipient_status",
    "verify_unsubscribe_token",
]
