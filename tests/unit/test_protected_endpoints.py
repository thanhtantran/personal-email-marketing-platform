"""Protected endpoints must deny requests without a server-side session.

Tenant context is resolved from the session cookie and membership records, never
from request bodies or headers. A request with no cookie must be rejected before
any database access.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_me_requires_authentication() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["title"] == "unauthenticated"
    assert body["type"].endswith("#unauthenticated")
    assert body["status"] == 401


def test_workspace_requires_authentication() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/workspace")
    assert response.status_code == 401
    assert response.json()["title"] == "unauthenticated"


def test_logout_without_session_is_rejected() -> None:
    client = TestClient(app)
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 401
    assert response.json()["title"] == "unauthenticated"
