from __future__ import annotations

from fastapi.testclient import TestClient

from core.app.main import create_app
from core.app.settings import Settings


def client_for(**settings) -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, **settings)))


class ExplodingPool:
    """Stands in for the pool and fails on any use."""

    def __getattr__(self, name):
        raise AssertionError(f"the database was touched: pool.{name}")


def test_healthz_without_database(clean_env):
    with client_for() as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "demo_today": "2026-09-30"}


def test_healthz_reports_demo_today(clean_env):
    clean_env.setenv("DEMO_TODAY", "2026-06-30")
    with client_for() as client:
        assert client.get("/healthz").json() == {"status": "ok", "demo_today": "2026-06-30"}


def test_healthz_never_touches_the_database(clean_env):
    with client_for() as client:
        client.app.state.pool = ExplodingPool()
        response = client.get("/healthz")
        client.app.state.pool = None
    assert response.status_code == 200


def test_readyz_without_database_url(clean_env):
    with client_for() as client:
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "reason": "DATABASE_URL is not set"}


def test_readyz_when_database_unreachable(clean_env, unreachable_db):
    with client_for(database_url=unreachable_db) as client:
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "reason": "database unreachable"}
    assert "not-a-real-password" not in response.text


def test_readyz_with_database(real_database_url):
    with TestClient(create_app(Settings(_env_file=None, database_url=real_database_url))) as client:
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_cors_allows_configured_origin_only(clean_env):
    clean_env.setenv("CORS_ORIGINS", "https://app.example")
    with client_for() as client:
        allowed = client.get("/healthz", headers={"Origin": "https://app.example"})
        other = client.get("/healthz", headers={"Origin": "https://evil.example"})
        preflight = client.options(
            "/healthz",
            headers={"Origin": "https://app.example", "Access-Control-Request-Method": "GET"},
        )
    assert allowed.headers.get("access-control-allow-origin") == "https://app.example"
    assert "access-control-allow-origin" not in other.headers
    assert preflight.status_code == 200
    assert preflight.headers.get("access-control-allow-origin") == "https://app.example"
