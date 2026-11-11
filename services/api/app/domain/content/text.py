"""Deterministic HTML-to-plaintext alternative generation.

The text part is derived from the sanitized HTML so the two parts can never
disagree about content.
"""

from __future__ import annotations

import html as html_module
import re

_DROP_ELEMENTS_RE = re.compile(
    r"<\s*(script|style|head)\b.*?<\s*/\s*\1\s*>", re.IGNORECASE | re.DOTALL
)
_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_BLOCK_BREAK_RE = re.compile(
    r"<\s*/?\s*(p|div|tr|table|h[1-6]|li|blockquote|section|hr)\b[^>]*>", re.IGNORECASE
)
_TAG_RE = re.compile(r"<[^>]+>")
_TRAILING_SPACE_RE = re.compile(r"[ \t]+\n")
_RUN_OF_SPACES_RE = re.compile(r"[ \t]{2,}")
_RUN_OF_NEWLINES_RE = re.compile(r"\n{3,}")


def html_to_text(html: str) -> str:
    """Convert HTML into a readable plaintext body."""
    text = _DROP_ELEMENTS_RE.sub("", html)
    text = _BR_RE.sub("\n", text)
    text = _BLOCK_BREAK_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html_module.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _TRAILING_SPACE_RE.sub("\n", text)
    text = _RUN_OF_SPACES_RE.sub(" ", text)
    text = _RUN_OF_NEWLINES_RE.sub("\n\n", text)
    return text.strip()
