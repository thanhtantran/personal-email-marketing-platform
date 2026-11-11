"""TemplateService renders through one pipeline: personalize, render, sanitize."""

from __future__ import annotations

import uuid

import pytest

from app.config import Settings
from app.db.models import Template
from app.domain.content.template_service import TemplateService
from app.errors import ValidationAppError

SOURCE = (
    "<mjml><mj-body><mj-section><mj-column>"
    '<mj-text>Hi {{ first_name | default: "there" }}</mj-text>'
    "</mj-column></mj-section></mj-body></mjml>"
)

# Raw renderer output includes unsafe markup on purpose: the pipeline must
# remove it before the HTML is ever stored.
RAW_HTML = '<html><body><script>alert(1)</script><p onclick="x()">Hi there</p></body></html>'


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


def _settings() -> Settings:
    return Settings(app_env="development")


@pytest.fixture
def patched_render(monkeypatch: pytest.MonkeyPatch):
    def fake_render(source: str, *, binary: str, timeout: int) -> str:
        return RAW_HTML

    monkeypatch.setattr("app.domain.content.template_service.render_mjml", fake_render)
    return fake_render


async def test_create_stores_sanitized_render(patched_render) -> None:
    service = TemplateService(FakeSession(), uuid.uuid4(), _settings())
    template = await service.create(name="Welcome", editor_json={}, mjml_source=SOURCE)
    assert template.version == 1
    assert template.status == "draft"
    assert "script" not in template.html.lower()
    assert "onclick" not in template.html.lower()
    assert "Hi there" in template.html
    assert template.text_body.strip() == "Hi there"


async def test_create_rejects_unknown_personalization(patched_render) -> None:
    service = TemplateService(FakeSession(), uuid.uuid4(), _settings())
    with pytest.raises(ValidationAppError):
        await service.create(
            name="Bad",
            editor_json={},
            mjml_source="<mjml><mj-body><mj-text>{{ secret }}</mj-text></mj-body></mjml>",
        )


async def test_create_rejects_unsupported_status(patched_render) -> None:
    service = TemplateService(FakeSession(), uuid.uuid4(), _settings())
    with pytest.raises(ValidationAppError):
        await service.create(
            name="Bad", editor_json={}, mjml_source=SOURCE, status="nonsense"
        )


async def test_update_bumps_version_only_when_source_changes(patched_render) -> None:
    service = TemplateService(FakeSession(), uuid.uuid4(), _settings())
    template = await service.create(name="Welcome", editor_json={}, mjml_source=SOURCE)

    await service.update(template, name="Renamed")
    assert template.version == 1
    assert template.name == "Renamed"

    new_source = SOURCE.replace("Hi", "Hello")
    await service.update(template, mjml_source=new_source)
    assert template.version == 2


def test_render_reports_fallbacks(patched_render) -> None:
    template = Template(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="Welcome",
        editor_json={},
        mjml_source=SOURCE,
        html="",
        text_body="",
        version=3,
        status="draft",
    )
    service = TemplateService(FakeSession(), template.tenant_id, _settings())
    outcome = service.render(template, {})
    assert outcome.version == 3
    assert outcome.used_fallback == ["first_name"]
    assert outcome.missing == []
    assert "script" not in outcome.html.lower()
