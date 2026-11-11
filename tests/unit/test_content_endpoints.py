"""Template endpoints must resolve the workspace from a server-side session."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _client() -> TestClient:
    return TestClient(app)


def test_list_templates_requires_authentication() -> None:
    response = _client().get("/api/v1/templates")
    assert response.status_code == 401
    assert response.json()["title"] == "unauthenticated"


def test_create_template_requires_authentication() -> None:
    response = _client().post(
        "/api/v1/templates",
        json={"name": "Welcome", "mjml_source": "<mjml></mjml>"},
    )
    assert response.status_code == 401


def test_render_template_requires_authentication() -> None:
    response = _client().post(
        "/api/v1/templates/00000000-0000-0000-0000-000000000000/render",
        json={"values": {}},
    )
    assert response.status_code == 401


def test_test_send_requires_authentication() -> None:
    response = _client().post(
        "/api/v1/templates/00000000-0000-0000-0000-000000000000/test-send",
        json={"recipient": "owner@example.com", "subject": "Hi"},
    )
    assert response.status_code == 401
