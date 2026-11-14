"""Red-team regressions for the public API without a database: object-level access and error bodies.

References: R4 (one customer, set by the server); OWASP API1:2023 Broken Object Level Authorization,
API8:2023 Security Misconfiguration. A test marked xfail(strict=True) records a confirmed gap with
its issue and fails the run once the gap is fixed, so the marker gets removed.
"""

from __future__ import annotations

import importlib
import importlib.util

import pytest
from fastapi.testclient import TestClient

# Skip only when the API package is not on the branch; any other import error fails the run.
if importlib.util.find_spec("core.app.api") is None or importlib.util.find_spec("core.app.api.texts") is None:
    pytest.skip("the API endpoints are not on this branch yet", allow_module_level=True)

from core.app.api import texts  # noqa: E402
from core.app.main import create_app  # noqa: E402
from core.app.settings import Settings  # noqa: E402

LEAK_MARKERS = ("Traceback", "File \"", "psycopg", "SELECT", "postgresql://", "sqlstate", "line ", "core/")


def fixed_error_texts() -> set[str]:
    """Every error message the contract allows: the API's catalogue, and the ask endpoint's and the
    pipeline's own texts when the answer pipeline is on the branch. Nothing else may be a message."""
    allowed = {text for pair in texts.ERRORS.values() for text in pair}
    if importlib.util.find_spec("core.agent") is not None and importlib.util.find_spec("core.agent.api") is not None:
        ask_api = importlib.import_module("core.agent.api")
        allowed |= set(getattr(ask_api, "ERROR_TEXT", {}).values())
        orchestrator = importlib.import_module("core.agent.orchestrator")
        for pair, _ in getattr(orchestrator, "ERRORS", {}).values():
            allowed |= set(pair)
    return allowed


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
    assert set(r.json()) == {"error"} and set(r.json()["error"]) == {"code", "message", "retryable"}
    # The message is one of the fixed texts: no exception, driver or validation text can reach it.
    assert r.json()["error"]["message"] in fixed_error_texts()
    for marker in LEAK_MARKERS:
        assert marker not in r.text, marker


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])  # fixed by #62: off unless API_DOCS=1
def test_api_docs_are_not_served_by_the_app(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", ["/api/overview/CUST00001", "/api/evidence/ev_000000000000?customer_id=CUST00001"])
def test_demo_mode_serves_only_the_personas(client, path):
    r = client.get(path)
    assert r.status_code == 404 and r.json()["error"]["code"] == "customer_not_found"
    persona = client.get(path.replace("CUST00001", "CUST00860"))
    assert persona.status_code != 404          # the 404 comes from the persona check, not from the data
