"""Object storage interface.

Uploads go to a private bucket through a short-lived presigned URL. The API
verifies existence, size and digest before reading a staged object, so the
storage implementation stays behind this narrow contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size: int


class ObjectStorage(Protocol):
    def presign_put(self, key: str, *, expires_seconds: int, content_type: str = "text/csv") -> str:
        """Return a short-lived URL allowing a single PUT to ``key``."""

    def head(self, key: str) -> ObjectInfo | None:
        """Return object metadata, or ``None`` when the key does not exist."""

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/json") -> None:
        """Write an object fully.

        Used for the bounded, TTL-managed raw webhook payload; callers must keep
        the body small and treat a failure as fatal for that acceptance path.
        """

    def get_bytes(self, key: str) -> bytes:
        """Read an object fully. Callers must bound size before calling."""

    def delete(self, key: str) -> None:
        """Remove a staged object. Missing keys are not an error."""
