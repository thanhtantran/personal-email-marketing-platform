"""Rendered output must never carry scripts, handlers or unsafe URLs."""

from __future__ import annotations

import pytest

from app.security.sanitize import (
    is_allowed_url,
    sanitize_html,
    unsanitized_violations,
)


def test_script_content_is_removed_not_unwrapped() -> None:
    dirty = '<div><script>alert("x")</script><p>Hi</p></div>'
    clean = sanitize_html(dirty)
    assert "script" not in clean.lower()
    assert "alert" not in clean
    assert "Hi" in clean


def test_event_handlers_are_stripped() -> None:
    clean = sanitize_html('<a href="https://example.com" onclick="steal()">go</a>')
    assert "onclick" not in clean.lower()
    assert 'href="https://example.com"' in clean


def test_javascript_url_is_dropped() -> None:
    clean = sanitize_html('<a href="javascript:alert(1)">go</a>')
    assert "javascript" not in clean.lower()


def test_iframe_and_object_embeds_removed() -> None:
    clean = sanitize_html('<iframe src="https://evil.test"></iframe><p>ok</p>')
    assert "iframe" not in clean.lower()
    assert "ok" in clean


def test_style_import_and_expression_removed() -> None:
    dirty = "<style>@import url('https://evil.test/x.css'); .a{width:expression(alert(1))}</style>"
    clean = sanitize_html(dirty)
    assert "@import" not in clean
    assert "expression" not in clean.lower()


def test_unsafe_url_helper_rejects_relative_and_script_schemes() -> None:
    assert is_allowed_url("https://example.com/x") is True
    assert is_allowed_url("mailto:me@example.com") is True
    assert is_allowed_url("tel:+15551234") is True
    assert is_allowed_url("javascript:alert(1)") is False
    assert is_allowed_url("//evil.test/x") is False
    assert is_allowed_url("/relative/path") is False
    assert is_allowed_url("") is False


@pytest.mark.parametrize(
    "html, code",
    [
        ("<script>x()</script>", "script_tag"),
        ("<iframe></iframe>", "iframe_tag"),
        ('<a onclick="x()">a</a>', "event_handler"),
        ("<a href='javascript:x'>a</a>", "javascript_url"),
    ],
)
def test_unsanitized_violations_report_codes(html: str, code: str) -> None:
    assert code in unsanitized_violations(html)
