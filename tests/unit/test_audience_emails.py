"""Email normalization rules used for contact matching and import dedupe."""

from __future__ import annotations

from app.domain.audience.emails import is_valid_email, normalize_email


def test_normalize_lowercases_and_trims() -> None:
    assert normalize_email("  Alice@Example.COM ") == "alice@example.com"


def test_normalize_collapses_case_only_duplicates() -> None:
    assert normalize_email("Bob@Example.com") == normalize_email("bob@example.com")


def test_normalize_rejects_invalid_input() -> None:
    assert normalize_email("not-an-email") is None
    assert normalize_email("a@") is None
    assert normalize_email("") is None
    assert normalize_email(None) is None


def test_normalize_rejects_overlong_address() -> None:
    local = "a" * 320
    assert normalize_email(f"{local}@example.com") is None


def test_is_valid_email() -> None:
    assert is_valid_email("x@y.com")
    assert not is_valid_email("x@y")
