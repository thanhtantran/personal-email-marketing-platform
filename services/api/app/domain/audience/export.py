"""CSV export with spreadsheet-injection protection.

Spreadsheet programs treat a leading ``=``, ``+``, ``-``, ``@``, tab or carriage
return as the start of a formula. Exported values are prefixed with a single
quote so a contact attribute cannot become executable content (SPEC.md
section 8).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe_value(value: object) -> str:
    text = "" if value is None else str(value)
    if text and text[0] in FORMULA_PREFIXES:
        return "'" + text
    return text


def render_csv(columns: Sequence[str], rows: Iterable[dict[str, object]]) -> str:
    """Render rows as RFC 4180 CSV, escaping every field for spreadsheet safety."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([csv_safe_value(row.get(column)) for column in columns])
    return buffer.getvalue()
