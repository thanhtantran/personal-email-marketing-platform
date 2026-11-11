"""Plaintext alternative must be derived deterministically from HTML."""

from __future__ import annotations

from app.domain.content.text import html_to_text


def test_script_and_style_content_is_dropped() -> None:
    html = "<style>.a{color:red}</style><script>alert(1)</script><p>Hello</p>"
    assert html_to_text(html) == "Hello"


def test_block_elements_become_newlines() -> None:
    text = html_to_text("<p>One</p><p>Two</p>")
    assert text == "One\n\nTwo"


def test_br_and_entities_are_handled() -> None:
    text = html_to_text("<p>A &amp; B<br>C</p>")
    assert text == "A & B\nC"


def test_whitespace_is_normalized() -> None:
    text = html_to_text("<div>  spaced   out  </div>")
    assert text == "spaced out"
