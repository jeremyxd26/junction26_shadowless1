"""API endpoints without a database: routing, validation, error envelopes, personas, the hero, what-if."""

from __future__ import annotations

import copy
import logging
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from core.app.api import deps, overview, whatif
from core.app.api.schemas import ErrorResponse, OverviewResponse, PersonasResponse
from core.app.main import create_app
from core.app.settings import Settings
from core.tools import aliases, config
from core.tools.context import ToolContext
from core.tools.db import Tx
from core.tools.models import Card, Number, Period, ToolResult
from core.tools.safe_to_spend import get_safe_to_spend


def client_for(**settings) -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, **settings)), raise_server_exceptions=False)


def assert_envelope(response, status: int, code: str, retryable: bool = False) -> None:
    assert response.status_code == status, response.text
    body = ErrorResponse.model_validate(response.json())
    assert (body.error.code, body.error.retryable) == (code, retryable)
    assert set(response.json()) == {"error"} and set(response.json()["error"]) == {"code", "message", "retryable"}


# ---- personas ------------------------------------------------------------------------------------

def test_personas_from_the_yaml_lead_first(clean_env):
    with client_for() as client:
        response = client.get("/api/personas")
    assert response.status_code == 200
    body = PersonasResponse.model_validate(response.json())
    assert [p.customer_id for p in body.personas] == ["CUST00860", "CUST00493", "CUST00349", "CUST00849"]
    assert (body.as_of, body.language, body.personas[0].display_name) == (date(2026, 9, 30), "en", "Sanna")
    keys = {"customer_id", "display_name", "age_band", "postal_area", "profile", "tagline", "default_language"}
    assert all(set(p) == keys for p in response.json()["personas"])  # no team notes (why, lead, age, ...)


def test_personas_in_finnish(clean_env):
    with client_for() as client:
        body = client.get("/api/personas", params={"lang": "fi"}).json()
    assert body["language"] == "fi"
    assert {p["profile"]["key"]: p["profile"]["label"] for p in body["personas"]}["steady"] == "Vakaa"


# ---- validation and errors ---------------------------------------------------------------------------

@pytest.mark.parametrize("path, params", [
    ("/api/personas", {"lang": "de"}),
    ("/api/overview/customer-1", {}),
    ("/api/overview/CUST00860", {"lang": "sv"}),
    ("/api/evidence/ev_123", {"customer_id": "CUST00860"}),                 # malformed ref
    ("/api/evidence/ev_0123456789ab", {}),                                   # customer_id missing
    ("/api/evidence/ev_0123456789ab", {"customer_id": "CUST00860", "limit": 0}),
    ("/api/evidence/ev_0123456789ab", {"customer_id": "CUST00860", "limit": 201}),
    ("/api/evidence/ev_0123456789ab", {"customer_id": "CUST00860", "cursor": "page2"}),
    ("/api/evidence/ev_0123456789ab", {"customer_id": "CUST00860", "cursor": "cur_1234567"}),   # 7 digits
    ("/api/evidence/ev_0123456789ab", {"customer_id": "CUST00860", "cursor": "cur_" + "9" * 5000}),
])
def test_bad_parameters_are_400_invalid_request(clean_env, path, params):
    with client_for() as client:
        assert_envelope(client.get(path, params=params), 400, "invalid_request")


def test_messages_are_localised(clean_env):
    with client_for() as client:
        fi = client.get("/api/overview/CUST00860", params={"lang": "fi"}).json()["error"]["message"]
    assert fi == "Tietosi eivät ole juuri nyt saatavilla. Yritä uudelleen."


@pytest.mark.parametrize("path, params", [
    ("/api/overview/CUST00860", {}),
    ("/api/evidence/ev_0123456789ab", {"customer_id": "CUST00860"}),
])
def test_without_database_503_data_unavailable(clean_env, path, params):
    with client_for() as client:
        assert_envelope(client.get(path, params=params), 503, "data_unavailable", retryable=True)


def test_unreachable_database_is_503_without_connection_details(clean_env, unreachable_db, monkeypatch):
    monkeypatch.setattr(deps, "POOL_TIMEOUT_S", 0.5)
    with client_for(database_url=unreachable_db) as client:
        response = client.get("/api/overview/CUST00860")
    assert_envelope(response, 503, "data_unavailable", retryable=True)
    assert "not-a-real-password" not in response.text and "127.0.0.1" not in response.text


class _FakeConn:
    """Enough of a connection for the request path before the tools run."""

    def execute(self, sql, params=None):
        class _Res:
            def fetchone(self):
                return (1,)

        return _Res()


class _FakePool:
    @contextmanager
    def connection(self, timeout=None):
        yield _FakeConn()


def test_unexpected_error_is_500_internal_without_its_text(clean_env, monkeypatch):
    def boom(ctx, hero_tool=None):
        raise RuntimeError("secret detail that must not leak")

    monkeypatch.setattr(overview, "build", boom)
    with client_for() as client:
        client.app.state.pool = _FakePool()
        response = client.get("/api/overview/CUST00860")
        client.app.state.pool = None
    assert_envelope(response, 500, "internal", retryable=True)
    assert "secret" not in response.text


CANARY = "postgresql://canary_user:canary_pw@canary-host.example/canary_db"


def test_unhandled_exception_text_reaches_neither_the_log_nor_the_body(clean_env, monkeypatch, caplog):
    """The exception is caught without re-raising: Starlette's 500 handler would log the traceback."""
    def boom(ctx, hero_tool=None):
        raise RuntimeError(f"connection failed: {CANARY}")

    monkeypatch.setattr(overview, "build", boom)
    caplog.set_level(logging.DEBUG)  # every logger, every level
    app = create_app(Settings(_env_file=None))
    with TestClient(app) as client:  # raise_server_exceptions=True: a re-raised exception would fail here
        client.app.state.pool = _FakePool()
        response = client.get("/api/overview/CUST00860", headers={"Origin": "http://localhost:5173"})
        client.app.state.pool = None
    assert_envelope(response, 500, "internal", retryable=True)
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"  # inside CORS
    request_id = response.headers["x-request-id"]
    logged = "\n".join(caplog.text.splitlines() + [r.exc_text or "" for r in caplog.records])
    assert "canary" not in logged and "canary" not in response.text
    assert f"(RuntimeError), request {request_id}" in caplog.text


@pytest.mark.parametrize("method, path, status", [
    ("GET", "/api/no-such-route", 404),
    ("GET", "/nothing/here", 404),
    ("POST", "/api/personas", 405),
    ("DELETE", "/api/overview/CUST00860", 405),
])
def test_unknown_routes_and_methods_get_the_envelope(clean_env, method, path, status):
    with client_for() as client:
        response = client.request(method, path)
    assert_envelope(response, status, "invalid_request")
    if status == 405:
        assert "GET" in response.headers["allow"]


# ---- the hero switch (no database: synthetic history and an in-memory evidence store) -------------

class _FakeStore:
    def __init__(self):
        self.rows = {}

    def cursor(self):
        store = self

        class _Cur:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def executemany(self, sql, params):
                for ref, _customer, spec in params:
                    store.rows.setdefault(ref, spec.obj)

        return _Cur()

    def execute(self, sql, params):
        class _Res:
            def __init__(self, rows):
                self._rows = rows

            def fetchall(self):
                return self._rows

        return _Res([(r, self.rows[r]) for r in params[0] if r in self.rows])


def _history() -> list[Tx]:
    h, i = [], 0
    for m in range(4, 10):
        for day, cat, typ, amt, merchant, mcc in [
            (4, "Housing", "housing_payment", "-800.00", None, None),
            (15, "Salary", "salary", "2500.00", None, None),
            (9, "Groceries", "purchase", "-60.00", "MRC-GRO-0001", "5411"),
            (20, "Restaurants", "purchase", "-30.00", "MRC-RES-0001", "5812"),
        ]:
            i += 1
            d = date(2026, m, day)
            h.append(Tx(i, d, datetime.combine(d, datetime.min.time()), cat, typ, merchant, mcc, Decimal(amt)))
    return h


def _ctx() -> ToolContext:
    return ToolContext(customer_id="CUST00860", as_of=date(2026, 9, 30), conn=_FakeStore(), _history=_history())


def _stub_hero(ctx, args) -> ToolResult:
    period = Period(start=date(2026, 10, 1), end=date(2026, 10, 7), label="Next 7 days")
    primary = Number(value=184.68, unit="eur", period=period, method="safe_to_spend.safe_to_spend_7d_eur@1",
                     evidence_ref="ev_0123456789ab", label="Safe to spend", display="€184.68", id="n1")
    card = Card(card_id="card_sts", type="metric", title="Safe to spend in the next 7 days", subtitle="1 to 7 October",
                evidence_ref="ev_0123456789ab", estimate={"label": "Estimate", "text": "An estimate."}, actions=[],
                status="ok", primary=primary, secondary=[], comparison=None, components=[])
    return ToolResult(tool="get_safe_to_spend", data={}, card=card)


def test_the_hero_comes_from_get_safe_to_spend():
    assert overview.HERO_TOOL is get_safe_to_spend
    body = overview.build(_ctx(), hero_tool=_stub_hero)  # the stub stands in for the metric SQL
    assert [c.type for c in body.cards] == ["breakdown", "bills"]
    assert body.greeting == "Hi Sanna" and len(body.suggested_questions) == 4 and body.insights == []
    assert body.reviews == []  # contract 0.2.0: an empty list, not an absent field, until #68


def test_hero_is_the_tools_metric_card():
    body = overview.build(_ctx(), hero_tool=_stub_hero)
    assert body.hero.type == "metric" and body.hero.status == "ok" and body.hero.primary.value == 184.68
    dumped = OverviewResponse.model_validate(body.model_dump(mode="json")).model_dump(mode="json")
    assert "id" not in dumped["hero"]["primary"]                       # tool-internal number ids are dropped
    assert "typical_day" not in dumped["cards"][1]["items"][0]         # extra tool fields are dropped


# ---- POST /api/whatif (no database: validation and the mapping of the tool's refusals) ------------

WHATIF = {"customer_id": "CUST00860", "language": "en",
          "scenario": {"selection": {"kind": "category", "value": "Restaurants"}, "cut_pct": 20}}


def whatif_body(selection=None, **scenario) -> dict:
    body = copy.deepcopy(WHATIF)
    if selection is not None:
        body["scenario"]["selection"] = selection
    body["scenario"].update(scenario)
    return body


@pytest.mark.parametrize("body", [
    {},
    {k: v for k, v in WHATIF.items() if k != "scenario"},
    {k: v for k, v in WHATIF.items() if k != "customer_id"},
    {**WHATIF, "customer_id": "customer-1"},
    {**WHATIF, "language": "de"},
    whatif_body(cut_pct=0),
    whatif_body(cut_pct=101),
    whatif_body(cut_pct="20"),                                   # a whole number, not a string
    whatif_body(cut_pct=20.5),
    whatif_body(cut_pct=None),
    whatif_body(selection={"kind": "store", "value": "Restaurants"}),
    whatif_body(selection={"kind": "category", "value": ""}),
    whatif_body(selection={"kind": "category"}),
])
def test_whatif_bad_requests_are_400(clean_env, body):
    with client_for() as client:
        assert_envelope(client.post("/api/whatif", json=body), 400, "invalid_request")


def test_whatif_body_that_is_not_json_is_400(clean_env):
    with client_for() as client:
        response = client.post("/api/whatif", content=b"cut_pct=20", headers={"content-type": "application/json"})
    assert_envelope(response, 400, "invalid_request")


def test_whatif_without_database_is_503(clean_env):
    with client_for() as client:
        assert_envelope(client.post("/api/whatif", json=WHATIF), 503, "data_unavailable", retryable=True)


def _post_whatif(monkeypatch, body, tool):
    monkeypatch.setattr(whatif, "run_what_if", tool)
    monkeypatch.setattr(ToolContext, "history", lambda self: _history())
    with client_for() as client:
        client.app.state.pool = _FakePool()
        response = client.post("/api/whatif", json=body)
        client.app.state.pool = None
    return response


@pytest.mark.parametrize("selection", [
    {"kind": "category", "value": "Health"},                                     # R9
    {"kind": "mcc", "value": sorted(config.MCC_GROUPS["health"])[0]},             # R9
    {"kind": "category", "value": "Salary"},                                     # not spending
    {"kind": "basket", "value": "luxuries"},
    {"kind": "mcc", "value": "taxi"},
    {"kind": "merchant", "value": "MRC-XXX-9999"},                               # not this customer's
])
def test_whatif_selections_refused_before_the_tool_are_422(clean_env, monkeypatch, selection):
    called = []
    response = _post_whatif(monkeypatch, whatif_body(selection), lambda ctx, args: called.append(args))
    assert_envelope(response, 422, "invalid_scenario")
    assert called == []
    assert "Health" not in response.text and "R9" not in response.text


def test_whatif_refusals_of_the_tool_are_422_without_their_text(clean_env, monkeypatch):
    def no_spending(ctx, args):
        raise ValueError("invalid_scenario: the selection has no spending in the last 6 full months")

    response = _post_whatif(monkeypatch, WHATIF, no_spending)
    assert_envelope(response, 422, "invalid_scenario")
    assert "spending" not in response.text


def test_whatif_maps_a_merchant_id_to_the_customers_alias(clean_env, monkeypatch):
    seen = []

    def capture(ctx, args):
        seen.append((ctx.customer_id, ctx.language, args))
        raise ValueError("stop here")

    _post_whatif(monkeypatch, {**whatif_body({"kind": "merchant", "value": "MRC-RES-0001"}), "language": "fi"},
                 capture)
    customer, language, args = seen[0]
    alias = aliases.build(_history(), date(2026, 9, 30)).for_merchant("MRC-RES-0001").key
    assert (customer, language, args.selection.kind, args.selection.value, args.cut_pct) == (
        "CUST00860", "fi", "merchant", alias, 20)
