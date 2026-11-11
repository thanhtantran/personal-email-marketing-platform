"""CSV export must neutralize spreadsheet formula injection."""

from __future__ import annotations

import pytest

from app.domain.audience.export import csv_safe_value, render_csv


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_formula_prefixes_are_escaped(prefix: str) -> None:
    assert csv_safe_value(f"{prefix}cmd") == f"'{prefix}cmd"


def test_plain_values_are_unchanged() -> None:
    assert csv_safe_value("hello") == "hello"
    assert csv_safe_value(None) == ""
    assert csv_safe_value(42) == "42"


def test_render_csv_writes_header_and_escapes_rows() -> None:
    body = render_csv(["email", "note"], [{"email": "=1+1", "note": "ok"}])
    lines = body.split("\r\n")
    assert lines[0] == "email,note"
    assert lines[1] == "'=1+1,ok"
