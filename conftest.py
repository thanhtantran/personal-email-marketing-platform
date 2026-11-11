"""Pytest path bootstrap.

Ensures the `app` package under services/api is importable when tests run
without an editable install (e.g. a plain `pytest` from the repo root).
"""

from __future__ import annotations

import sys
from pathlib import Path

API_DIR = Path(__file__).parent / "services" / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))
