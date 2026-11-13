"""Launch validation, immutable snapshots and the idempotent recipient ledger."""

from __future__ import annotations

import uuid

from app.db.models import Campaign, Segment, Template
from app.domain.campaign.ledger import (
    RECIPIENT_STATUS_QUEUED,
    ledger_row,
    recipient_idempotency_key,
)
from app.domain.campaign.snapshot import build_audience_snapshot, build_content_snapshot
from app.domain.campaign.validation import (
    CODE_INVALID_FROM_EMAIL,
    CODE_MISSING_SEGMENT,
    CODE_MISSING_SENDER_NAME,
    CODE_MISSING_SUBJECT,
    CODE_MISSING_TEMPLATE,
    CODE_NO_ELIGIBLE_RECIPIENTS,
    CODE_PROVIDER_NOT_ELIGIBLE,
    CODE_STALE_CAPACITY,
    CODE_TEMPLATE_ARCHIVED,
    validate_launch,
)

TENANT = uuid.uuid4()
SEGMENT_ID = uuid.uuid4()
TEMPLATE_ID = uuid.uuid4()


def _template(*, status: str = "published", version: int = 3) -> Template:
    return Template(
        id=TEMPLATE_ID,
        tenant_id=TENANT,
        name="Welcome",
        editor_json={},
        mjml_source="<mjml></mjml>",
        html="<html></html>",
        text_body="hi",
        version=version,
        status=status,
    )


def _segment(*, version: int = 2) -> Segment:
    return Segment(
        id=SEGMENT_ID,
        tenant_id=TENANT,
        name="Active",
        definition={"conditions": [{"field": "status", "operator": "eq", "value": "active"}]},
        version=version,
    )


def _campaign(**overrides: object) -> Campaign:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "tenant_id": TENANT,
        "name": "Launch",
        "status": "draft",
        "subject": "Hello",
        "from_name": "Owner",
        "from_email": "owner@example.com",
        "reply_to": "reply@example.com",
        "template_id": TEMPLATE_ID,
        "template_version": 3,
        "segment_id": SEGMENT_ID,
    }
    values.update(overrides)
    return Campaign(**values)


def _check(campaign: Campaign, **kwargs: object):
    params: dict[str, object] = {
        "template": _template(),
        "segment": _segment(),
        "eligible_recipients": 10,
        "provider_eligible": True,
        "capacity_fresh": True,
    }
    params.update(kwargs)
    return validate_launch(campaign, **params)


def test_valid_campaign_passes() -> None:
    check = _check(_campaign())
    assert check.ok
    assert check.issues == []
    assert check.as_extra() == {"issues": []}


def test_missing_subject_and_template_block_launch() -> None:
    check = _check(_campaign(subject="   ", template_id=None), template=None)
    codes = {issue.code for issue in check.issues}
    assert CODE_MISSING_SUBJECT in codes
    assert CODE_MISSING_TEMPLATE in codes


def test_archived_template_blocks_launch() -> None:
    check = _check(_campaign(), template=_template(status="archived"))
    assert CODE_TEMPLATE_ARCHIVED in {issue.code for issue in check.issues}


def test_sender_identity_is_checked() -> None:
    check = _check(_campaign(from_name="", from_email="not-an-email"))
    codes = {issue.code for issue in check.issues}
    assert CODE_MISSING_SENDER_NAME in codes
    assert CODE_INVALID_FROM_EMAIL in codes


def test_segment_and_eligibility_are_checked() -> None:
    check = _check(_campaign(segment_id=None), segment=None)
    assert CODE_MISSING_SEGMENT in {issue.code for issue in check.issues}

    check = _check(_campaign(), eligible_recipients=0)
    assert CODE_NO_ELIGIBLE_RECIPIENTS in {issue.code for issue in check.issues}


def test_provider_readiness_gate() -> None:
    check = _check(_campaign(), provider_eligible=False, capacity_fresh=False)
    codes = {issue.code for issue in check.issues}
    assert CODE_PROVIDER_NOT_ELIGIBLE in codes
    assert CODE_STALE_CAPACITY in codes


def test_content_snapshot_freezes_sender_and_render() -> None:
    campaign = _campaign()
    content = build_content_snapshot(campaign, _template())
    assert content["subject"] == "Hello"
    assert content["from_email"] == "owner@example.com"
    assert content["template_version"] == 3
    assert content["mjml_source"] == "<mjml></mjml>"
    assert content["html"] == "<html></html>"


def test_audience_snapshot_freezes_definition() -> None:
    audience = build_audience_snapshot(_segment())
    assert audience["segment_id"] == str(SEGMENT_ID)
    assert audience["version"] == 2
    assert audience["definition"]["conditions"][0]["field"] == "status"


def test_recipient_key_is_deterministic() -> None:
    campaign_id = uuid.uuid4()
    first = recipient_idempotency_key(campaign_id, "a@example.com")
    second = recipient_idempotency_key(campaign_id, "a@example.com")
    other = recipient_idempotency_key(campaign_id, "b@example.com")
    assert first == second
    assert first != other
    assert len(first) == 64


def test_ledger_row_is_queued_and_idempotent() -> None:
    campaign_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    row = ledger_row(campaign_id, contact_id=contact_id, normalized_email="a@example.com")
    assert row["campaign_id"] == campaign_id
    assert row["contact_id"] == contact_id
    assert row["email_snapshot"] == "a@example.com"
    assert row["status"] == RECIPIENT_STATUS_QUEUED
    assert row["idempotency_key"] == recipient_idempotency_key(campaign_id, "a@example.com")
