"""Campaign analytics: reading caveats and non-conflation of metrics."""

from __future__ import annotations

import uuid

from app.config import Settings
from app.domain.analytics.service import (
    CAVEAT_ACCEPTANCE,
    CAVEAT_ASYNC,
    CAVEAT_TRACKING_OFF,
    CAVEAT_UNKNOWN,
    CampaignAnalyticsService,
)


def _service(tracking_enabled: bool) -> CampaignAnalyticsService:
    return CampaignAnalyticsService(
        None,  # type: ignore[arg-type] - caveats do not touch the session
        uuid.uuid4(),
        Settings(tracking_enabled=tracking_enabled),
    )


def test_caveats_always_explain_acceptance_versus_delivery() -> None:
    caveats = _service(tracking_enabled=False)._caveats()
    assert CAVEAT_ACCEPTANCE in caveats
    assert CAVEAT_ASYNC in caveats
    assert CAVEAT_UNKNOWN in caveats


def test_tracking_off_adds_a_caveat() -> None:
    assert CAVEAT_TRACKING_OFF in _service(tracking_enabled=False)._caveats()


def test_tracking_on_drops_the_tracking_caveat() -> None:
    assert CAVEAT_TRACKING_OFF not in _service(tracking_enabled=True)._caveats()
