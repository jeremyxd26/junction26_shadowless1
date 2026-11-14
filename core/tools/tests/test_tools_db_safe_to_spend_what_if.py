"""Database-backed tests for get_safe_to_spend and run_what_if.

Skipped without DATABASE_URL. For the three sample customers of metrics.md and the four personas of
docs/design/personas.md, both tools are compared with an independent run of the metric SQL
(03_safe_to_spend.sql, 04_what_if.sql) for a one-customer range, and with the worked numbers of those
documents. Every evidence ref the tools write must resolve and reconcile. One customer per query,
tx_date <= as_of.
"""

import json
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from core.tools import aliases, evidence
from core.tools.bills import get_recurring_bills
from core.tools.context import ToolContext
from core.tools.safe_to_spend import binding_limit, get_safe_to_spend, status_of
from core.tools.what_if import run_what_if

AS_OF = date(2026, 9, 30)
METRICS = Path(__file__).resolve().parents[2] / "metrics"
SAMPLE = ["CUST00001", "CUST00002", "CUST00006"]
PERSONAS = ["CUST00860", "CUST00493", "CUST00349", "CUST00849"]
# the sample customers' cases check the worked numbers of metrics.md: on a private database only (#502)
SAMPLE_CASES = [pytest.param(c, marks=pytest.mark.sample_customer) for c in SAMPLE]
EVERYONE = SAMPLE_CASES + PERSONAS
D = Decimal

# metrics.md section 3 and personas.md Q3 (as_of 2026-09-30): safe to spend 7d after the savings goal (#391),
# binding limit, status
SAFE_WORKED = {
    "CUST00001": ("93.98", "budget", "ok"),
    "CUST00002": ("0.00", "budget", "nothing_free"),
    "CUST00006": ("12.95", "budget", "ok"),
    "CUST00860": ("97.46", "budget", "below_usual"),
    "CUST00493": ("78.86", "budget", "ok"),
    "CUST00349": ("147.23", "budget", "below_usual"),
    "CUST00849": ("123.15", "budget", "ok"),
}
# metrics.md section 4 and personas.md Q4: dining out (category Restaurants) -20%
WHAT_IF_WORKED = {  # baseline / month, saving / month, / week, / year
    "CUST00001": ("56.86", "11.37", "2.62", "136.45"),
    "CUST00002": ("92.18", "18.44", "4.24", "221.23"),
    "CUST00006": ("15.56", "3.11", "0.72", "37.33"),
    "CUST00860": ("229.56", "45.91", "10.56", "550.95"),
    "CUST00493": ("102.66", "20.53", "4.72", "246.38"),
    "CUST00349": ("294.73", "58.95", "13.56", "707.36"),
    "CUST00849": ("277.48", "55.50", "12.76", "665.96"),
}
RESTAURANTS_20 = {"selection": {"kind": "category", "value": "Restaurants"}, "cut_pct": 20}


def ctx_for(conn, customer_id, language="en", as_of=AS_OF):
    return ToolContext(customer_id=customer_id, as_of=as_of, conn=conn, language=language)


def sql_row(conn, file_name, customer_id, settings=None, as_of=AS_OF):
    """Independent run of a metric file for [customer_id, next id): plain session settings, one row."""
    values = {"demo_today": as_of.isoformat(), "customer_from": customer_id,
              "customer_to": f"CUST{int(customer_id[4:]) + 1:05d}", "cushion_eur": "100", **(settings or {})}
    for name, value in values.items():
        conn.execute("SELECT set_config(%s, %s, false)", (f"app.{name}", value))
    rows = []
    with conn.cursor() as cur:
        cur.execute((METRICS / file_name).read_text(encoding="utf-8"))
        for _ in cur.results():
            if cur.description:
                names = [d.name for d in cur.description]
                rows = [dict(zip(names, r)) for r in cur.fetchall()]
    conn.execute("SET statement_timeout = '60s'")
    return [r for r in rows if r["customer_id"] == customer_id]


def dec(number):
    return D(str(number.value))


def assert_reconciles(conn, customer_id, refs):
    assert refs
    for ref in refs:
        res = evidence.resolve(conn, ref, customer_id, limit=1)
        assert res.reconciles, f"{ref} ({res.kind} {res.method}) does not reconcile"


def assert_model_view_clean(view, customer_id):
    text = json.dumps(view, default=str)
    assert customer_id not in text
    assert "MRC-" not in text            # no merchant ids (R3)
    assert "ev_" not in text             # no evidence refs in the model view


# ---- get_safe_to_spend -------------------------------------------------------------------------------

@pytest.mark.parametrize("customer_id", EVERYONE)
def test_safe_to_spend_equals_03_and_the_worked_numbers(conn, customer_id):
    result = get_safe_to_spend(ctx_for(conn, customer_id))
    data = result.data
    row = sql_row(conn, "03_safe_to_spend.sql", customer_id)[0]

    assert dec(data.safe_to_spend) == row["safe_to_spend_7d_eur"]
    assert dec(data.free_until_payday) == row["free_until_payday_eur"]
    assert dec(data.balance_limit) == row["balance_limit_7d_eur"]
    assert dec(data.budget_limit) == row["budget_limit_7d_eur"]
    comp = {c.key: c for c in data.components}
    assert dec(comp["balance"].amount) == row["balance_eur"]
    assert dec(comp["essentials_reserve"].amount) == row["essentials_reserve_eur"]
    assert dec(comp["irregular_reserve"].amount) == row["irregular_reserve_eur"]
    assert dec(comp["cushion"].amount) == row["cushion_eur"]
    # bills due comes from recurring.bills_due_numbers, rounded like 03 ("metrics wins"): to the cent
    assert dec(comp["bills_due"].amount) == row["bills_due_eur"]
    assert [c.operation for c in data.components] == ["add", "subtract", "subtract", "subtract", "subtract"]

    assert data.binding_limit == row["binding_limit"] == binding_limit(dec(data.balance_limit), dec(data.budget_limit))
    assert data.status == row["status"] == status_of(dec(data.safe_to_spend), row["usual_everyday_7d_eur"])
    assert data.next_payday == row["next_payday"] and data.salary_status == row["salary_status"]
    assert (data.period.start, data.period.end) == (row["week_start"], row["week_end"])

    worked_value, worked_binding, worked_status = SAFE_WORKED[customer_id]
    assert dec(data.safe_to_spend) == D(worked_value)
    assert (data.binding_limit, data.status) == (worked_binding, worked_status)


@pytest.mark.parametrize("customer_id", EVERYONE)
def test_components_add_up_to_free_until_payday(conn, customer_id):
    data = get_safe_to_spend(ctx_for(conn, customer_id)).data
    signed = sum((dec(c.amount) if c.operation == "add" else -dec(c.amount) for c in data.components), D("0"))
    # each of the five parts is rounded on its own (contracts/api.md 2.1)
    assert abs(signed - dec(data.free_until_payday)) <= D("0.02")


@pytest.mark.parametrize("customer_id", SAMPLE_CASES + ["CUST00860"])
def test_bills_due_is_the_same_number_as_the_bills_card(conn, customer_id):
    ctx = ctx_for(conn, customer_id)
    safe = get_safe_to_spend(ctx).data
    bills = get_recurring_bills(ctx, {"include_income": False}).data
    bills_due = next(c.amount for c in safe.components if c.key == "bills_due")
    assert bills_due.evidence_ref == bills.upcoming_total.evidence_ref
    assert bills_due.value == bills.upcoming_total.value


def test_lead_persona_bills_due_is_the_eval_reference(conn):
    # personas.md Q3: CUST00860 bills due 928.50 (03_safe_to_spend.sql), the eval reference value
    data = get_safe_to_spend(ctx_for(conn, "CUST00860")).data
    bills_due = next(c.amount for c in data.components if c.key == "bills_due")
    row = sql_row(conn, "03_safe_to_spend.sql", "CUST00860")[0]
    assert dec(bills_due) == row["bills_due_eur"] == D("928.50")


@pytest.mark.parametrize("customer_id", SAMPLE_CASES + ["CUST00860"])
def test_safe_to_spend_evidence_and_card(conn, customer_id):
    result = get_safe_to_spend(ctx_for(conn, customer_id))
    assert_reconciles(conn, customer_id, result.evidence)
    top = evidence.resolve(conn, result.data.safe_to_spend.evidence_ref, customer_id)
    # #391: the evidence lists the savings goal next to the two limits ("why this number" shows it)
    assert top.kind == "composite" and {p["role"] for p in top.parts} == {"a", "b", "goal"}
    goal_part = next(p for p in top.parts if p["role"] == "goal")
    assert goal_part["ref"] == result.data.savings_goal.evidence_ref and goal_part["method"] == "safe_to_spend.savings_goal_eur@1"
    card = result.card
    assert card.type == "metric" and card.status == result.data.status and card.estimate["text"]
    assert [n.method for n in card.secondary] == [
        "safe_to_spend.free_until_payday_eur@1", "safe_to_spend.balance_limit_7d_eur@1",
        "safe_to_spend.budget_limit_7d_eur@1", "safe_to_spend.savings_goal_eur@1"]
    assert_model_view_clean(result.model_view, customer_id)


# Other dates (metrics.md section 3): 2026-05-20, CUST00001's salary that month came on the 29th
# ("late", payday = month end); 2026-09-14, salary upcoming tomorrow (N = 1). On 2026-05-20 the sum of
# the rounded per-bill amounts (278.37) differs from 03's rounded sum (278.36); metrics wins.
OTHER_DATES = [(date(2026, 5, 20), "late", date(2026, 5, 31)), (date(2026, 9, 14), "upcoming", date(2026, 9, 15))]


@pytest.mark.sample_customer   # CUST00001's own salary dates of metrics.md section 3
@pytest.mark.parametrize("as_of, salary_status, payday", OTHER_DATES)
def test_safe_to_spend_on_other_dates_equals_03(conn, as_of, salary_status, payday):
    result = get_safe_to_spend(ctx_for(conn, "CUST00001", as_of=as_of))
    data = result.data
    row = sql_row(conn, "03_safe_to_spend.sql", "CUST00001", as_of=as_of)[0]
    assert (data.salary_status, data.next_payday) == (salary_status, payday) == (row["salary_status"], row["next_payday"])
    assert data.free_until_payday.period.end == data.next_payday == row["next_payday"]
    assert data.free_until_payday.period.start == as_of + (date(2026, 1, 2) - date(2026, 1, 1))
    assert dec(data.safe_to_spend) == row["safe_to_spend_7d_eur"]
    assert dec(data.free_until_payday) == row["free_until_payday_eur"]
    comp = {c.key: c for c in data.components}
    assert dec(comp["bills_due"].amount) == row["bills_due_eur"]          # metrics wins, to the cent
    if as_of == date(2026, 5, 20):
        assert dec(comp["bills_due"].amount) == D("278.36")               # the items add up to 278.37
    signed = sum((dec(c.amount) if c.operation == "add" else -dec(c.amount) for c in data.components), D("0"))
    assert abs(signed - dec(data.free_until_payday)) <= D("0.02")
    assert_reconciles(conn, "CUST00001", result.evidence)


def test_what_if_rejects_an_mcc_the_customer_uses_for_health(conn):
    ctx = ctx_for(conn, "CUST00860")
    health_mcc = next(t.mcc for t in ctx.history() if t.category == "Health" and t.mcc)
    with pytest.raises(Exception, match="R9"):
        run_what_if(ctx, {"selection": {"kind": "mcc", "value": health_mcc}, "cut_pct": 20})


@pytest.mark.sample_customer   # CUST00001's worked number of metrics.md section 3
def test_safe_to_spend_in_finnish(conn):
    result = get_safe_to_spend(ctx_for(conn, "CUST00001", "fi"))
    assert result.data.safe_to_spend.display == "93,98 €"
    assert result.card.title.startswith("Turvallisesti")


# ---- run_what_if -------------------------------------------------------------------------------------

@pytest.mark.parametrize("customer_id", EVERYONE)
def test_what_if_dining_out_equals_04_and_the_worked_numbers(conn, customer_id):
    result = run_what_if(ctx_for(conn, customer_id), RESTAURANTS_20)
    data = result.data
    row = sql_row(conn, "04_what_if.sql", customer_id, {"whatif": "category:Restaurants", "whatif_pct": "20"})[0]
    for key, column in [("baseline_per_month", "baseline_month_eur"), ("saving_per_month", "saving_month_eur"),
                        ("saving_per_week", "saving_week_eur"), ("saving_per_year", "saving_year_eur"),
                        ("one_off_excluded", "one_off_excluded_eur"), ("regular_excluded", "regular_excluded_eur")]:
        assert dec(getattr(data, key)) == row[column], key
    assert data.status == row["status"] == "estimate"
    worked = WHAT_IF_WORKED[customer_id]
    assert [dec(data.baseline_per_month), dec(data.saving_per_month), dec(data.saving_per_week),
            dec(data.saving_per_year)] == [D(v) for v in worked]
    assert data.scenario.cut_pct.value == 20 and data.scenario.cut_pct.evidence_ref is None


@pytest.mark.parametrize("scenario, status", [
    ({"kind": "category", "value": "Groceries"}, "not_offered"),          # all regular essentials
    ({"kind": "basket", "value": "unexpected_necessities"}, "estimate_with_caveat"),
    ({"kind": "basket", "value": "everyday_spending"}, "estimate"),
    ({"kind": "mcc", "value": "5812,5813,5814"}, "estimate"),
])
def test_what_if_statuses_equal_04(conn, scenario, status):
    result = run_what_if(ctx_for(conn, "CUST00860"), {"selection": scenario, "cut_pct": 20})
    row = sql_row(conn, "04_what_if.sql", "CUST00860",
                  {"whatif": f"{scenario['kind']}:{scenario['value']}", "whatif_pct": "20"})[0]
    assert result.data.status == row["status"] == status
    assert dec(result.data.saving_per_month) == row["saving_month_eur"]
    assert dec(result.data.regular_excluded) == row["regular_excluded_eur"]
    if status == "not_offered":
        assert result.data.saving_per_month.value == 0 and dec(result.data.regular_excluded) > 0
    assert len(result.data.caveats) == (1 if status == "estimate" else 2)


def test_what_if_merchant_alias_maps_to_the_merchant_and_never_reaches_the_model(conn):
    ctx = ctx_for(conn, "CUST00860")   # the lead persona: 210 restaurant purchases (#502)
    history = ctx.history()
    alias_map = aliases.build(history, AS_OF)
    restaurant = next(t.merchant_id for t in sorted(history, key=lambda t: t.tx_date, reverse=True)
                      if t.category == "Restaurants" and t.merchant_id)
    alias = alias_map.for_merchant(restaurant).key
    result = run_what_if(ctx, {"selection": {"kind": "merchant", "value": alias}, "cut_pct": 50})
    row = sql_row(conn, "04_what_if.sql", "CUST00860", {"whatif": f"merchant:{restaurant}", "whatif_pct": "50"})[0]
    assert dec(result.data.saving_per_month) == row["saving_month_eur"]
    assert result.data.scenario.selection == {"kind": "merchant", "value": restaurant}   # app side
    assert result.model_view["selection"] == {"kind": "merchant", "value": alias}        # model side
    assert_model_view_clean(result.model_view, "CUST00860")


def test_what_if_rejects_a_health_merchant(conn):
    ctx = ctx_for(conn, "CUST00860")
    history = ctx.history()
    health = next(t.merchant_id for t in history if t.category == "Health" and t.merchant_id)
    alias = aliases.build(history, AS_OF).for_merchant(health).key
    with pytest.raises(ValueError, match="R9"):
        run_what_if(ctx, {"selection": {"kind": "merchant", "value": alias}, "cut_pct": 20})


@pytest.mark.sample_customer   # CUST00002's Travel of metrics.md; a persona's 422 is in core/tests/test_api_db.py
def test_what_if_without_spending_is_an_invalid_scenario(conn):
    # CUST00002 has no Travel in the window (metrics.md section 6 worked numbers: 0.00 a month)
    assert sql_row(conn, "04_what_if.sql", "CUST00002", {"whatif": "category:Travel", "whatif_pct": "20"}) == []
    with pytest.raises(ValueError, match="invalid_scenario"):
        run_what_if(ctx_for(conn, "CUST00002"), {"selection": {"kind": "category", "value": "Travel"}, "cut_pct": 20})


@pytest.mark.parametrize("customer_id", SAMPLE_CASES + ["CUST00860"])
def test_what_if_evidence_and_card(conn, customer_id):
    result = run_what_if(ctx_for(conn, customer_id), RESTAURANTS_20)
    assert_reconciles(conn, customer_id, result.evidence)
    card = result.card
    assert card.type == "whatif" and card.estimate["text"].endswith("cut by 20%.")
    assert card.result["status"] == "estimate" and card.evidence_ref == result.data.saving_per_month.evidence_ref
    assert_model_view_clean(result.model_view, customer_id)


# ---- timing (one call of each tool for one customer) ------------------------------------------------

def test_one_call_of_each_tool_is_fast_enough(conn):
    ctx = ctx_for(conn, "CUST00860")
    t0 = time.perf_counter()
    get_safe_to_spend(ctx)
    t1 = time.perf_counter()
    run_what_if(ctx, RESTAURANTS_20)
    t2 = time.perf_counter()
    print(f"get_safe_to_spend {1000 * (t1 - t0):.0f} ms, run_what_if {1000 * (t2 - t1):.0f} ms")
    assert t1 - t0 < 10 and t2 - t1 < 10   # generous: the shared database is sometimes slow


# ---- #55 review follow-ups ---------------------------------------------------------------------------

def test_metric_files_run_in_a_read_only_transaction(conn, tmp_path, monkeypatch):
    """On an idle (autocommit) connection nothing in a metric file can write."""
    from psycopg import errors

    from core.tools import metric_sql

    monkeypatch.setattr(metric_sql, "METRICS_DIR", tmp_path)
    (tmp_path / "probe.sql").write_text(
        "SELECT 'CUST00860'::text AS customer_id, current_setting('transaction_read_only') AS ro;", encoding="utf-8")
    (tmp_path / "write.sql").write_text(
        "INSERT INTO coach_evidence (ref, customer_id, spec) VALUES ('ev_readonlyprobe', 'CUST00860', '{}');\n"
        "SELECT 'CUST00860'::text AS customer_id;", encoding="utf-8")
    assert metric_sql.run_one(conn, "probe.sql", "CUST00860", AS_OF)["ro"] == "on"
    with pytest.raises(errors.ReadOnlySqlTransaction):
        metric_sql.run(conn, "write.sql", "CUST00860", AS_OF)
    assert conn.execute("SELECT count(*) FROM coach_evidence WHERE ref = 'ev_readonlyprobe'").fetchone()[0] == 0
    # inside a caller's transaction: a savepoint, and the caller's transaction stays writable afterwards
    with conn.transaction(force_rollback=True):
        assert metric_sql.run_one(conn, "probe.sql", "CUST00860", AS_OF)["ro"] == "off"
        assert conn.execute("SELECT current_setting('transaction_read_only')").fetchone()[0] == "off"


@pytest.mark.parametrize("source", [
    {"file": "01_recurring.sql", "column": "typical_month_eur", "settings": {}},
    {"file": "03_safe_to_spend.sql", "column": "bills_due_eur", "settings": {"customer_from": "CUST00000"}},
    {"file": "03_safe_to_spend.sql", "column": "bills_due_eur", "settings": {"demo_today": "2026-01-31"}},
])
def test_metric_evidence_refuses_other_files_and_reserved_settings(conn, source):
    """A stored spec is data: another file, or a setting that moves the customer range or as_of, is refused."""
    spec = {"v": 1, "kind": "metric", "customer_id": "CUST00860", "as_of": AS_OF.isoformat(),
            "method": "safe_to_spend.bills_due_eur@1", "source": source, "value": "586.32"}
    ref = evidence.make_ref(spec)
    with conn.transaction(force_rollback=True):  # the crafted spec is never kept
        conn.execute("INSERT INTO coach_evidence (ref, customer_id, spec) VALUES (%s, %s, %s)",
                     (ref, "CUST00860", json.dumps(spec)))
        with pytest.raises(evidence.EvidenceForbidden):
            evidence.resolve(conn, ref, "CUST00860")


def test_safe_to_spend_refuses_a_bills_total_that_differs_from_03(conn, monkeypatch):
    """The bills-due Number must equal 03's bills_due_eur; a difference is an internal error, not a warning."""
    import dataclasses

    from core.tools import safe_to_spend

    real = safe_to_spend.recurring.bills_due_numbers

    def off_by_a_cent(ctx, nb, **kw):
        due = real(ctx, nb, **kw)
        return dataclasses.replace(due, total_value=due.total_value + D("0.01"))

    monkeypatch.setattr(safe_to_spend.recurring, "bills_due_numbers", off_by_a_cent)
    with pytest.raises(safe_to_spend.BillsDueMismatch):
        get_safe_to_spend(ctx_for(conn, "CUST00860"))
