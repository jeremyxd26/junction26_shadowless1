"""Red-team regressions for the public API without a database: object-level access and error bodies.

References: R4 (one customer, set by the server); OWASP API1:2023 Broken Object Level Authorization,
API8:2023 Security Misconfiguration. A test marked xfail(strict=True) records a confirmed gap with
its issue and fails the run once the gap is fixed, so the marker gets removed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("core.app.api", reason="the API endpoints are not on this branch yet")

from core.app.main import create_app  # noqa: E402
from core.app.settings import Settings  # noqa: E402

LEAK_MARKERS = ("Traceback", "File \"", "psycopg", "SELECT", "postgresql://", "sqlstate", "line ", "core/")


@pytest.fixture
def client(monkeypatch):
    for name in ("DATABASE_URL", "AUDIT_API"):
        monkeypatch.delenv(name, raising=False)
    with TestClient(create_app(Settings(_env_file=None)), raise_server_exceptions=False) as c:
        yield c


@pytest.mark.parametrize("method, path, body", [
    ("GET", "/api/evidence/ev_ZZZZZZZZZZZZ?customer_id=CUST00860", None),
    ("GET", "/api/evidence/..%2f..%2fetc%2fpasswd?customer_id=CUST00860", None),
    ("GET", "/api/evidence/ev_000000000000?customer_id=CUST00860'%20OR%201=1--", None),
    ("GET", "/api/evidence/ev_000000000000?customer_id=CUST00860&limit=100000", None),
    ("GET", "/api/evidence/ev_000000000000?customer_id=CUST00860&cursor=cur_99999999999999999999999999", None),
    ("GET", "/api/overview/CUST0086%00", None),
    ("GET", "/api/overview/%E2%80%8BCUST00860", None),
    ("POST", "/api/overview/CUST00860", None),
    ("GET", "/api/nope", None),
    ("POST", "/api/ask", b'{"customer_id":"CUST00860",'),
    ("POST", "/api/ask", b"\xff\xfe\x00"),
    ("POST", "/api/ask", b'[1,2,3]'),
    ("POST", "/api/ask", b'{"customer_id":"CUST00860","message":1e999}'),
])
def test_errors_are_the_envelope_and_leak_nothing(client, method, path, body):
    r = client.request(method, path, content=body, headers={"Content-Type": "application/json"})
    assert 400 <= r.status_code < 600
    if path.startswith("/api/"):
        assert set(r.json()) == {"error"} and set(r.json()["error"]) == {"code", "message", "retryable"}
    for marker in LEAK_MARKERS:
        assert marker not in r.text, marker


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_are_not_served_by_the_app(client, path):
    if client.get(path).status_code == 200:
        pytest.xfail("API docs are on in the app and hidden only by the proxy; issue #62")


@pytest.mark.xfail(strict=True, reason="demo mode serves every customer in the data, not only the personas; issue #101")
@pytest.mark.parametrize("path", ["/api/overview/CUST00001", "/api/evidence/ev_000000000000?customer_id=CUST00001"])
def test_demo_mode_serves_only_the_personas(client, path):
    """A customer who is not a demo persona is refused from configuration alone, before any database
    read, with the same 404 as an unknown id. Without a database the endpoints answer 503 today."""
    r = client.get(path)
    assert r.status_code == 404 and r.json()["error"]["code"] == "customer_not_found"
