"""Validation gate for GrapesJS editor state and MJML source.

This runs before rendering to fail fast with a clear reason code: the sanitizer
is the authoritative control, but accepting only supported components keeps
authoring inside the supported surface (IMPLEMENTATION_PLAN Stage 3 risks).
"""

from __future__ import annotations

import re

from app.errors import ValidationAppError
from app.security.sanitize import unsanitized_violations

# MJML components the editor may emit. Deliberately excluded: mj-raw, mj-html,
# mj-script - they would let an author bypass MJML structure with raw markup.
ALLOWED_COMPONENT_TYPES: set[str] = {
    "mjml",
    "mj-body",
    "mj-section",
    "mj-column",
    "mj-wrapper",
    "mj-group",
    "mj-hero",
    "mj-text",
    "mj-image",
    "mj-button",
    "mj-divider",
    "mj-spacer",
    "mj-social",
    "mj-social-element",
    "mj-navbar",
    "mj-navbar-link",
    "mj-table",
    "mj-style",
}

DISALLOWED_MJML_TAGS: set[str] = {"mj-raw", "mj-html", "mj-script", "mj-include"}

_DANGEROUS_TAG_NAMES: set[str] = {
    "script",
    "iframe",
    "object",
    "embed",
    "form",
    "input",
    "button",
    "link",
    "meta",
    "base",
    "svg",
    "canvas",
    "video",
    "audio",
    "template",
}

_DISALLOWED_TAG_RE = re.compile(
    r"<\s*(mj-raw|mj-html|mj-script|mj-include)\b", re.IGNORECASE
)

MAX_COMPONENT_DEPTH = 40


def _check_string(value: str, *, context: str) -> None:
    violations = unsanitized_violations(value)
    if violations:
        raise ValidationAppError(
            "Editor component contains unsafe content",
            extra={"reason": "unsafe_component_content", "context": context,
                   "violations": violations},
        )


def _walk(node: object, *, depth: int) -> None:
    if depth > MAX_COMPONENT_DEPTH:
        raise ValidationAppError(
            "Editor state is nested too deeply", extra={"reason": "component_depth_exceeded"}
        )
    if isinstance(node, dict):
        component_type = node.get("type")
        if (
            isinstance(component_type, str)
            and component_type.startswith("mj-")
            and component_type not in ALLOWED_COMPONENT_TYPES
        ):
            raise ValidationAppError(
                "Unsupported editor component",
                extra={"reason": "unsupported_component", "component": component_type},
            )
        tag_name = node.get("tagName")
        if isinstance(tag_name, str) and tag_name.strip().lower() in _DANGEROUS_TAG_NAMES:
            raise ValidationAppError(
                "Unsupported editor tag",
                extra={"reason": "unsupported_component", "component": tag_name.strip().lower()},
            )
        for key, value in node.items():
            if isinstance(value, str):
                _check_string(value, context=str(key))
            else:
                _walk(value, depth=depth + 1)
    elif isinstance(node, list):
        for item in node:
            _walk(item, depth=depth + 1)


def validate_editor_json(raw: object) -> dict:
    """Validate the saved GrapesJS editor state (arbitrary JSON object)."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValidationAppError(
            "Editor state must be a JSON object", extra={"reason": "editor_state_not_object"}
        )
    _walk(raw, depth=0)
    return raw


def validate_mjml_source(source: object, *, max_bytes: int) -> str:
    """Validate the authoritative MJML source before rendering."""
    if not isinstance(source, str) or not source.strip():
        raise ValidationAppError("MJML source is required", extra={"reason": "mjml_required"})
    if len(source.encode("utf-8")) > max_bytes:
        raise ValidationAppError(
            "MJML source exceeds the size limit",
            extra={"reason": "mjml_too_large", "max_bytes": max_bytes},
        )
    lowered = source.lower()
    if "<mjml" not in lowered:
        raise ValidationAppError(
            "MJML source must contain an <mjml> root element", extra={"reason": "mjml_root_missing"}
        )
    disallowed = _DISALLOWED_TAG_RE.search(source)
    if disallowed:
        raise ValidationAppError(
            "Unsupported MJML element",
            extra={"reason": "unsupported_component", "component": disallowed.group(1).lower()},
        )
    violations = unsanitized_violations(source)
    if violations:
        raise ValidationAppError(
            "MJML source contains unsafe content",
            extra={"reason": "mjml_unsafe", "violations": violations},
        )
    return source
