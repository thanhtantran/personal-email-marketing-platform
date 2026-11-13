"""Launch validation.

A launch fails loudly and early rather than enqueueing sends that policy or the
provider will reject. Checks cover content, sender identity, the segment
estimate, and marketing consent/suppression state (the eligible count already
excludes suppressed, unsubscribed and non-consented contacts). Provider
eligibility and capacity freshness are supplied by the caller; the gateway
wires real account checks in Stage 5.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db.models import Campaign, Segment, Template
from app.domain.audience.emails import normalize_email

CODE_MISSING_SUBJECT = "missing_subject"
CODE_MISSING_TEMPLATE = "missing_template"
CODE_TEMPLATE_ARCHIVED = "template_archived"
CODE_MISSING_SENDER_NAME = "missing_sender_name"
CODE_INVALID_FROM_EMAIL = "invalid_from_email"
CODE_INVALID_REPLY_TO = "invalid_reply_to"
CODE_MISSING_SEGMENT = "missing_segment"
CODE_NO_ELIGIBLE_RECIPIENTS = "no_eligible_recipients"
CODE_PROVIDER_NOT_ELIGIBLE = "provider_not_eligible"
CODE_STALE_CAPACITY = "stale_capacity"


@dataclass(frozen=True)
class LaunchIssue:
    code: str
    detail: str


@dataclass(frozen=True)
class LaunchCheck:
    ok: bool
    issues: list[LaunchIssue]

    def as_extra(self) -> dict:
        return {"issues": [{"code": issue.code, "detail": issue.detail} for issue in self.issues]}


def validate_launch(
    campaign: Campaign,
    *,
    template: Template | None,
    segment: Segment | None,
    eligible_recipients: int,
    provider_eligible: bool,
    capacity_fresh: bool,
) -> LaunchCheck:
    """Return the issues that block a launch, or an empty list when it is legal."""
    issues: list[LaunchIssue] = []

    if not campaign.subject.strip():
        issues.append(LaunchIssue(CODE_MISSING_SUBJECT, "Campaign has no subject"))
    if campaign.template_id is None or template is None:
        issues.append(LaunchIssue(CODE_MISSING_TEMPLATE, "Campaign has no template"))
    elif template.status == "archived":
        issues.append(LaunchIssue(CODE_TEMPLATE_ARCHIVED, "Campaign template is archived"))

    if not campaign.from_name.strip():
        issues.append(LaunchIssue(CODE_MISSING_SENDER_NAME, "Campaign has no sender name"))
    if normalize_email(campaign.from_email) is None:
        issues.append(LaunchIssue(CODE_INVALID_FROM_EMAIL, "Sender address is not a valid email"))
    if campaign.reply_to and normalize_email(campaign.reply_to) is None:
        issues.append(LaunchIssue(CODE_INVALID_REPLY_TO, "Reply-to address is not a valid email"))

    if campaign.segment_id is None or segment is None:
        issues.append(LaunchIssue(CODE_MISSING_SEGMENT, "Campaign has no audience segment"))
    elif eligible_recipients <= 0:
        issues.append(
            LaunchIssue(
                CODE_NO_ELIGIBLE_RECIPIENTS,
                "Segment has no eligible, consented, non-suppressed recipients",
            )
        )

    if not provider_eligible:
        issues.append(
            LaunchIssue(
                CODE_PROVIDER_NOT_ELIGIBLE,
                "No provider account is verified for marketing sends",
            )
        )
    if not capacity_fresh:
        issues.append(
            LaunchIssue(CODE_STALE_CAPACITY, "Provider capacity snapshot is stale or unknown")
        )

    return LaunchCheck(ok=not issues, issues=issues)
