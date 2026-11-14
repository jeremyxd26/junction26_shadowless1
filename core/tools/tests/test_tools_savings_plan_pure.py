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
from core.tools.models import Card, Number, Period, Unit
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


def baskets_card():
    """A minimal baskets breakdown card, as get_basket_breakdown returns it (numbers with private ids)."""
    total = num("1650.00", "ev_bask_total", "baskets.month_avg_eur@1").model_copy(update={"id": "n1"})
    item = num("980.00", "ev_bask_every", "baskets.month_avg_eur@1").model_copy(update={"id": "n2"})
    return Card(card_id="card_baskets", type="breakdown", title="Where your money goes", subtitle="Apr-Sep 2026",
                evidence_ref="ev_bask_total", estimate=None, actions=[], display_hint="stacked_bar", total=total,
                comparison=None, items=[{"key": "everyday_spending", "label": "Everyday spending",
                                         "amount": item.model_dump(), "share": None, "change": None, "flags": []}])


@pytest.fixture
def fake(monkeypatch):
    state = SimpleNamespace(what_ifs=dict(SANNA), calls=[], specs={}, bonus_status="estimate", baskets_calls=[],
                            modes=set())

    def run_what_if(ctx, args, too_few="raise"):
        category, pct = args["selection"]["value"], args["cut_pct"]
        state.calls.append((category, pct))
        state.modes.add(too_few)
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

    def get_basket_breakdown(ctx, args):
        state.baskets_calls.append(args)
        return SimpleNamespace(card=baskets_card(), evidence=["ev_bask_total", "ev_bask_every"])

    monkeypatch.setattr(sp, "get_basket_breakdown", get_basket_breakdown)
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
    assert [p["role"] for p in total_spec["parts"]] == ["restaurants", "lifestyle"]   # roles named by category
    year_spec = fake.specs[d.total_year.evidence_ref]
    assert year_spec["formula"] == "scale" and year_spec["parts"][0]["ref"] == d.total_month.evidence_ref
    assert fake.calls[0] == ("Restaurants", 20) and set(fake.calls[1:]) == {(c, 10) for c in config.SAVINGS_PLAN_OTHER_CATEGORIES}
    # each cut share is a rule value, so an answer cites it as a number
    assert [(lv.cut.value, lv.cut.method, lv.cut.unit.value) for lv in d.levers] == [
        (20, "savings_plan.cut_pct@1", "percent"), (10, "savings_plan.cut_pct@1", "percent")]
    assert all(fake.specs[lv.cut.evidence_ref]["formula"] == "rule_value" for lv in d.levers)
    # only what the plan shows is registered: two levers and their cut shares, two totals, safe to save; then
    # (#380, #503 review) the two levers' baselines for the card's estimate, after all of them, so n1..n7 stay
    registered = ctx.numbers.all()
    assert len(registered) == 9
    assert [registered[f"n{i}"].method for i in (8, 9)] == ["what_if.baseline_month_eur@1"] * 2
    assert [n.id for n in result.card.estimate.observed] == ["n8", "n9"]


def test_the_two_cut_levers_are_always_different_categories(fake):
    """Nothing is counted twice: the second lever never is Restaurants, whatever its baseline."""
    assert "Restaurants" not in config.SAVINGS_PLAN_OTHER_CATEGORIES
    fake.what_ifs["Entertainment"] = what_if("999.00", "99.90", ref="ev_ent")
    d = plan()[0].data
    keys = [lv.key for lv in d.levers]
    assert keys == ["Restaurants", "Entertainment"] and len(set(keys)) == len(keys)


def test_the_tool_skips_the_first_category_even_when_the_settings_list_it(fake, monkeypatch):
    """Review of #411: with Restaurants among the other categories and the largest, the tool still never counts
    it twice (it was 45.91 + 45.91 in the review); the next largest is the second lever."""
    monkeypatch.setattr(config, "SAVINGS_PLAN_OTHER_CATEGORIES", ("Restaurants", "Lifestyle"))
    d = plan()[0].data
    assert [lv.key for lv in d.levers] == ["Restaurants", "Lifestyle"] and d.total_month.value == 63.17
    assert ("Restaurants", config.SAVINGS_PLAN_OTHER_CUT_PCT) not in fake.calls


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


def test_no_lever_at_all_gives_the_baskets_card_and_safe_to_save(fake):
    """Decision of #411: no lever reaches the threshold, so the card is where the money goes (the baskets card,
    computed on the private context) next to safe to save; its numbers carry the answer's ids."""
    fake.what_ifs = {c: what_if("20.00", "2.00", ref=f"ev_{c[:3]}") for c in SANNA}
    result, ctx = plan()
    assert result.data.levers == [] and result.data.total_month is None and result.data.total_year is None
    assert result.model_view["kind"] == "none"
    assert result.model_view["safe_to_save"]["value"] == 184.61       # today's answer is still there
    assert fake.baskets_calls == [config.SAVINGS_PLAN_NONE_BASKETS]
    card = result.card
    assert (card.card_id, card.type, card.total.evidence_ref) == ("card_baskets", "breakdown", "ev_bask_total")
    registered = ctx.numbers.all()
    item = card.items[0]["amount"]
    assert registered[card.total.id].evidence_ref == "ev_bask_total" and registered[item["id"]].evidence_ref == "ev_bask_every"
    assert {"ev_bask_total", "ev_bask_every"} <= set(result.evidence)


def test_a_failing_baskets_card_leaves_the_no_lever_answer_without_a_card(fake, monkeypatch):
    fake.what_ifs = {c: what_if("20.00", "2.00", ref=f"ev_{c[:3]}") for c in SANNA}
    monkeypatch.setattr(sp, "get_basket_breakdown", lambda ctx, args: (_ for _ in ()).throw(RuntimeError("down")))
    result, _ = plan()
    assert result.card is None and result.model_view["safe_to_save"]["value"] == 184.61


def test_a_failing_safe_to_save_or_s_bonus_never_takes_the_plan_down(fake, monkeypatch):
    """Review of #411: any failure of the two extras leaves them out; the plan, its card and totals stand."""
    def boom(ctx, args):
        raise RuntimeError("down")

    monkeypatch.setattr(sp, "get_safe_to_save", boom)
    monkeypatch.setattr(sp, "get_bonus_estimate", lambda ctx, args: (_ for _ in ()).throw(ValueError("bad")))
    result, _ = plan()
    d = result.data
    assert (d.safe_to_save, d.follow_up) == (None, None) and d.total_month.value == 63.17 and result.card is not None
    assert result.model_view["safe_to_save"] is None and result.model_view["follow_up"] is None


def test_the_s_bonus_is_never_in_the_total_the_card_or_the_model_view(fake):
    """Decision of #411: no S-Bonus amount anywhere in the plan's answer; when the estimate is offered, its own
    question is the answer's follow-up (answered with its own Number and evidence)."""
    result, ctx = plan()
    d = result.data
    assert d.total_month.value == 45.91 + 17.26                      # not + 25.15, not + 184.61
    assert d.safe_to_save.value == 184.61
    assert "25.15" not in repr(result.model_view) and "25.15" not in result.card.model_dump_json()
    assert not [n for n in ctx.numbers.all().values() if n.method.startswith("bonus_estimate.")]
    assert result.model_view["follow_up"] == "How much S-Bonus could I get?"
    assert plan("fi")[0].model_view["follow_up"] == "Paljonko S-Bonusta voisin saada?"
    fake.bonus_status = "not_offered"
    assert plan()[0].model_view["follow_up"] is None


def test_the_card_is_a_breakdown_with_the_levers_in_words(fake):
    """Every row key is a category (contract section 3, breakdown items) and every row label says its cut in
    words. The bank button has the one label of #267 and no amount."""
    card = plan()[0].card
    assert (card.type, card.display_hint, card.title) == ("breakdown", "list", "Your savings plan")
    assert card.total.method == "savings_plan.total_month_eur@1"
    assert [i["key"] for i in card.items] == ["Restaurants", "Lifestyle"]
    assert [i["label"] for i in card.items] == ["Restaurants, a fifth less", "Lifestyle, a tenth less"]
    assert card.estimate.text == "About, if you cut these as shown and the rest of your spending stays as it is."
    show, host = card.actions
    assert (show.type, host.type, host.target, host.label) == ("open_evidence", "open_host_screen", "monthly_saving",
                                                               "See monthly saving in S-mobiili")
    fi = plan("fi")[0].card
    assert fi.items[0]["label"] == "Ravintolat, viidenneksen vähemmän"
    assert fi.actions[1].label == "Katso kuukausisäästäminen S-mobiilissa"


def digits_outside_numbers_and_dates(node, key=""):
    """Strings of a card's JSON with a digit, outside Number objects, the card's ids and refs, and the period."""
    if isinstance(node, dict):
        if {"value", "unit", "method", "display"} <= set(node):   # a Number (its period is a date)
            return
        for k, v in node.items():
            if k not in ("card_id", "evidence_ref", "subtitle"):   # ids, refs and the period label (a date)
                yield from digits_outside_numbers_and_dates(v, k)
    elif isinstance(node, list):
        for v in node:
            yield from digits_outside_numbers_and_dates(v, key)
    elif isinstance(node, str) and any(ch.isdigit() for ch in node):
        yield f"{key}: {node}"


@pytest.mark.parametrize("language", ["en", "fi"])
@pytest.mark.parametrize("other_pct", [10, 15])
def test_the_card_json_has_no_digit_outside_numbers_and_dates(fake, monkeypatch, language, other_pct):
    """Review of #411: every number of the card is a Number object (contract section 2.1)."""
    monkeypatch.setattr(config, "SAVINGS_PLAN_OTHER_CUT_PCT", other_pct)
    card = plan(language)[0].card
    assert card.subtitle == card.total.period.label
    assert list(digits_outside_numbers_and_dates(card.model_dump(mode="json"))) == []


def strings_outside_numbers(node):
    if isinstance(node, dict):
        if {"id", "value", "unit"} <= set(node):   # a model Number
            return
        for v in node.values():
            yield from strings_outside_numbers(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings_outside_numbers(v)
    elif isinstance(node, str):
        yield node


@pytest.mark.parametrize("language", ["en", "fi"])
def test_the_model_view_gives_every_number_as_a_number(fake, language):
    """Review of #411: no digit outside a Number in the model view (no "Restaurants 20% less", no bare cut_pct),
    so the composer never copies bare digits; each cut share is a Number and, for the default shares, words."""
    view = plan(language)[0].model_view
    assert "ev_" not in repr(view) and "CUST" not in repr(view)
    assert set(view) == {"tool", "kind", "levers", "total_month", "total_year", "safe_to_save", "follow_up"}
    assert view["kind"] == "plan" and [lv["key"] for lv in view["levers"]] == ["Restaurants", "Lifestyle"]
    assert all(set(lv) == {"key", "category", "cut", "cut_words", "saving"} for lv in view["levers"])
    assert [lv["cut"]["value"] for lv in view["levers"]] == [20, 10]
    assert [lv["cut_words"] for lv in view["levers"]] == (["a fifth", "a tenth"] if language == "en"
                                                          else ["viidenneksen", "kymmenyksen"])
    assert not [s for s in strings_outside_numbers(view) if any(ch.isdigit() for ch in s)]


@pytest.mark.parametrize("pct,en,fi", [(10, "a tenth", "kymmenyksen"), (20, "a fifth", "viidenneksen"),
                                       (25, "a quarter", "neljänneksen"), (50, "half", "puolet"), (15, None, None)])
def test_cut_words_come_from_the_setting(pct, en, fi):
    assert (sp.cut_words(pct, "en"), sp.cut_words(pct, "fi")) == (en, fi)


def test_a_share_without_words_is_a_number_only(fake, monkeypatch):
    monkeypatch.setattr(config, "SAVINGS_PLAN_OTHER_CUT_PCT", 15)
    result = plan()[0]
    other = result.model_view["levers"][1]
    assert other["cut_words"] is None and other["cut"]["value"] == 15 and result.data.levers[1].cut.display == "15.0%"
    assert result.card.items[1]["label"] == "Lifestyle, less than usual"     # the card row stays in words


def test_the_plan_asks_the_what_if_for_its_structured_mode(fake):
    # #379 part B: in the chat's mode a category with 1-2 purchases raises MissingData, which would end the plan;
    # the structured mode answers not_offered, so it is no lever
    plan()
    assert fake.modes == {"not_offered"}


def test_a_what_if_that_reports_too_few_purchases_never_ends_the_plan(fake, monkeypatch):
    # the crash part B's bridge check found: a MissingData for one "other" category; the plan is still made
    from core.tools.missing import MissingData
    real = sp.run_what_if

    def raising(ctx, args, too_few="raise"):
        if args["selection"]["value"] == "Travel":
            raise MissingData("too_few_transactions", what="travel", period="1 Apr \u2013 30 Sep 2026", n=1)
        return real(ctx, args, too_few)

    monkeypatch.setattr(sp, "run_what_if", raising)
    d = plan()[0].data
    assert [lv.key for lv in d.levers] and d.total_month is not None and "Travel" not in [lv.key for lv in d.levers]
