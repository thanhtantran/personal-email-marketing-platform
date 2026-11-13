"""Immutable campaign snapshots.

At launch the content and audience definition are copied into a snapshot row.
Dispatch reads the snapshot, never the live template or segment, so editing or
archiving a template after launch cannot change an in-flight campaign's content
or its resolved audience definition (SPEC.md invariant 7).
"""

from __future__ import annotations

from app.db.models import Campaign, Segment, Template


def build_content_snapshot(campaign: Campaign, template: Template | None) -> dict:
    """Freeze the sender identity and rendered content of the campaign.

    ``mjml_source`` is kept so per-recipient personalization can be re-rendered
    at dispatch from the same frozen source, never from the live template.
    """
    return {
        "subject": campaign.subject,
        "from_name": campaign.from_name,
        "from_email": campaign.from_email,
        "reply_to": campaign.reply_to,
        "template_id": str(campaign.template_id) if campaign.template_id else None,
        "template_version": template.version if template is not None else campaign.template_version,
        "mjml_source": template.mjml_source if template is not None else "",
        "html": template.html if template is not None else "",
        "text_body": template.text_body if template is not None else "",
    }


def build_audience_snapshot(segment: Segment | None) -> dict:
    """Freeze the audience definition AST used to resolve recipients."""
    return {
        "segment_id": str(segment.id) if segment is not None else None,
        "version": segment.version if segment is not None else None,
        "definition": dict(segment.definition) if segment is not None else {},
    }
