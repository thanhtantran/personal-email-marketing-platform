"""Campaign endpoints must resolve the workspace from a server-side session."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

CAMPAIGN_ID = "00000000-0000-0000-0000-000000000000"


def _client() -> TestClient:
    return TestClient(app)


def test_list_campaigns_requires_authentication() -> None:
    response = _client().get("/api/v1/campaigns")
    assert response.status_code == 401
    assert response.json()["title"] == "unauthenticated"


def test_create_campaign_requires_authentication() -> None:
    response = _client().post("/api/v1/campaigns", json={"name": "Welcome"})
    assert response.status_code == 401


def test_get_campaign_requires_authentication() -> None:
    response = _client().get(f"/api/v1/campaigns/{CAMPAIGN_ID}")
    assert response.status_code == 401


def test_update_campaign_requires_authentication() -> None:
    response = _client().patch(f"/api/v1/campaigns/{CAMPAIGN_ID}", json={"subject": "Hi"})
    assert response.status_code == 401


def test_validate_campaign_requires_authentication() -> None:
    response = _client().post(f"/api/v1/campaigns/{CAMPAIGN_ID}/validate")
    assert response.status_code == 401


def test_schedule_campaign_requires_authentication() -> None:
    response = _client().post(f"/api/v1/campaigns/{CAMPAIGN_ID}/schedule", json={})
    assert response.status_code == 401


def test_launch_campaign_requires_authentication() -> None:
    response = _client().post(f"/api/v1/campaigns/{CAMPAIGN_ID}/launch")
    assert response.status_code == 401


def test_pause_and_resume_require_authentication() -> None:
    assert _client().post(f"/api/v1/campaigns/{CAMPAIGN_ID}/pause").status_code == 401
    assert _client().post(f"/api/v1/campaigns/{CAMPAIGN_ID}/resume").status_code == 401


def test_cancel_campaign_requires_authentication() -> None:
    response = _client().post(f"/api/v1/campaigns/{CAMPAIGN_ID}/cancel")
    assert response.status_code == 401


def test_list_recipients_requires_authentication() -> None:
    response = _client().get(f"/api/v1/campaigns/{CAMPAIGN_ID}/recipients")
    assert response.status_code == 401
