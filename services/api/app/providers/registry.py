"""Adapter registry.

Adapters are resolved by provider name so gateway code never imports a concrete
provider. ``mock`` is always available and is the only adapter that can never
send a real message; production adapters are registered here and gated by
account eligibility and operator configuration rather than by code paths.
"""

from __future__ import annotations

from collections.abc import Callable

from app.config import Settings, get_settings
from app.providers.contract import ProviderAdapter
from app.providers.mock import MOCK_PROVIDER_NAME, MockProviderAdapter
from app.providers.resend import RESEND_PROVIDER_NAME, ResendProviderAdapter

AdapterFactory = Callable[[Settings], ProviderAdapter]


class UnknownProviderError(Exception):
    """Raised when an account references a provider with no registered adapter."""


def _resend(settings: Settings) -> ProviderAdapter:
    return ResendProviderAdapter(timeout_seconds=settings.send_request_timeout_seconds)


_FACTORIES: dict[str, AdapterFactory] = {
    MOCK_PROVIDER_NAME: lambda _settings: MockProviderAdapter(),
    RESEND_PROVIDER_NAME: _resend,
}


def register_adapter(name: str, factory: AdapterFactory) -> None:
    """Register an adapter factory (used by adapters and tests)."""
    _FACTORIES[name] = factory


def available_providers() -> list[str]:
    return sorted(_FACTORIES)


def is_known_provider(name: str) -> bool:
    return name in _FACTORIES


def get_adapter(name: str, *, settings: Settings | None = None) -> ProviderAdapter:
    factory = _FACTORIES.get(name)
    if factory is None:
        raise UnknownProviderError(f"no adapter registered for provider '{name}'")
    return factory(settings or get_settings())
