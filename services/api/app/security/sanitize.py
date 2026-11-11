"""Allowlist HTML sanitizer for rendered email content.

Rendering output is never trusted: GrapesJS/MJML source is author-editable, so
every rendered document passes through this allowlist before it is stored or
shown in a preview (SPEC.md section 8). Scripts, event handlers, unsafe URL
protocols, embedded objects and unsafe CSS are removed.
"""

from __future__ import annotations

import re

import nh3

# Tags that are meaningful in email HTML. Notably absent: script, iframe,
# object, embed, form, input, button, link, meta, base, svg, math.
ALLOWED_TAGS: set[str] = {
    "a",
    "b",
    "blockquote",
    "br",
    "center",
    "code",
    "div",
    "em",
    "font",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "small",
    "span",
    "strong",
    "style",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}

# Tags whose entire content is dropped, not merely unwrapped. Without this the
# inner text of a stripped <script> would leak into the visible document.
CLEAN_CONTENT_TAGS: set[str] = {
    "script",
    "iframe",
    "object",
    "embed",
    "form",
    "svg",
    "math",
    "template",
    "noscript",
    "title",
}

ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "*": {
        "align",
        "bgcolor",
        "border",
        "cellpadding",
        "cellspacing",
        "class",
        "colspan",
        "dir",
        "height",
        "id",
        "lang",
        "role",
        "rowspan",
        "style",
        "title",
        "valign",
        "width",
    },
    # "rel" is intentionally omitted: nh3 owns it via ``link_rel`` below.
    "a": {"href", "name", "target"},
    "img": {"alt", "border", "height", "src", "width"},
    "font": {"color", "face", "size"},
    "table": {"align", "border", "cellpadding", "cellspacing", "role", "width"},
    "td": {"bgcolor", "colspan", "height", "rowspan", "valign", "width"},
    "th": {"bgcolor", "colspan", "height", "rowspan", "valign", "width"},
}

ALLOWED_URL_SCHEMES: set[str] = {"http", "https", "mailto", "tel"}

# Positioning and CSS expressions are excluded: they enable overlay/spoofing
# tricks and legacy script execution inside email clients.
ALLOWED_STYLE_PROPERTIES: set[str] = {
    "background",
    "background-color",
    "background-image",
    "background-position",
    "background-repeat",
    "background-size",
    "border",
    "border-bottom",
    "border-bottom-color",
    "border-bottom-left-radius",
    "border-bottom-right-radius",
    "border-bottom-style",
    "border-bottom-width",
    "border-collapse",
    "border-color",
    "border-left",
    "border-left-color",
    "border-left-style",
    "border-left-width",
    "border-radius",
    "border-right",
    "border-right-color",
    "border-right-style",
    "border-right-width",
    "border-spacing",
    "border-style",
    "border-top",
    "border-top-color",
    "border-top-left-radius",
    "border-top-right-radius",
    "border-top-style",
    "border-top-width",
    "border-width",
    "box-shadow",
    "color",
    "display",
    "font",
    "font-family",
    "font-size",
    "font-style",
    "font-weight",
    "height",
    "letter-spacing",
    "line-height",
    "margin",
    "margin-bottom",
    "margin-left",
    "margin-right",
    "margin-top",
    "max-height",
    "max-width",
    "min-width",
    "mso-line-height-rule",
    "mso-padding-alt",
    "mso-table-lspace",
    "mso-table-rspace",
    "opacity",
    "overflow",
    "padding",
    "padding-bottom",
    "padding-left",
    "padding-right",
    "padding-top",
    "text-align",
    "text-decoration",
    "text-indent",
    "text-transform",
    "vertical-align",
    "white-space",
    "width",
    "word-break",
    "word-wrap",
}

_STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.IGNORECASE | re.DOTALL)
_IMPORT_RE = re.compile(r"@import[^;]*;?", re.IGNORECASE | re.DOTALL)
_UNSAFE_CSS_RE = re.compile(
    r"(expression\s*\(|javascript\s*:|vbscript\s*:|behavior\s*:|-moz-binding)", re.IGNORECASE
)

# Patterns used for fast, explanatory rejection before rendering. They are a
# usability gate only; the allowlist above remains the authoritative control.
_UNSAFE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("script_tag", re.compile(r"<\s*script\b", re.IGNORECASE)),
    ("iframe_tag", re.compile(r"<\s*iframe\b", re.IGNORECASE)),
    ("object_tag", re.compile(r"<\s*(object|embed)\b", re.IGNORECASE)),
    ("form_tag", re.compile(r"<\s*form\b", re.IGNORECASE)),
    ("event_handler", re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)),
    ("javascript_url", re.compile(r"(javascript|vbscript)\s*:", re.IGNORECASE)),
    ("data_html_url", re.compile(r"data\s*:\s*text/html", re.IGNORECASE)),
)


def unsanitized_violations(html: str) -> list[str]:
    """Return codes for unsafe constructs found in raw, untrusted HTML/MJML."""
    return [code for code, pattern in _UNSAFE_PATTERNS if pattern.search(html)]


def is_allowed_url(value: str) -> bool:
    """Allow only explicit, safe URL schemes (relative URLs are rejected)."""
    candidate = value.strip()
    if not candidate:
        return False
    scheme, sep, _ = candidate.partition(":")
    if not sep:
        return False
    return scheme.strip().lower() in ALLOWED_URL_SCHEMES


def _harden_style_blocks(html: str) -> str:
    """Strip @import and script-capable CSS from surviving <style> elements."""

    def _clean(match: re.Match[str]) -> str:
        inner = _IMPORT_RE.sub("", match.group(1))
        inner = _UNSAFE_CSS_RE.sub("", inner)
        return f"<style>{inner}</style>"

    return _STYLE_BLOCK_RE.sub(_clean, html)


def sanitize_html(html: str) -> str:
    """Return a sanitized document safe to store, preview or deliver."""
    cleaned = nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        clean_content_tags=CLEAN_CONTENT_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        filter_style_properties=ALLOWED_STYLE_PROPERTIES,
        strip_comments=True,
        link_rel="noopener noreferrer",
    )
    return _harden_style_blocks(cleaned)
