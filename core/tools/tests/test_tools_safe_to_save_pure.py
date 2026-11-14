"""get_safe_to_save without a database: the card's rules on rows of 03_safe_to_spend.sql (#165)."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pytest

from core.tools import config, metric_sql, safe_to_spend
from core.tools.context import ToolContext
from core.tools.formatting import money
from core.tools.safe_to_save import build, get_safe_to_save, window

AS_OF = date(2026, 9, 30)


class FakeStore:
    """The evidence store's write and read-back, in memory."""

    def __init__(self):
        self.rows = {}

    def cursor(self):
        store = self

        class Cur:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def executemany(self, sql, params):
                for ref, _customer, spec in params:
                    store.rows.setdefault(ref, spec.obj)

        return Cur()

    def execute(self, sql, params):
        class Res:
            def __init__(self, rows):
                self._rows = rows

            def fetchall(self):
                return self._rows

        return Res([(r, self.rows[r]) for r in params[0] if r in self.rows])


def row(**changes) -> dict:
    """Sanna's row (contracts/api.md `card.safe_to_save`), with changes."""
    base = {
        "free_month_eur": "783.79", "everyday_month_eur": "599.18", "safe_to_save_monthly_eur": "184.61",
        "essentials_shortfall_month_eur": "0.00", "free_until_payday_eur": "12567.56",
        "everyday_until_payday_eur": "295.28", "safe_to_save_eur": "12272.28", "save_reason": None,
        "save_reason_category": None, "save_reason_month_eur": None,
        "next_payday": date(2026, 10, 15), "salary_status": "received_this_month",
        # the weekly figure after the savings goal (#391), from the same row
        "week_start": date(2026, 10, 1), "week_end": date(2026, 10, 7), "balance_limit_7d_eur": "5864.86",
        "budget_limit_7d_eur": "97.46", "safe_to_spend_7d_eur": "97.46", "savings_goal_eur": "360.00",
    }
    base.update(changes)
    return {k: Decimal(v) if isinstance(v, str) and re.fullmatch(r"-?[0-9.]+", v) else v for k, v in base.items()}


def run(r: dict, language: str = "en"):
    ctx = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=FakeStore(), language=language)
    return build(ctx, {"cushion_eur": config.SAFE_TO_SPEND_CUSHION_EUR}, r), ctx


def numbers_of(card: dict):
    """Every Number object of a card (a dict with value, unit, method and display)."""
    def walk(o):
        if isinstance(o, dict):
            if {"value", "unit", "method", "display"} <= set(o):
                yield o
            for v in o.values():
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)
    return list(walk(card))


def test_free_month_covers_everyday_spending():
    result, _ = run(row())
    card = result.card.model_dump(mode="json")
    assert (card["type"], card["monthly"]["value"], card["stock"]["value"], card["reason"]) == (
        "safe_to_save", 184.61, 12272.28, None)
    assert [(c["key"], c["operation"], c["amount"]["value"]) for c in card["monthly_components"]] == [
        ("free_month", "add", 783.79), ("everyday_month", "subtract", 599.18)]
    assert [(c["key"], c["operation"], c["amount"]["value"]) for c in card["stock_components"]] == [
        ("free_until_payday", "add", 12567.56), ("everyday_until_payday", "subtract", 295.28)]
    assert card["evidence_ref"] == card["monthly"]["evidence_ref"]
    assert card["actions"][0]["evidence_ref"] == card["evidence_ref"]
    # monthly figures describe the last 6 complete months, the stock today + 1 to payday
    assert (card["monthly"]["period"]["start"], card["monthly"]["period"]["end"]) == ("2026-04-01", "2026-09-30")
    assert (card["stock"]["period"]["start"], card["stock"]["period"]["end"]) == ("2026-10-01", "2026-10-15")
    assert card["monthly"]["display"] == "€184.61 a month" and card["stock"]["display"] == "€12,272.28"


def test_everyday_spending_uses_it_all_up():
    result, _ = run(row(everyday_month_eur="900.00", safe_to_save_monthly_eur="0.00",
                        save_reason="largest_everyday_category", save_reason_category="Restaurants",
                        save_reason_month_eur="186.93"))
    card = result.card.model_dump(mode="json")
    assert card["monthly"]["value"] == 0
    assert [c["key"] for c in card["monthly_components"]] == ["free_month", "everyday_month"]
    reason = card["reason"]
    assert (reason["kind"], reason["category"], reason["amount"]["value"]) == (
        "largest_everyday_category", {"key": "Restaurants", "label": "Restaurants"}, 186.93)
    assert reason["amount"]["method"] == "safe_to_spend.save_reason_month_eur@1"
    assert "Restaurants" in reason["text"] and not re.search(r"[0-9]", reason["text"])


def test_a_sensitive_category_is_never_named():
    result, _ = run(row(everyday_month_eur="900.00", safe_to_save_monthly_eur="0.00",
                        save_reason="largest_everyday_category", save_reason_category="Health",
                        save_reason_month_eur="120.00"))
    reason = result.card.model_dump(mode="json")["reason"]
    assert reason["category"] is None
    assert "Health" not in str(result.card.model_dump()) and "Health" not in str(result.model_view)


def test_essentials_exceed_income():
    result, _ = run(row(free_month_eur="-1.59", everyday_month_eur="250.00", safe_to_save_monthly_eur="0.00",
                        essentials_shortfall_month_eur="1.59", save_reason="essentials_exceed_income",
                        save_reason_month_eur="1.59"))
    card = result.card.model_dump(mode="json")
    assert card["monthly"]["value"] == 0
    assert [(c["key"], c["operation"], c["amount"]["value"]) for c in card["monthly_components"]] == [
        ("essentials_shortfall", "subtract", 1.59)]
    reason = card["reason"]
    assert (reason["kind"], reason["category"], reason["amount"]["value"]) == ("essentials_exceed_income", None, 1.59)


def test_a_free_month_just_below_zero_is_a_shortfall():
    """#191 review: -0.004 rounds to 0.00, but 03's reason follows the unrounded sign; the components follow
    the reason, not the rounded value."""
    result, _ = run(row(free_month_eur="0.00", essentials_shortfall_month_eur="0.00", safe_to_save_monthly_eur="0.00",
                        save_reason="essentials_exceed_income", save_reason_month_eur="0.00"))
    card = result.card.model_dump(mode="json")
    assert [(c["key"], c["operation"]) for c in card["monthly_components"]] == [("essentials_shortfall", "subtract")]
    assert card["reason"]["kind"] == "essentials_exceed_income"


def test_no_stock_when_free_until_payday_is_negative():
    result, _ = run(row(free_until_payday_eur="-40.00", safe_to_save_eur="0.00"))
    card = result.card.model_dump(mode="json")
    assert card["stock"]["value"] == 0 and card["stock_components"] == []


@pytest.mark.parametrize("changes", [
    dict(free_month_eur="-1.59", everyday_month_eur="250.00", safe_to_save_monthly_eur="0.00",
         essentials_shortfall_month_eur="1.59", save_reason="essentials_exceed_income", save_reason_month_eur="1.59"),
    dict(everyday_month_eur="900.00", safe_to_save_monthly_eur="0.00", save_reason="largest_everyday_category",
         save_reason_category="Restaurants", save_reason_month_eur="186.93"),
    dict(free_until_payday_eur="-40.00", safe_to_save_eur="0.00"),
    {},
])
@pytest.mark.parametrize("language", ["en", "fi"])
def test_nothing_negative_and_no_digits_in_free_text(changes, language):
    result, _ = run(row(**changes), language)
    card = result.card.model_dump(mode="json")
    assert all(n["value"] >= 0 and not n["display"].startswith("-") for n in numbers_of(card))
    # The subtitle's only digits are the displays of the goal, safe to save and the weekly figure (#391).
    subtitle = card["subtitle"]
    for n in (result.data.savings_goal, result.data.monthly, result.data.safe_to_spend_week):
        subtitle = subtitle.replace(n.display, "")
    texts = [card["title"], subtitle, card["stock_explanation"], card["estimate"]["text"]]
    texts += [c["label"] for c in card["monthly_components"] + card["stock_components"]]
    texts += [card["reason"]["text"]] if card["reason"] else []
    assert not any(re.search(r"[0-9]", t) for t in texts), texts


def test_a_negative_shown_amount_is_refused():
    with pytest.raises(ValueError, match="negative"):
        run(row(everyday_month_eur="-5.00"))


def test_every_number_is_metric_evidence_of_03():
    result, ctx = run(row())
    specs = ctx.conn.rows
    card = result.card.model_dump(mode="json")
    for n in numbers_of(card):
        spec = specs[n["evidence_ref"]]
        if n["method"] in (config.SAFE_TO_SAVE_WEEK_METHOD, config.SAFE_TO_SAVE_DAY_METHOD):   # #417: of `monthly`
            assert spec["formula"] == "scale" and spec["parts"][0]["ref"] == card["monthly"]["evidence_ref"]
            continue
        assert spec["kind"] == "metric" and spec["source"]["file"] == "03_safe_to_spend.sql"
        assert n["method"] == f"safe_to_spend.{spec['source']['column']}@1"
        assert Decimal(spec["value"]) == Decimal(str(n["value"]))
        assert (spec["params"]["period"]["start"], spec["params"]["period"]["end"]) == (
            n["period"]["start"], n["period"]["end"])


def test_the_model_view_has_numbers_by_id_and_no_refs():
    result, _ = run(row())
    view = result.model_view
    assert view["tool"] == "get_safe_to_save" and view["monthly"]["value"] == 184.61
    assert "ev_" not in str(view) and "CUST" not in str(view)


def test_the_window_is_03s():
    assert window(date(2026, 9, 30)) == (date(2026, 4, 1), date(2026, 9, 30))
    assert window(date(2026, 10, 15)) == (date(2026, 4, 1), date(2026, 9, 30))
    assert window(date(2026, 10, 31)) == (date(2026, 5, 1), date(2026, 10, 31))


def test_one_run_of_03_for_both_tools_of_one_context(monkeypatch):
    """The overview's hero and this card read the same row: metric_row runs the file once per context."""
    runs = []

    def run_one(conn, file, customer_id, as_of, settings):
        runs.append(file)
        return row()

    monkeypatch.setattr(metric_sql, "run_one", run_one)
    ctx = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=FakeStore())
    first = safe_to_spend.metric_row(ctx)
    get_safe_to_save(ctx, {})
    assert safe_to_spend.metric_row(ctx) == first and runs == ["03_safe_to_spend.sql"]


def test_no_row_is_no_transactions(monkeypatch):
    monkeypatch.setattr(metric_sql, "run_one", lambda *a: None)
    ctx = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=FakeStore())
    with pytest.raises(safe_to_spend.NoTransactions):
        get_safe_to_save(ctx, {})


# ---- #217: parallel lanes on copies of one context run the metric file once ---------------------------

def _two_lanes(monkeypatch, result):
    """metric_row in two threads on copies of one context (as the answer pipeline's lanes), with a slow
    run_one; returns the number of runs and what each lane got (a row or the exception)."""
    import dataclasses
    import threading
    import time

    runs = []
    started = threading.Barrier(2)

    def slow_run_one(conn, file, customer_id, as_of, settings):
        runs.append(file)
        time.sleep(0.2)
        return result

    monkeypatch.setattr(metric_sql, "run_one", slow_run_one)
    base = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=FakeStore())
    base._labels = {}
    lanes = [dataclasses.replace(base), dataclasses.replace(base)]   # copies that share `shared`
    assert lanes[0].shared is lanes[1].shared
    got: list = [None, None]

    def lane(i):
        started.wait()
        try:
            got[i] = safe_to_spend.metric_row(lanes[i])[1]
        except Exception as exc:  # noqa: BLE001 - the lane's outcome is the test's subject
            got[i] = exc

    threads = [threading.Thread(target=lane, args=(i,)) for i in (0, 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    return runs, got


def test_two_parallel_lanes_run_the_metric_file_once(monkeypatch):
    runs, got = _two_lanes(monkeypatch, row())
    assert runs == ["03_safe_to_spend.sql"]
    assert got[0] is got[1] and got[0]["safe_to_save_monthly_eur"] == Decimal("184.61")


def host_actions(card: dict) -> list[dict]:
    return [a for a in card["actions"] if a["type"] == "open_host_screen"]


@pytest.mark.parametrize("language, label", [("en", "See monthly saving in S-mobiili"),
                                             ("fi", "Katso kuukausisäästäminen S-mobiilissa")])
def test_a_month_that_leaves_money_offers_the_host_monthly_saving_screen(language, label):
    """#267: one step into the bank's monthly saving, naming the destination only."""
    result, _ = run(row(), language)
    card = result.card.model_dump(mode="json")
    assert card["monthly"]["value"] > 0
    assert host_actions(card) == [{"type": "open_host_screen", "label": label, "evidence_ref": None,
                                   "prompt": None, "target": "monthly_saving"}]
    assert not re.search(r"[0-9]", label)                         # no number in the label (answer-text check)
    assert len(card["actions"]) <= 2                              # the API allows two actions per card


def test_a_month_that_leaves_nothing_has_no_host_screen_action():
    result, _ = run(row(free_month_eur="-1.59", everyday_month_eur="250.00", safe_to_save_monthly_eur="0.00",
                        essentials_shortfall_month_eur="1.59", save_reason="essentials_exceed_income",
                        save_reason_month_eur="1.59"))
    card = result.card.model_dump(mode="json")
    assert card["monthly"]["value"] == 0 and host_actions(card) == []
    assert [a["type"] for a in card["actions"]] == ["open_evidence"]


def test_the_host_screen_target_list_is_closed():
    from pydantic import ValidationError

    from core.tools.models import HOST_SCREEN_TARGETS, Action

    assert HOST_SCREEN_TARGETS == ("monthly_saving", "bonus_to_fund", "contact_bank")   # contact_bank: #420
    with pytest.raises(ValidationError):
        Action(type="open_host_screen", label="x", target="some_fund")       # not in the list
    with pytest.raises(ValidationError):
        Action(type="open_host_screen", label="x")                          # target required
    with pytest.raises(ValidationError):
        Action(type="open_evidence", label="x", evidence_ref="ev_1", target="monthly_saving")  # only here
    # the destination only: no evidence and no prompt on a host screen action (review of #308)
    with pytest.raises(ValidationError):
        Action(type="open_host_screen", label="x", target="monthly_saving", evidence_ref="ev_1")
    with pytest.raises(ValidationError):
        Action(type="open_host_screen", label="x", target="monthly_saving", prompt="How could I save more?")
    assert Action(type="open_host_screen", label="x", target="bonus_to_fund").target == "bonus_to_fund"


def test_no_row_raises_in_both_lanes_after_one_run(monkeypatch):
    runs, got = _two_lanes(monkeypatch, None)
    assert runs == ["03_safe_to_spend.sql"]
    assert all(isinstance(g, safe_to_spend.NoTransactions) for g in got)


# ---- #417: the headline at three scales ----------------------------------------------------------------

@pytest.mark.parametrize("changes", [
    {},                                                                     # Sanna's fixture, 184.61
    dict(safe_to_save_monthly_eur="364.31", everyday_month_eur="419.48"),
    dict(free_month_eur="2000.00", safe_to_save_monthly_eur="1234.56", everyday_month_eur="765.44"),
    dict(everyday_month_eur="900.00", safe_to_save_monthly_eur="0.00", save_reason="largest_everyday_category",
         save_reason_category="Restaurants", save_reason_month_eur="186.93"),
])
def test_week_and_day_reconcile_with_the_month_by_the_stated_formula(changes):
    r = row(**changes)
    result, _ = run(r)
    monthly = r["safe_to_save_monthly_eur"]
    data, m = result.data, Decimal(monthly)
    assert Decimal(str(data.weekly.value)) == money(m * 7 / Decimal("30.4375"))
    assert Decimal(str(data.daily.value)) == money(m / Decimal("30.4375"))
    assert (data.weekly.unit.value, data.daily.unit.value) == ("eur_per_week", "eur_per_day")
    card = result.card.model_dump(mode="json")
    assert card["weekly"]["value"] == data.weekly.value and card["daily"]["value"] == data.daily.value
    assert result.model_view["weekly"]["id"] == data.weekly.id
