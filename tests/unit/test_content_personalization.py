"""Personalization must be allowlisted, escaped and observable."""

from __future__ import annotations

import types

import pytest

from app.domain.content.personalization import (
    extract_variables,
    is_allowed_variable,
    missing_report,
    render,
    validate_variables,
    values_from_contact,
)
from app.errors import ValidationAppError


def test_values_are_html_escaped() -> None:
    result = render("Hi {{ first_name }}", {"first_name": '<script>alert(1)</script>'})
    assert "<script>" not in result.body
    assert "&lt;script&gt;" in result.body


def test_escape_can_be_disabled_for_text_contexts() -> None:
    result = render("Hi {{ first_name }}", {"first_name": "A & B"}, escape=False)
    assert result.body == "Hi A & B"


def test_default_is_used_and_recorded() -> None:
    result = render('Hi {{ first_name | default: "there" }}', {})
    assert result.body == "Hi there"
    assert result.used_fallback == ["first_name"]
    assert result.missing == []


def test_missing_value_is_reported_and_removed() -> None:
    result = render("Hi {{ first_name }}!", {})
    assert result.body == "Hi !"
    assert result.missing == ["first_name"]
    assert result.unresolved == ["{{ first_name }}"]


def test_explicit_value_wins_over_default() -> None:
    result = render('{{ first_name | default: "there" }}', {"first_name": "Ada"})
    assert result.body == "Ada"
    assert result.used_fallback == []


@pytest.mark.parametrize(
    "name, allowed",
    [
        ("first_name", True),
        ("email", True),
        ("attribute.company", True),
        ("attribute.bad-key", False),
        ("system.env", False),
        ("", False),
    ],
)
def test_allowed_variables(name: str, allowed: bool) -> None:
    assert is_allowed_variable(name) is allowed


def test_unknown_variable_is_rejected() -> None:
    with pytest.raises(ValidationAppError) as excinfo:
        validate_variables("Hi {{ secret_token }}")
    assert excinfo.value.extra.get("reason") == "unknown_personalization_variable"


def test_extract_variables_preserves_order() -> None:
    refs = extract_variables("{{ first_name }} {{ last_name }}")
    assert [ref.name for ref in refs] == ["first_name", "last_name"]


def test_missing_report_only_counts_required_variables() -> None:
    text = '{{ first_name | default: "there" }} {{ company }}'
    empty = [{"first_name": "", "company": ""}, {"first_name": "Ada", "company": "Acme"}]
    assert missing_report(text, empty) == ["company"]


def test_values_from_contact_builds_builtins_and_attributes() -> None:
    contact = types.SimpleNamespace(
        normalized_email="ada@example.com",
        attributes={"first_name": "Ada", "last_name": "Lovelace", "company": "Acme"},
    )
    values = values_from_contact(contact)
    assert values["email"] == "ada@example.com"
    assert values["full_name"] == "Ada Lovelace"
    assert values["attribute.company"] == "Acme"
