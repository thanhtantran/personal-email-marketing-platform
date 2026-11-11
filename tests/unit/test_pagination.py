"""Cursor pagination encodes a total order and rejects tampering."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.domain.pagination import decode_cursor, encode_cursor
from app.errors import ValidationAppError


def test_cursor_round_trip() -> None:
    created_at = datetime(2026, 1, 2, 3, 4, 5, 6789, tzinfo=UTC)
    row_id = uuid.uuid4()
    token = encode_cursor(created_at, row_id)
    assert decode_cursor(token) == (created_at, row_id)


def test_empty_cursor_is_none() -> None:
    assert decode_cursor("") is None


def test_invalid_cursor_is_rejected() -> None:
    with pytest.raises(ValidationAppError):
        decode_cursor("!!!not-base64!!!")
