"""Template lifecycle: validation, rendering, sanitization and versioning.

Rendering is centralized here so ``create``, ``update`` and ``render`` can never
disagree: the stored ``html``/``text_body`` and any preview come from the same
pipeline (IMPLEMENTATION_PLAN Stage 3 exit gate).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Template
from app.domain.content.editor import validate_editor_json, validate_mjml_source
from app.domain.content.mjml import render_mjml
from app.domain.content.personalization import render as render_personalization
from app.domain.content.personalization import validate_variables
from app.domain.content.text import html_to_text
from app.errors import ValidationAppError
from app.security.sanitize import sanitize_html

TEMPLATE_STATUSES: tuple[str, ...] = ("draft", "published", "archived")


@dataclass
class RenderOutcome:
    html: str
    text: str
    missing: list[str] = field(default_factory=list)
    used_fallback: list[str] = field(default_factory=list)
    version: int = 1


class TemplateService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID, settings: Settings) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.settings = settings

    # ------------------------------------------------------------------ render
    def _render_pipeline(
        self, mjml_source: str, values: Mapping[str, str]
    ) -> tuple[str, str, list[str], list[str]]:
        """Personalize, render, sanitize and derive text from MJML source."""
        validate_variables(mjml_source)
        personalized = render_personalization(mjml_source, values, escape=True)
        source = validate_mjml_source(
            personalized.body, max_bytes=self.settings.template_max_source_bytes
        )
        raw_html = render_mjml(
            source,
            binary=self.settings.mjml_binary,
            timeout=self.settings.mjml_timeout_seconds,
        )
        html = sanitize_html(raw_html)
        if not html.strip():
            raise ValidationAppError(
                "Rendering produced no content", extra={"reason": "render_empty"}
            )
        return html, html_to_text(html), personalized.missing, personalized.used_fallback

    def prepare(
        self, *, editor_json: object, mjml_source: object
    ) -> tuple[dict, str, str, str]:
        """Validate source and produce the default (unpersonalized) render."""
        editor = validate_editor_json(editor_json)
        source = validate_mjml_source(
            mjml_source, max_bytes=self.settings.template_max_source_bytes
        )
        html, text, _, _ = self._render_pipeline(source, {})
        return editor, source, html, text

    def render(self, template: Template, values: Mapping[str, str]) -> RenderOutcome:
        html, text, missing, fallback = self._render_pipeline(template.mjml_source, values)
        return RenderOutcome(
            html=html,
            text=text,
            missing=missing,
            used_fallback=fallback,
            version=template.version,
        )

    # ------------------------------------------------------------------ lifecycle
    async def create(
        self,
        *,
        name: str,
        editor_json: object,
        mjml_source: object,
        status: str = "draft",
    ) -> Template:
        if status not in TEMPLATE_STATUSES:
            raise ValidationAppError(
                "Unsupported template status",
                extra={"reason": "invalid_template_status", "allowed": list(TEMPLATE_STATUSES)},
            )
        editor, source, html, text = self.prepare(editor_json=editor_json, mjml_source=mjml_source)
        template = Template(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            name=name,
            editor_json=editor,
            mjml_source=source,
            html=html,
            text_body=text,
            version=1,
            status=status,
        )
        self.session.add(template)
        await self.session.flush()
        return template

    async def update(
        self,
        template: Template,
        *,
        name: str | None = None,
        editor_json: object | None = None,
        mjml_source: object | None = None,
        status: str | None = None,
    ) -> Template:
        if status is not None and status not in TEMPLATE_STATUSES:
            raise ValidationAppError(
                "Unsupported template status",
                extra={"reason": "invalid_template_status", "allowed": list(TEMPLATE_STATUSES)},
            )
        if editor_json is not None or mjml_source is not None:
            effective_editor = template.editor_json if editor_json is None else editor_json
            effective_source = template.mjml_source if mjml_source is None else mjml_source
            editor, source, html, text = self.prepare(
                editor_json=effective_editor, mjml_source=effective_source
            )
            changed = source != template.mjml_source or editor != template.editor_json
            template.editor_json = editor
            template.mjml_source = source
            template.html = html
            template.text_body = text
            if changed:
                template.version = template.version + 1
        if name is not None:
            template.name = name
        if status is not None:
            template.status = status
        await self.session.flush()
        return template
