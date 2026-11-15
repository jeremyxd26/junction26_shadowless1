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
from core.app.api.errors import ApiError
from core.app.api.schemas import ErrorResponse, OverviewResponse, PersonasResponse
from core.app.main import create_app
from core.app.settings import Settings
from core.tools import aliases, config, safe_to_spend
from core.tools.context import ToolContext
from core.tools.db import Tx
from core.tools.models import Card, Number, Period, ToolResult
from core.tools.safe_to_spend import BillsDueMismatch, NoTransactions, get_safe_to_spend
from core.tools.what_if import WhatIfRefused


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
    def boom(*args, **kwargs):
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
    def boom(*args, **kwargs):
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
    assert_envelope(response, status, "not_found" if status == 404 else "invalid_request")
    if status == 405:
        assert "GET" in response.headers["allow"]


def test_a_path_with_a_line_break_cannot_forge_a_log_line(clean_env, caplog):
    app = create_app(Settings(_env_file=None))

    @app.get("/api/boom/{rest}")  # a str parameter matches [^/]+, which includes a decoded line break
    def boom(rest: str):
        raise RuntimeError("boom")

    caplog.set_level(logging.DEBUG)
    with TestClient(app) as client:
        response = client.get("/api/boom/a%0d%0aERROR:%20FAKE")
    assert_envelope(response, 500, "internal", retryable=True)
    lines = [r.getMessage() for r in caplog.records if "unhandled error" in r.getMessage()]
    assert len(lines) == 1 and "\n" not in lines[0] and "\r" not in lines[0]
    assert "\\r\\nERROR: FAKE" in lines[0]  # shown escaped, inside the one line


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


# The row of 03_safe_to_spend.sql for Sanna (contracts/api.md `card.safe_to_save`), as metric_row caches
# it on the context: the safe-to-save tool then runs without a database.
SANNA_03_ROW = {
    "free_month_eur": Decimal("783.79"), "everyday_month_eur": Decimal("599.18"),
    "safe_to_save_monthly_eur": Decimal("184.61"), "essentials_shortfall_month_eur": Decimal("0.00"),
    "free_until_payday_eur": Decimal("12567.56"), "everyday_until_payday_eur": Decimal("295.28"),
    "safe_to_save_eur": Decimal("12272.28"), "save_reason": None, "save_reason_category": None,
    "save_reason_month_eur": None, "next_payday": date(2026, 10, 15), "salary_status": "received_this_month",
    # the weekly figure after the savings goal (#391): "Needed" keeps the goal at 360
    "week_start": date(2026, 10, 1), "week_end": date(2026, 10, 7), "balance_limit_7d_eur": Decimal("5864.86"),
    "budget_limit_7d_eur": Decimal("97.46"), "safe_to_spend_7d_eur": Decimal("97.46"),
    "savings_goal_eur": Decimal("360.00"),
}


NO_ROW = object()   # 03 returns no row for the customer (no transactions up to as_of)


def _ctx(row: dict | object = SANNA_03_ROW) -> ToolContext:
    ctx = ToolContext(customer_id="CUST00860", as_of=date(2026, 9, 30), conn=_FakeStore(), _history=_history())
    ctx._labels = {}   # no labels: the context reads no reviews table
    ctx.shared[safe_to_spend.row_key(ctx, safe_to_spend.settings_for(ctx))] = None if row is NO_ROW else row
    return ctx


def _stub_hero(ctx, args) -> ToolResult:
    period = Period(start=date(2026, 10, 1), end=date(2026, 10, 7), label="Next 7 days")
    primary = Number(value=184.68, unit="eur", period=period, method="safe_to_spend.safe_to_spend_7d_eur@1",
                     evidence_ref="ev_0123456789ab", label="Safe to spend", display="€184.68", id="n1")
    card = Card(card_id="card_sts", type="metric", title="Safe to spend in the next 7 days", subtitle="1 to 7 October",
                evidence_ref="ev_0123456789ab", estimate={"label": "Estimate", "text": "An estimate."}, actions=[],
                status="ok", primary=primary, secondary=[], comparison=None, components=[])
    return ToolResult(tool="get_safe_to_spend", data={}, card=card)


@pytest.mark.parametrize("failure", [
    BillsDueMismatch("bills due differ for customer CUST00860: 278.37 against 278.36"),
    NoTransactions("no transactions up to as_of for this customer"),
])
def test_a_known_hero_failure_gives_a_null_hero_and_the_rest_intact(failure, caplog):
    def failing(ctx, args):
        raise failure

    caplog.set_level(logging.DEBUG)
    body = overview.build(_ctx(), hero_tool=failing)
    assert body.hero is None
    assert [c.type for c in body.cards] == ["breakdown", "bills"] and body.greeting == "Hi Sanna, I'm Sentti"
    OverviewResponse.model_validate(body.model_dump(mode="json"))
    assert f"hero unavailable ({type(failure).__name__})" in caplog.text
    assert str(failure) not in caplog.text and "CUST00860" not in caplog.text and "278" not in caplog.text


def test_any_other_hero_failure_is_not_hidden():
    def bug(ctx, args):
        raise RuntimeError("safe to spend does not equal the smaller limit")

    with pytest.raises(RuntimeError):
        overview.build(_ctx(), hero_tool=bug)


def test_the_save_tool_failing_leaves_the_hero_and_the_rest(caplog):
    """#191 review: a known failure of the safe-to-save tool gives a null card, not a 500."""
    def failing(ctx, args):
        raise safe_to_spend.NoTransactions("no transactions up to as_of for this customer")

    caplog.set_level(logging.DEBUG)
    body = overview.build(_ctx(), hero_tool=_stub_hero, save_tool=failing)
    assert body.safe_to_save is None and body.hero is not None and body.hero.primary.value == 184.68
    assert [c.type for c in body.cards] == ["breakdown", "bills"]
    assert "safe to save unavailable (NoTransactions)" in caplog.text and "as_of" not in caplog.text


def test_no_row_of_03_gives_a_null_hero_and_a_null_card():
    """Both tools read the same row: when 03 returns none, both sections are null and the rest stays."""
    body = overview.build(_ctx(NO_ROW))   # the real get_safe_to_spend and get_safe_to_save
    assert body.hero is None and body.safe_to_save is None
    assert [c.type for c in body.cards] == ["breakdown", "bills"] and body.greeting == "Hi Sanna, I'm Sentti"
    OverviewResponse.model_validate(body.model_dump(mode="json"))


def test_the_save_card_comes_from_the_real_tool_on_the_shared_row():
    body = overview.build(_ctx(), hero_tool=_stub_hero)
    card = body.safe_to_save
    assert (card.monthly.value, card.stock.value, card.reason) == (184.61, 12272.28, None)
    assert [c.key for c in card.monthly_components] == ["free_month", "everyday_month"]


def test_the_hero_comes_from_get_safe_to_spend():
    assert overview.HERO_TOOL is get_safe_to_spend
    body = overview.build(_ctx(), hero_tool=_stub_hero)  # the stub stands in for the metric SQL
    assert [c.type for c in body.cards] == ["breakdown", "bills"]
    assert body.greeting == "Hi Sanna, I'm Sentti" and len(body.suggested_questions) == 4 and body.insights == []
    assert body.reviews == []  # contract 0.2.0: an empty list, not an absent field, until #68


def test_hero_is_the_tools_metric_card():
    body = overview.build(_ctx(), hero_tool=_stub_hero)
    assert body.hero.type == "metric" and body.hero.status == "ok" and body.hero.primary.value == 184.68
    dumped = OverviewResponse.model_validate(body.model_dump(mode="json")).model_dump(mode="json")
    assert "id" not in dumped["hero"]["primary"]                       # tool-internal number ids are dropped
    assert "typical_day" not in dumped["cards"][1]["items"][0]         # extra tool fields are dropped


def test_overview_through_the_tool_cache_is_the_same_and_runs_no_tool_twice(tool_cache_off, monkeypatch):
    """#86: with the cache on, a second overview is served from it, byte-identical, and calls no tool."""
    from core.tools.models import Args

    class HeroArgs(Args):
        pass

    calls = []

    def hero(ctx, args):
        calls.append("hero")
        return _stub_hero(ctx, args)

    monkeypatch.setitem(overview.CACHEABLE, hero, ("stub_hero", HeroArgs))
    uncached = overview.build(_ctx(), hero_tool=hero).model_dump_json()        # the cache is off here
    monkeypatch.setattr(tool_cache_off, "mode", "memory")
    calls.clear()
    first = overview.build(_ctx(), hero_tool=hero).model_dump_json()
    second = overview.build(_ctx(), hero_tool=hero).model_dump_json()
    assert uncached == first == second and calls == ["hero"]       # cached is byte-identical to uncached
    assert tool_cache_off.stats.hits == 4 and tool_cache_off.stats.misses == 4   # hero, baskets, save, bills


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
    {"kind": "mcc", "value": "8021"},                                            # R9, whatever the history (#510)
    {"kind": "mcc", "value": "5411,8021"},                                       # R9 inside a list
    {"kind": "category", "value": "Salary"},                                     # not spending
    {"kind": "basket", "value": "luxuries"},
    {"kind": "mcc", "value": "taxi"},
    {"kind": "merchant", "value": "MRC-XXX-9999"},                               # not this customer's
])
def test_whatif_selections_refused_before_the_tool_are_422(clean_env, monkeypatch, selection):
    called = []
    response = _post_whatif(monkeypatch, whatif_body(selection), lambda ctx, args, too_few=None: called.append(args))
    assert_envelope(response, 422, "invalid_scenario")
    assert called == []
    assert "Health" not in response.text and "R9" not in response.text


def test_whatif_refusals_of_the_tool_are_422_without_their_text(clean_env, monkeypatch):
    def no_spending(ctx, args, too_few=None):
        raise WhatIfRefused("invalid_scenario: the selection has no spending in the last 6 full months")

    response = _post_whatif(monkeypatch, WHATIF, no_spending)
    assert_envelope(response, 422, "invalid_scenario")
    assert "spending" not in response.text


def test_whatif_errors_are_in_the_bodys_language(clean_env, monkeypatch):
    """The review of #106: a Finnish request gets Finnish errors, not only with ?lang=fi."""
    fi_health = {**whatif_body({"kind": "category", "value": "Health"}), "language": "fi"}
    response = _post_whatif(monkeypatch, fi_health, lambda ctx, args, too_few=None: None)
    assert_envelope(response, 422, "invalid_scenario")
    assert response.json()["error"]["message"] == "Tätä tilannetta ei voi laskea."

    def unknown(conn, customer_id):
        raise ApiError("customer_not_found")

    monkeypatch.setattr(deps, "require_customer", unknown)   # what-if checks through deps.customer_connection
    response = _post_whatif(monkeypatch, {**WHATIF, "language": "fi"}, lambda ctx, args, too_few=None: None)
    assert_envelope(response, 404, "customer_not_found")
    assert response.json()["error"]["message"] == "Asiakasta ei löytynyt."
    response = _post_whatif(monkeypatch, WHATIF, lambda ctx, args, too_few=None: None)            # language en: English
    assert response.json()["error"]["message"] == "We couldn't find this customer."


def test_a_bug_in_the_what_if_tool_is_a_500_not_a_refusal(clean_env, monkeypatch):
    """Only the tool's refusal type is a 422; any other ValueError (or pydantic error) is a bug."""
    def bug(ctx, args, too_few=None):
        raise ValueError("a tool bug, not a refusal")

    response = _post_whatif(monkeypatch, WHATIF, bug)
    assert_envelope(response, 500, "internal", retryable=True)
    assert "bug" not in response.text


def test_whatif_maps_a_merchant_id_to_the_customers_alias(clean_env, monkeypatch):
    seen = []

    def capture(ctx, args, too_few=None):
        seen.append((ctx.customer_id, ctx.language, args, too_few))
        raise WhatIfRefused("stop here")

    _post_whatif(monkeypatch, {**whatif_body({"kind": "merchant", "value": "MRC-RES-0001"}), "language": "fi"},
                 capture)
    customer, language, args, too_few = seen[0]
    assert too_few == "not_offered"   # the endpoint answers too few purchases as not_offered (#379)
    alias = aliases.build(_history(), date(2026, 9, 30)).for_merchant("MRC-RES-0001").key
    assert (customer, language, args.selection.kind, args.selection.value, args.cut_pct) == (
        "CUST00860", "fi", "merchant", alias, 20)


# ---- peer_aggregate evidence (#69): group statistics only, as the resolver of PR #95 returns them ----

PEER_SPEC = {"v": 1, "kind": "peer_aggregate", "customer_id": "CUST00860", "as_of": "2026-09-30",
             "method": "peer_benchmark.peer_median_month_eur@1",
             "source": {"file": "06_peer_benchmark.sql", "metric": "Restaurants",
                        "column": "peer_median_month_eur", "settings": {"peer_min_n": "20"}},
             "value": "212.40", "params": {"period": {"start": "2026-04-01", "end": "2026-09-30"}}}
PEER_PARTS = [  # core/tools/evidence.py resolve() of PR #95: {role, method, value}, no refs
    {"role": "peer_median", "method": "peer_benchmark.peer_median_month_eur@1", "value": "212.40"},
    {"role": "peer_p25", "method": "peer_benchmark.peer_p25_month_eur@1", "value": "140.05"},
    {"role": "peer_p75", "method": "peer_benchmark.peer_p75_month_eur@1", "value": "301.90"},
    {"role": "peer_n", "method": "peer_benchmark.peer_n@1", "value": "37"},
    {"role": "peer_level", "method": None, "value": "age_band+city"},
]


@pytest.mark.parametrize("language", ["en", "fi"])
def test_peer_aggregate_evidence_shows_group_statistics_only(language):
    from core.app.api import evidence as evidence_api
    from core.tools import evidence as tools_evidence

    res = tools_evidence.Resolution("ev_0123456789ab", "peer_aggregate", PEER_SPEC["method"], Decimal("212.40"),
                                    parts=PEER_PARTS, reconciles=True, spec=PEER_SPEC)
    e = evidence_api.build(None, res, "CUST00860", language).model_dump(mode="json")
    assert (e["kind"], e["reconciles"], e["rows"], e["row_count"], e["query"], e["next_cursor"]) == (
        "peer_aggregate", True, [], None, None, None)
    assert e["number"]["value"] == 212.4 and e["number"]["unit"] == "eur_per_month"
    assert e["method"]["doc"].endswith("metrics.md#6-peer-benchmark")
    parts = {p["role"]: p["number"] for p in e["parts"]}
    assert list(parts) == ["peer_median", "peer_p25", "peer_p75", "peer_n"]       # no part for the level itself
    assert all(n["evidence_ref"] is None for n in parts.values())                # statistics, nothing to open
    assert [parts[r]["value"] for r in parts] == [212.4, 140.05, 301.9, 37]
    assert parts["peer_n"]["unit"] == "count" and parts["peer_p25"]["unit"] == "eur_per_month"
    assert parts["peer_n"]["period"] == e["number"]["period"]
    level = "same age group and city" if language == "en" else "sama ikäryhmä ja kaupunki"
    assert level in parts["peer_n"]["label"]
    assert parts["peer_median"]["display"] == ("€212.40 a month" if language == "en" else "212,40 € / kk")
    assert "never another customer" in e["privacy_note"] or "toisen asiakkaan" in e["privacy_note"]
