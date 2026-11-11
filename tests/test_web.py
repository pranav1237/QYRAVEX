# ruff: noqa: I001
from fastapi.testclient import TestClient

from workbridge.web import app


client = TestClient(app)


def test_dashboard_is_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "WorkBridge" in response.text
    assert "Research desk" in response.text


def test_dashboard_assets_are_served():
    response = client.get("/app.js")
    assert response.status_code == 200
    assert "runResearch" in response.text


def test_benchmark_api_returns_all_challenges():
    response = client.get("/api/benchmarks")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 8
    assert payload["passed"] == 8
