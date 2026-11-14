"""get_savings_plan without a database (#369): each lever present or absent, the threshold, the total and twelve
times it, no lever at all, nothing counted twice, the S-Bonus and safe to save never added in."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.tools import config, evidence
from core.tools import savings_plan as sp
from core.tools.context import ToolContext
from core.tools.formatting import display
from core.tools.models import Number, Period, Unit
from core.tools.what_if import WhatIfRefused

AS_OF = date(2026, 9, 30)
WINDOW = Period(start=date(2026, 4, 1), end=date(2026, 9, 30), label="Apr-Sep 2026")


def num(value, ref, method, unit=Unit.EUR_PER_MONTH):
    return Number(value=float(value), unit=unit, period=WINDOW, method=method, evidence_ref=ref, label="x",
                  display=display(Decimal(str(value)), unit, "en", method))


def what_if(baseline, saving, status="estimate", ref="ev_ref"):
    return SimpleNamespace(data=SimpleNamespace(
        status=status, baseline_per_month=num(baseline, ref + "b", "what_if.baseline_month_eur@1"),
        saving_per_month=num(saving, ref + "s", "what_if.saving_month_eur@1")))


SANNA = {"Restaurants": what_if("229.56", "45.91", ref="ev_rest"), "Entertainment": what_if("100.05", "10.01", ref="ev_ent"),
         "Lifestyle": what_if("172.58", "17.26", ref="ev_life"), "Travel": what_if("63.19", "6.32", ref="ev_trav")}


@pytest.fixture
def fake(monkeypatch):
    state = SimpleNamespace(what_ifs=dict(SANNA), calls=[], specs={}, bonus_status="estimate")

    def run_what_if(ctx, args):
        category, pct = args["selection"]["value"], args["cut_pct"]
        state.calls.append((category, pct))
        result = state.what_ifs.get(category)
        if result is None:
            raise WhatIfRefused("no spending")
        return result

    monkeypatch.setattr(sp, "run_what_if", run_what_if)
    monkeypatch.setattr(sp, "get_safe_to_save", lambda ctx, args: SimpleNamespace(data=SimpleNamespace(
        monthly=num("184.61", "ev_save", "safe_to_spend.safe_to_save_monthly_eur@1"))))
    monkeypatch.setattr(sp, "get_bonus_estimate", lambda ctx, args: SimpleNamespace(data=SimpleNamespace(
        status=state.bonus_status, total_month=num("25.15", "ev_bonus", "bonus_estimate.total_month_eur@1"))))
    monkeypatch.setattr(evidence, "write", lambda conn, specs: state.specs.update(specs))
    return state


def plan(language="en"):
    ctx = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=None, language=language)
    return sp.get_savings_plan(ctx, {}), ctx


def test_two_levers_their_total_and_twelve_times_it(fake):
    result, ctx = plan()
    d = result.data
    assert [(lv.key, lv.cut_pct, lv.saving.value) for lv in d.levers] == [("Restaurants", 20, 45.91), ("Lifestyle", 10, 17.26)]
    assert (d.total_month.value, d.total_year.value) == (63.17, 758.04)
    assert (d.total_month.method, d.total_year.method) == ("savings_plan.total_month_eur@1", "savings_plan.total_year_eur@1")
    total_spec = fake.specs[d.total_month.evidence_ref]
    assert total_spec["formula"] == "sum" and [p["ref"] for p in total_spec["parts"]] == ["ev_rests", "ev_lifes"]
    year_spec = fake.specs[d.total_year.evidence_ref]
    assert year_spec["formula"] == "scale" and year_spec["parts"][0]["ref"] == d.total_month.evidence_ref
    assert fake.calls[0] == ("Restaurants", 20) and set(fake.calls[1:]) == {(c, 10) for c in config.SAVINGS_PLAN_OTHER_CATEGORIES}
    # only what the plan shows is registered: two levers, two totals, safe to save, the S-Bonus extra
    assert len(ctx.numbers.all()) == 6


def test_the_two_cut_levers_are_always_different_categories(fake):
    """Nothing is counted twice: the second lever never is Restaurants, whatever its baseline."""
    assert "Restaurants" not in config.SAVINGS_PLAN_OTHER_CATEGORIES
    fake.what_ifs["Entertainment"] = what_if("999.00", "99.90", ref="ev_ent")
    d = plan()[0].data
    keys = [lv.key for lv in d.levers]
    assert keys == ["Restaurants", "Entertainment"] and len(set(keys)) == len(keys)


def test_the_largest_other_category_by_baseline_and_ties_by_name(fake):
    fake.what_ifs["Entertainment"] = what_if("172.58", "17.26", ref="ev_ent")   # the same baseline as Lifestyle
    assert [lv.key for lv in plan()[0].data.levers] == ["Restaurants", "Entertainment"]


def test_small_purchases_never_add_an_amount():
    """Small purchases are no lever (#369): no category of the plan is "small purchases"."""
    assert "small_purchases" not in {config.SAVINGS_PLAN_FIRST[0], *config.SAVINGS_PLAN_OTHER_CATEGORIES}


@pytest.mark.parametrize("saving,present", [("4.99", False), ("5.00", True), ("5.01", True)])
def test_a_lever_counts_from_five_euros_a_month(fake, saving, present):
    fake.what_ifs["Restaurants"] = what_if("24.95", saving, ref="ev_rest")
    keys = [lv.key for lv in plan()[0].data.levers]
    assert ("Restaurants" in keys) is present


def test_a_cut_the_what_if_does_not_offer_or_refuses_is_no_lever(fake):
    fake.what_ifs["Restaurants"] = what_if("229.56", "45.91", status="not_offered", ref="ev_rest")
    del fake.what_ifs["Lifestyle"]                                   # no spending: the what-if refuses
    d = plan()[0].data
    assert [lv.key for lv in d.levers] == ["Entertainment"]           # the largest other that remains
    assert d.total_month.value == 10.01


def test_no_lever_at_all_gives_no_card_and_says_none(fake):
    fake.what_ifs = {c: what_if("20.00", "2.00", ref=f"ev_{c[:3]}") for c in SANNA}
    result, _ = plan()
    assert result.data.levers == [] and result.data.total_month is None and result.data.total_year is None
    assert result.card is None and result.model_view["kind"] == "none"
    assert result.model_view["safe_to_save"]["value"] == 184.61       # today's answer is still there


def test_the_s_bonus_and_safe_to_save_are_never_in_the_total(fake):
    d = plan()[0].data
    assert d.total_month.value == 45.91 + 17.26                      # not + 25.15, not + 184.61
    assert d.bonus.value == 25.15 and d.safe_to_save.value == 184.61
    fake.bonus_status = "not_offered"
    assert plan()[0].data.bonus is None


def test_the_card_is_a_breakdown_with_the_levers_and_the_extra_line(fake):
    card = plan()[0].card
    assert (card.type, card.display_hint, card.title) == ("breakdown", "list", "Your savings plan")
    assert card.total.method == "savings_plan.total_month_eur@1"
    assert [i["key"] for i in card.items] == ["Restaurants", "Lifestyle", "s_bonus_extra"]
    assert card.items[0]["label"] == "Restaurants 20% less"
    assert "not in the total" in card.items[2]["label"]
    show, host = card.actions
    assert (show.type, host.type, host.target, host.label) == ("open_evidence", "open_host_screen", "monthly_saving",
                                                               "Start saving in S-mobiili")
    fi = plan("fi")[0].card
    assert fi.items[0]["label"] == "Ravintolat 20 % vähemmän" and fi.actions[1].label == "Aloita säästäminen S-mobiilissa"


def test_the_model_view_has_numbers_and_labels_only(fake):
    view = plan()[0].model_view
    assert "ev_" not in repr(view) and "CUST" not in repr(view)
    assert set(view) == {"tool", "kind", "levers", "total_month", "total_year", "safe_to_save", "bonus_extra"}
    assert view["kind"] == "plan" and [lv["key"] for lv in view["levers"]] == ["Restaurants", "Lifestyle"]
