"""Provider account domain.

Public surface: :class:`ProviderAccountService`, the operator-facing service for
registering accounts and credentials, verifying them, refreshing the dated
capacity facts the router acts on, and toggling the tenant-level marketing pause
(SPEC.md sections 4 and 6).
"""

from __future__ import annotations

from app.domain.provider.service import ACCOUNT_STATUSES, ProviderAccountService

__all__ = ["ACCOUNT_STATUSES", "ProviderAccountService"]
