"""Red-team regression for #101: in demo mode the API serves only the demo personas.

References: R4 (one customer, set by the server); OWASP API1:2023 Broken Object Level Authorization;
OWASP LLM02 Sensitive Information Disclosure. A customer id that is not a persona of
core/config/personas.yaml gets the same 404 customer_not_found as an id that does not exist, from
configuration alone: no connection is taken, so nothing is read or written for it.
The database-backed part at the end is skipped without DATABASE_URL.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.app.api import deps
from core.app.api.errors import ApiError
from core.app.api.personas import load_personas
from core.app.main import create_app
from core.app.settings import Settings

PERSONA = "CUST00860"
NOT_A_PERSONA = "CUST00001"      # exists in the data
MISSING = "CUST99999"            # does not exist

ENDPOINTS = [   # every endpoint on main that names a customer: (method, path template, params template)
    ("GET", "/api/overview/{cid}", {}),
    ("GET", "/api/evidence/ev_0123456789ab", {"customer_id": "{cid}"}),
]


class SpyPool:
    """A pool that records every connection request and has no database behind it."""

    def __init__(self) -> None:
        self.taken = 0

    @contextmanager
    def connection(self, timeout=None):
        self.taken += 1
        raise RuntimeError("no database in this test")
        yield


def request(client, method, path, params, cid):
    return client.request(method, path.format(cid=cid), params={k: v.format(cid=cid) for k, v in params.items()})


@pytest.fixture
def client_with(clean_env):
    @contextmanager
    def make(**settings):
        with TestClient(create_app(Settings(_env_file=None, **settings)), raise_server_exceptions=False) as c:
            yield c
    return make


@pytest.mark.parametrize("method, path, params", ENDPOINTS)
def test_a_non_persona_gets_the_same_404_as_a_missing_id_without_the_database(client_with, method, path, params):
    with client_with() as client:
        pool = SpyPool()
        client.app.state.pool = pool
        not_a_persona = request(client, method, path, params, NOT_A_PERSONA)
        missing = request(client, method, path, params, MISSING)
        client.app.state.pool = None
    for response in (not_a_persona, missing):
        assert response.status_code == 404
        assert response.json() == {"error": {"code": "customer_not_found", "message": "We couldn't find this customer.",
                                             "retryable": False}}
    assert not_a_persona.content == missing.content       # a real customer cannot be told from a missing one
    assert pool.taken == 0                                 # refused before any connection


@pytest.mark.parametrize("method, path, params", ENDPOINTS)
def test_a_persona_passes_the_allowlist(client_with, method, path, params):
    with client_with() as client:                          # no database: the request reaches the data step
        response = request(client, method, path, params, PERSONA)
    assert response.status_code == 503 and response.json()["error"]["code"] == "data_unavailable"


@pytest.mark.parametrize("method, path, params", ENDPOINTS)
def test_demo_customers_all_widens_it_for_local_eval_runs(client_with, method, path, params):
    with client_with(demo_customers="all") as client:
        response = request(client, method, path, params, NOT_A_PERSONA)
    assert response.status_code == 503                     # past the allowlist; the database decides


def test_the_finnish_error_is_the_same_for_both(client_with):
    with client_with() as client:
        a = client.get(f"/api/overview/{NOT_A_PERSONA}", params={"lang": "fi"})
        b = client.get(f"/api/overview/{MISSING}", params={"lang": "fi"})
    assert a.status_code == b.status_code == 404 and a.content == b.content


def test_the_allowlist_is_the_personas_file():
    personas = {p["customer_id"] for p in load_personas()["personas"]}
    assert deps.served_customers(Settings(_env_file=None)) == personas == {
        "CUST00860", "CUST00493", "CUST00349", "CUST00849"}
    assert deps.served_customers(Settings(_env_file=None, demo_customers="all")) is None


def test_the_setting(clean_env):
    assert Settings(_env_file=None).demo_customers == "personas"            # default: personas only
    clean_env.setenv("DEMO_CUSTOMERS", "")
    assert Settings(_env_file=None).demo_customers == "personas"            # empty counts as unset
    clean_env.setenv("DEMO_CUSTOMERS", "all")
    assert Settings(_env_file=None).demo_customers == "all"
    clean_env.setenv("DEMO_CUSTOMERS", "everyone")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)                                             # a typo never opens it up


class CountingConn:
    def __init__(self, found: bool) -> None:
        self.found = found
        self.queries = 0

    def execute(self, sql, params=None):
        self.queries += 1
        found = self.found

        class _Res:
            def fetchone(self):
                return (1,) if found else None
        return _Res()


def test_a_found_customer_is_looked_up_once_per_process(monkeypatch):
    monkeypatch.setattr(deps, "_known_customers", set())
    conn = CountingConn(found=True)
    deps.require_customer(conn, PERSONA)
    deps.require_customer(conn, PERSONA)
    assert conn.queries == 1


def test_a_missing_customer_is_never_remembered(monkeypatch):
    monkeypatch.setattr(deps, "_known_customers", set())
    conn = CountingConn(found=False)
    for _ in range(2):
        with pytest.raises(ApiError):
            deps.require_customer(conn, PERSONA)
    assert conn.queries == 2 and deps._known_customers == set()


# ---- with the database (skipped without DATABASE_URL) ----------------------------------------------

def test_with_the_database_a_persona_is_served_and_others_are_not(clean_env):
    url = Settings().database_url
    if url is None:
        pytest.skip("DATABASE_URL is not set")
    with TestClient(create_app(Settings(_env_file=None, database_url=url.get_secret_value()))) as client:
        served = client.get(f"/api/overview/{PERSONA}")
        assert served.status_code == 200 and served.json()["customer_id"] == PERSONA
        ref = served.json()["cards"][0]["total"]["evidence_ref"]
        for method, path, params in ENDPOINTS + [("GET", f"/api/evidence/{ref}", {"customer_id": "{cid}"})]:
            a = request(client, method, path, params, NOT_A_PERSONA)
            b = request(client, method, path, params, MISSING)
            assert a.status_code == b.status_code == 404 and a.content == b.content, path
