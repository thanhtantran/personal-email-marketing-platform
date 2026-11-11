"""Safe personalization variables for email content.

Contact data is never interpolated raw. Values are always escaped for the target
context, an explicit fallback may be declared in the template, and variables that
resolve to nothing are reported so the operator sees them before send
(PRD "Templates and campaigns"; IMPLEMENTATION_PLAN Stage 3 exit gate).

Syntax::

    {{ first_name }}
    {{ first_name | default: "there" }}
"""

from __future__ import annotations

import html as html_module
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from app.errors import ValidationAppError

VARIABLE_RE = re.compile(
    r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*"
    r'(?:\|\s*default\s*:\s*"([^"]*)")?\s*\}\}'
)

BUILTIN_VARIABLES: frozenset[str] = frozenset(
    {"email", "first_name", "last_name", "full_name", "company"}
)
ATTRIBUTE_PREFIX = "attribute."
_ATTRIBUTE_KEY_RE = re.compile(r"^[a-z0-9_]{1,64}$")


@dataclass(frozen=True)
class VariableRef:
    name: str
    default: str | None = None


@dataclass
class RenderResult:
    body: str
    missing: list[str] = field(default_factory=list)
    used_fallback: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def is_allowed_variable(name: str) -> bool:
    if name in BUILTIN_VARIABLES:
        return True
    if name.startswith(ATTRIBUTE_PREFIX):
        return bool(_ATTRIBUTE_KEY_RE.match(name[len(ATTRIBUTE_PREFIX) :]))
    return False


def extract_variables(text: str) -> list[VariableRef]:
    """Return the variable references used by ``text`` in document order."""
    return [VariableRef(match.group(1), match.group(2)) for match in VARIABLE_RE.finditer(text)]


def validate_variables(text: str) -> list[VariableRef]:
    """Raise for any variable outside the allowlist; return the references."""
    references = extract_variables(text)
    unknown = sorted({ref.name for ref in references if not is_allowed_variable(ref.name)})
    if unknown:
        raise ValidationAppError(
            "Template uses unsupported personalization variables",
            extra={"reason": "unknown_personalization_variable", "variables": unknown},
        )
    return references


def resolve(values: Mapping[str, str], name: str) -> str:
    """Return the value for ``name`` or an empty string when absent/blank."""
    value = values.get(name)
    if value is None:
        return ""
    return str(value).strip()


def _dedupe(names: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def render(text: str, values: Mapping[str, str], *, escape: bool = True) -> RenderResult:
    """Substitute variables in ``text``, escaping values for HTML contexts."""
    missing: list[str] = []
    used_fallback: list[str] = []
    unresolved: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        default = match.group(2)
        raw = resolve(values, name)
        if raw:
            return html_module.escape(raw, quote=True) if escape else raw
        if default is not None:
            used_fallback.append(name)
            return html_module.escape(default, quote=True) if escape else default
        missing.append(name)
        unresolved.append(match.group(0))
        return ""

    body = VARIABLE_RE.sub(_replace, text)
    return RenderResult(
        body=body,
        missing=_dedupe(missing),
        used_fallback=_dedupe(used_fallback),
        unresolved=unresolved,
    )


def missing_report(text: str, value_sets: Iterable[Mapping[str, str]]) -> list[str]:
    """Preflight: required variables (no fallback) that are empty for any contact."""
    required = [ref.name for ref in extract_variables(text) if ref.default is None]
    if not required:
        return []
    missing: set[str] = set()
    for values in value_sets:
        for name in required:
            if not resolve(values, name):
                missing.add(name)
    return sorted(missing)


def values_from_contact(contact: object) -> dict[str, str]:
    """Build a variable mapping from a contact record."""
    attributes = getattr(contact, "attributes", None) or {}
    first = str(attributes.get("first_name") or "").strip()
    last = str(attributes.get("last_name") or "").strip()
    full_name = str(attributes.get("full_name") or "").strip() or " ".join(
        part for part in (first, last) if part
    )
    values: dict[str, str] = {
        "email": str(getattr(contact, "normalized_email", "") or ""),
        "first_name": first,
        "last_name": last,
        "full_name": full_name,
        "company": str(attributes.get("company") or "").strip(),
    }
    for key, value in attributes.items():
        values[f"{ATTRIBUTE_PREFIX}{key}"] = "" if value is None else str(value)
    return values
