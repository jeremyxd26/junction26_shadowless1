"""get_bonus_estimate without a database (#158).

The worked examples of docs/domain/s-group-benefits.md section 4 are the tests, to the cent. The tool
runs on a synthetic history with a stand-in evidence store; every composite spec is re-computed from
its parts, as evidence.resolve does.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from core.tools import bonus, config, evidence
from core.tools.context import ToolContext
from core.tools.db import Tx
from core.tools.formatting import display

AS_OF = date(2026, 9, 30)


# ---- the document's worked examples --------------------------------------------------------------------

@pytest.mark.parametrize("grocery, share, base, percent, bonus_month, payment", [
    ("400", 100, "400.00", "2.5", "10.00", "2.00"),
    ("400", 50, "200.00", "1.5", "3.00", "1.00"),
    ("750", 100, "750.00", "4.0", "30.00", "3.75"),
])
def test_worked_examples(grocery, share, base, percent, bonus_month, payment):
    e = bonus.estimate(D(grocery), share)
    assert (e.level_base, e.bonus_percent, e.bonus_month, e.payment_benefit_month) == (
        D(base), D(percent), D(bonus_month), D(payment))
    assert e.total_month == D(bonus_month) + D(payment) and e.total_year == e.total_month * 12
    assert e.status == "estimate"


@pytest.mark.parametrize("start, extra_bonus, level_jump, payment_gain, total_gain", [
    ("150", "1.50", "0.75", "0.50", "2.75"),
    ("450", "3.00", "2.25", "0.50", "5.75"),
    ("650", "4.00", "3.25", "0.50", "7.75"),
])
def test_one_hundred_euros_more_as_two_calls(start, extra_bonus, level_jump, payment_gain, total_gain):
    before, after = bonus.estimate(D(start), 100), bonus.estimate(D(start) + 100, 100)
    assert after.bonus_month - before.bonus_month == D(extra_bonus) + D(level_jump)
    # the parts of the breakdown: the new percentage on the extra 100 and the jump on what is already spent
    assert D(100) * after.bonus_percent / 100 == D(extra_bonus)
    assert D(start) * (after.bonus_percent - before.bonus_percent) / 100 == D(level_jump)
    assert after.payment_benefit_month - before.payment_benefit_month == D(payment_gain)
    assert after.total_month - before.total_month == D(total_gain)


def test_below_the_lowest_row_is_not_offered_but_the_payment_benefit_stays():
    e = bonus.estimate(D("40"), 100)
    assert (e.status, e.bonus_percent, e.bonus_month, e.payment_benefit_month) == (
        "not_offered", D("0"), D("0.00"), D("0.20"))
    assert bonus.estimate(D("50"), 100).status == "estimate"          # the lowest row itself counts


@pytest.mark.parametrize("grocery, share, base, percent, bonus_month, payment, status", [
    ("399.99", 50, "199.99", "1.0", "2.00", "1.00", "estimate"),    # 199.995: the 1.0 % row; shown 199.99
    ("99.99", 50, "49.99", "0", "0.00", "0.25", "not_offered"),     # 49.995: below the lowest row
    ("400.00", 50, "200.00", "1.5", "3.00", "1.00", "estimate"),    # exactly 200: the 1.5 % row
])
def test_the_level_is_decided_on_the_unrounded_base(grocery, share, base, percent, bonus_month, payment, status):
    e = bonus.estimate(D(grocery), share)
    assert (e.level_base, e.bonus_percent, e.bonus_month, e.payment_benefit_month, e.status) == (
        D(base), D(percent), D(bonus_month), D(payment), status)
    # the shown base never reads as a level the unrounded base did not reach
    reached = [m for m, _ in bonus.RULES.levels if m <= e.level_base]
    assert (max(reached) if reached else None) == next(
        (m for m, p in reversed(bonus.RULES.levels) if p == e.bonus_percent), None)


def test_the_rules_come_from_the_yaml_file():
    r = bonus.RULES
    assert r.levels[0] == (D("50"), D("1.0")) and r.levels[-1] == (D("900"), D("5.0"))
    assert (r.payment_percent, r.default_share_pct, r.table_sources) == (D("0.5"), 100, ("G2", "G3"))
    assert (r.table, r.base_category, r.payment_sources) == ("default", "Groceries", ("G4", "G7", "G8"))


def test_a_missing_or_malformed_rules_file_fails_with_a_clear_message(tmp_path):
    with pytest.raises(RuntimeError, match="missing: nope.yaml not found"):
        bonus.load_rules(tmp_path / "nope.yaml")
    with pytest.raises(RuntimeError, match="core/config/absent.yaml"):     # relative inside the repository
        bonus.load_rules(bonus.ROOT / "core" / "config" / "absent.yaml")
    good = bonus.CONFIG_FILE.read_text(encoding="utf-8")
    for broken in (good.replace("min_monthly_purchases_eur: 200", "min_monthly_purchases_eur: 20"),  # not ascending
                   good.replace("percent: 0.5 ", "percent: half "),
                   good.replace("source: [G4, G7, G8]", "source: []"),           # the payment benefit's sources
                   good.replace("bonus_table: default", "bonus_table: regional"),  # no such table
                   good.replace("base_category: Groceries", "base_category: Food"),  # not a category
                   good.replace("default:", "standard:"),
                   "bonus: [1, 2"):
        path = tmp_path / "rules.yaml"
        path.write_text(broken, encoding="utf-8")
        with pytest.raises(RuntimeError, match="malformed in rules.yaml"):
            bonus.load_rules(path)


@pytest.mark.parametrize("args", [{"share_pct": 0}, {"share_pct": 101}, {"share_pct": 50.5},
                                  {"share_pct": True}, {"share_pct": "50"},
                                  {"customer_id": "CUST00860"}, {"share": 50}])
def test_arguments_are_validated(args):
    with pytest.raises(ValidationError):
        bonus.GetBonusEstimateArgs.model_validate(args)


# ---- the tool on a synthetic history ----------------------------------------------------------------------

class Store:
    """Stand-in for the evidence table: write() stores the specs."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

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


def history() -> list[Tx]:
    """Four 100-euro grocery purchases a month from April to September 2026 (400 a month), plus other
    spending and older months that must not count."""
    out, i = [], 1
    for month in range(3, 10):
        for k in range(4):
            d = date(2026, month, 3 + 7 * k)
            out.append(Tx(i, d, datetime.combine(d, datetime.min.time()), "Groceries", "purchase",
                          f"MRC-GRO-{k:04d}", "5411", D("-100.00")))
            i += 1
        d = date(2026, month, 20)
        out.append(Tx(i, d, datetime.combine(d, datetime.min.time()), "Restaurants", "purchase",
                      "MRC-RES-0001", "5812", D("-55.00")))
        i += 1
    return sorted(out, key=lambda t: (t.tx_date, t.id))


def run(share_pct=None, language="en"):
    store = Store()
    ctx = ToolContext("CUST00860", AS_OF, store, language, _history=history())
    args = {} if share_pct is None else {"share_pct": share_pct}
    return bonus.get_bonus_estimate(ctx, args), store


def test_the_tool_on_400_a_month_matches_the_first_worked_example():
    result, _ = run()
    d = result.data
    assert (d.grocery_month.value, d.level_base.value, d.bonus_percent.value, d.bonus_month.value,
            d.payment_benefit_month.value, d.total_month.value, d.total_year.value) == (
        400.0, 400.0, 2.5, 10.0, 2.0, 12.0, 144.0)
    assert d.status == "estimate" and d.lowest_level is None and d.reason is None
    assert d.grocery_month.method == "spender_profile.spend_month_eur@1"


def test_the_default_share_is_a_rule_value_with_evidence():
    result, store = run()
    share = result.data.share
    assert (share.method, share.value, share.display) == ("bonus_estimate.share_pct@1", 100, "100%")
    spec = store.rows[share.evidence_ref]                              # a ref, unlike a typed share
    assert (spec["formula"], spec["params"]["rule"], spec["params"]["value"]) == (
        "rule_value", "what_if_assumptions.default_share", "100")


@pytest.mark.parametrize("language, shown", [("en", "50%"), ("fi", "50 %")])
def test_a_typed_share_is_user_input_shown_as_a_whole_percentage(language, shown):
    result, _ = run(share_pct=50, language=language)
    d = result.data
    assert (d.share.method, d.share.value, d.share.evidence_ref, d.share.display) == (
        config.USER_INPUT_METHOD, 50, None, shown)
    assert (d.level_base.value, d.bonus_percent.value) == (200.0, 1.5)


def test_every_number_has_a_formatter_display_and_derived_ones_reconcile():
    result, store = run(language="fi")
    d = result.data
    numbers = [d.grocery_month, d.level_base, d.bonus_percent, d.bonus_month, d.payment_benefit_month,
               d.total_month, d.total_year, d.share]
    for n in numbers:
        assert n.display == display(D(str(n.value)), n.unit, "fi", n.method)
    for n in numbers:
        assert n.evidence_ref in store.rows
        spec = store.rows[n.evidence_ref]
        assert n.method == spec["method"] and D(spec["value"]) == D(str(n.value))
        if spec["kind"] == "composite":
            parts = {p["role"]: D(store.rows[p["ref"]]["value"]) for p in spec["parts"]}
            assert evidence.compute_formula(spec["formula"], parts, spec.get("params")) == D(spec["value"])
    level = store.rows[d.bonus_percent.evidence_ref]["params"]
    assert level["source"] == ["G2", "G3"] and level["table"] == "default"     # the rule and its source
    rate = store.rows[d.payment_benefit_month.evidence_ref]["params"]
    assert (rate["source"], rate["rule"]) == (["G4", "G7", "G8"], "payment_benefit.percent")


def test_below_the_lowest_level_the_card_says_why():
    result, store = run(share_pct=10)                                  # 40 a month: below 50
    d = result.data
    assert (d.status, d.bonus_percent.value, d.bonus_month.value, d.payment_benefit_month.value) == (
        "not_offered", 0.0, 0.0, 0.2)
    assert d.lowest_level.value == 50.0 and d.reason
    assert store.rows[d.lowest_level.evidence_ref]["params"]["rule"] == "bonus.tables.default.levels[0]"
    card = result.card.model_dump()
    assert card["estimate"]["text"].startswith(d.reason)               # the card itself says why
    assert d.lowest_level.evidence_ref in [n["evidence_ref"] for n in card["secondary"]]
    # the number ids follow the order the card shows them
    shown = [d.share, card["primary"], *card["secondary"], *[c["amount"] for c in card["components"]]]
    ids = [n.id if hasattr(n, "id") else n["id"] for n in shown]
    assert ids == [f"n{i}" for i in range(1, len(ids) + 1)]


def test_card_and_model_view_carry_the_assumptions_and_name_no_merchant():
    result, _ = run()
    card = result.card.model_dump()
    assert card["type"] == "metric" and card["estimate"]["label"] == "Estimate"
    for key in config.BONUS_ASSUMPTIONS:
        assert config.BONUS_TEXT[key][0] in card["estimate"]["text"]
    view = result.model_view
    assert view["kind"] == "estimate" and len(view["assumptions"]) == len(config.BONUS_ASSUMPTIONS)
    text = json.dumps(view)
    for leak in ("MRC-", "store_", "merchant", "evidence_ref", "ev_", "CUST", "rows"):
        assert leak not in text
    assert all(not any(ch.isdigit() for ch in s) for s in view["assumptions"])   # no number outside Numbers


@pytest.mark.parametrize("language, opener", [(0, "Assumes "), (1, "Oletus: ")])
def test_the_assumptions_read_as_assumptions_and_claim_no_membership(language, opener):
    for key in config.BONUS_ASSUMPTIONS:
        text = config.BONUS_TEXT[key][language]
        assert text.startswith(opener), text
        for claim in ("your co-op", "you are a member", "osuuskauppasi", "jäsenenä"):
            assert claim not in text.lower(), text


class SpecStore:
    """Stand-in for evidence.load: ref -> (customer, spec)."""

    def __init__(self, specs: dict[str, dict]) -> None:
        self.specs = specs

    def execute(self, sql, params):
        row = ("CUST00860", self.specs[params[0]]) if params[0] in self.specs else None

        class Res:
            def fetchone(self):
                return row

        return Res()


@pytest.mark.parametrize("params", [
    {"levels": [["abc", "1.0"]], "below_lowest_percent": "0"},     # not a number: InvalidOperation
    {"levels": None, "below_lowest_percent": "0"},                 # not a list: TypeError
    {"levels": [["50", "1.0"]], "below_lowest_percent": "0", "share_num": 1, "share_den": 0},  # division by 0
])
def test_a_crafted_composite_spec_resolves_without_a_check_not_a_500(params):
    part = evidence.transactions_spec("CUST00860", AS_OF, "spender_profile.spend_month_eur@1",
                                      bonus.Selection(direction="out", start=AS_OF, end=AS_OF), D("400.00"),
                                      {"n_months": 6})
    part_ref = evidence.make_ref(part)
    spec = evidence.composite_spec("CUST00860", AS_OF, "bonus_estimate.bonus_percent@1", "bonus_level",
                                   {"base": part_ref}, D("2.5"), params)
    ref = evidence.make_ref(spec)
    res = evidence.resolve(SpecStore({ref: spec, part_ref: part}), ref, "CUST00860")
    assert (res.kind, res.reconciles) == ("composite", None)
