"""Scheduler entry point.

Stage 0 placeholder: a single-active scheduler will claim due campaigns using a
PostgreSQL lease/advisory lock so accidental duplicate instances cannot
double-enqueue work (see ARCHITECTURE.md section 6). The real due-campaign
claiming loop is implemented in Stage 4.
"""

from __future__ import annotations

import logging
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("scheduler")


def main() -> None:
    logger.info("scheduler placeholder started; due-campaign claiming arrives in Stage 4")
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
