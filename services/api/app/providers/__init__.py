"""Provider adapters: the only outbound email boundary (ARCHITECTURE.md section 2).

Provider SDK/HTTP code stays inside this package; the rest of the application
sees only the normalized contract in :mod:`app.providers.contract`.
"""

from __future__ import annotations

from app.providers.contract import (
    AccountVerification,
    CapabilityDeclaration,
    CapacitySnapshot,
    MessageClass,
    NormalizedProviderEvent,
    OutboundMessage,
    ProviderAdapter,
    ProviderAdapterError,
    ProviderTimeoutError,
    ReconciliationResult,
    Secret,
    SubmitOutcome,
    SubmitResult,
)
from app.providers.registry import (
    UnknownProviderError,
    available_providers,
    get_adapter,
    is_known_provider,
    register_adapter,
)

__all__ = [
    "AccountVerification",
    "CapabilityDeclaration",
    "CapacitySnapshot",
    "MessageClass",
    "NormalizedProviderEvent",
    "OutboundMessage",
    "ProviderAdapter",
    "ProviderAdapterError",
    "ProviderTimeoutError",
    "ReconciliationResult",
    "Secret",
    "SubmitOutcome",
    "SubmitResult",
    "UnknownProviderError",
    "available_providers",
    "get_adapter",
    "is_known_provider",
    "register_adapter",
]
