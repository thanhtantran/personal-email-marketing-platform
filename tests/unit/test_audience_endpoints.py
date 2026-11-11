"""Audience endpoints must reject requests without a server-side session."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _client() -> TestClient:
    return TestClient(app)


def test_list_contacts_requires_authentication() -> None:
    response = _client().get("/api/v1/contacts")
    assert response.status_code == 401
    assert response.json()["title"] == "unauthenticated"


def test_list_segments_requires_authentication() -> None:
    response = _client().get("/api/v1/segments")
    assert response.status_code == 401


def test_create_import_requires_authentication() -> None:
    response = _client().post("/api/v1/imports", json={"mapping": {"email": "email"}})
    assert response.status_code == 401


def test_export_contacts_requires_authentication() -> None:
    response = _client().get("/api/v1/contacts/export")
    assert response.status_code == 401
