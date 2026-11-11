"""Security primitives: opaque session tokens and constant-time comparison."""

from __future__ import annotations

from app.security.tokens import constant_time_equals, generate_token, hash_token


def test_generate_token_is_random_and_url_safe() -> None:
    first = generate_token()
    second = generate_token()
    assert first != second
    assert len(first) >= 43  # 32 random bytes -> at least 43 url-safe chars
    assert all(char.isalnum() or char in "-_" for char in first)


def test_hash_token_is_stable_sha256() -> None:
    token = "example-token"
    digest = hash_token(token)
    assert len(digest) == 64
    assert digest == hash_token(token)
    assert digest != token
    assert all(char in "0123456789abcdef" for char in digest)


def test_constant_time_equals() -> None:
    assert constant_time_equals("abc", "abc")
    assert not constant_time_equals("abc", "abd")
    assert not constant_time_equals("abc", "abcd")
