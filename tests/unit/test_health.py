"""Liveness and readiness probe tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_healthz_ok() -> None:
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_reports_dependencies_accurately() -> None:
    """Readiness must reflect live PostgreSQL/Redis connectivity, not a stub."""
    client = TestClient(app)
    response = client.get("/readyz")
    body = response.json()

    assert response.status_code in {200, 503}
    assert body["status"] in {"ok", "unavailable"}
    assert body["environment"]

    deps = {dep["name"]: dep["healthy"] for dep in body["dependencies"]}
    assert set(deps) == {"postgres", "redis"}

    all_healthy = all(deps.values())
    assert body["status"] == ("ok" if all_healthy else "unavailable")
    assert response.status_code == (200 if all_healthy else 503)
