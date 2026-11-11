"""Editor state and MJML source are gated before rendering."""

from __future__ import annotations

import pytest

from app.domain.content.editor import (
    MAX_COMPONENT_DEPTH,
    validate_editor_json,
    validate_mjml_source,
)
from app.errors import ValidationAppError

VALID_MJML = (
    "<mjml><mj-body><mj-section><mj-column>"
    "<mj-text>Hi</mj-text></mj-column></mj-section></mj-body></mjml>"
)


def test_valid_editor_state_is_accepted() -> None:
    state = {
        "type": "mjml",
        "components": [{"type": "mj-text", "content": "Hello"}],
    }
    assert validate_editor_json(state) == state


def test_none_editor_state_becomes_empty_object() -> None:
    assert validate_editor_json(None) == {}


def test_non_object_editor_state_is_rejected() -> None:
    with pytest.raises(ValidationAppError):
        validate_editor_json(["not", "an", "object"])


@pytest.mark.parametrize(
    "state",
    [
        {"type": "mj-raw", "content": "<b>x</b>"},
        {"type": "mj-script"},
        {"tagName": "iframe"},
        {"content": "<script>alert(1)</script>"},
        {"content": '<a href="javascript:x">x</a>'},
    ],
)
def test_unsafe_editor_state_is_rejected(state: dict) -> None:
    with pytest.raises(ValidationAppError):
        validate_editor_json(state)


def test_deeply_nested_editor_state_is_rejected() -> None:
    node: dict = {"type": "mj-text"}
    for _ in range(MAX_COMPONENT_DEPTH + 2):
        node = {"children": [node]}
    with pytest.raises(ValidationAppError):
        validate_editor_json(node)


def test_valid_mjml_source_is_accepted() -> None:
    assert validate_mjml_source(VALID_MJML, max_bytes=10_000) == VALID_MJML


@pytest.mark.parametrize(
    "source",
    [
        "",
        "not mjml at all",
        "<div>no root</div>",
        "<mjml><mj-body><mj-raw>x</mj-raw></mj-body></mjml>",
        "<mjml><mj-body></mj-body></mjml><script>x()</script>",
    ],
)
def test_invalid_mjml_source_is_rejected(source: str) -> None:
    with pytest.raises(ValidationAppError):
        validate_mjml_source(source, max_bytes=10_000)


def test_oversized_mjml_source_is_rejected() -> None:
    with pytest.raises(ValidationAppError):
        validate_mjml_source(VALID_MJML, max_bytes=10)
