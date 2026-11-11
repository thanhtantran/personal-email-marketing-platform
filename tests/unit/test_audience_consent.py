"""Consent/suppression policy: eligibility and reason-to-status mapping."""

from __future__ import annotations

from app.domain.audience.consent import is_eligible, status_for_suppression_reason


def test_eligible_only_when_active_and_consented() -> None:
    assert is_eligible(status="active", consent_status="granted")
    assert not is_eligible(status="active", consent_status="unknown")
    assert not is_eligible(status="suppressed", consent_status="granted")
    assert not is_eligible(status="unsubscribed", consent_status="granted")


def test_suppression_reason_mirrors_contact_status() -> None:
    assert status_for_suppression_reason("unsubscribe") == "unsubscribed"
    assert status_for_suppression_reason("complaint") == "suppressed"
    assert status_for_suppression_reason("hard_bounce") == "suppressed"


def test_manual_suppression_does_not_force_a_status() -> None:
    assert status_for_suppression_reason("manual") is None
