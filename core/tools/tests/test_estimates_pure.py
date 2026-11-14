"""#380: every card that sets `estimate` separates what was observed from what is assumed. No database.

- Each tool's card that sets an estimate is built, in English and Finnish and in the states that matter
  (safe to save with and without a month, the S-Bonus offered and not, the forecast below and above zero),
  and its `assumptions` are not empty. At runtime an empty list is allowed and logged once (never raised).
- Codes come from the closed list; a text has no digit (a figure is the `value`); `observed` and the values
  are the card's own Numbers (the same ref, and the same id where the tool registered one).
- The closed list is the same in the tools, the API schema and the contract's Estimates table."""

from __future__ import annotations

import logging
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from test_bonus_pure import run as bonus_run
from test_tools_baskets_bills_pure import TODAY as BILLS_TODAY
from test_tools_baskets_bills_pure import _FakeStore, history_for_series
from test_tools_safe_to_save_pure import row
from test_tools_safe_to_save_pure import run as save_run

from core.app.api import schemas
from core.tools import config, forecast, models, peer, safe_to_spend, what_if
from core.tools.bills import get_recurring_bills
from core.tools.context import ToolContext
from core.tools.formatting import display
from core.tools.models import ASSUMPTION_CODES, Number, Period, Unit

WINDOW = Period(start=date(2026, 4, 1), end=date(2026, 9, 30), label="Apr-Sep 2026")
CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "api.md"


def num(value: str, unit: Unit, method: str, ref: str, nid: str | None = None, language: str = "en") -> Number:
    return Number(value=float(value) if "." in value else int(value), unit=unit, period=WINDOW, method=method,
                  evidence_ref=ref, label="x", display=display(Decimal(value), unit, language, method), id=nid)


def hero_card(language):
    week = Period(start=date(2026, 10, 1), end=date(2026, 10, 7), label="Next 7 days")
    comps = [safe_to_spend.Component(key=key, label=key, operation="add" if key == "balance" else "subtract",
                                     amount=num(v, Unit.EUR, f"safe_to_spend.{key}_eur@1", f"ev_sts_{key}", f"n{i + 6}",
                                                language))
             for i, (key, v) in enumerate((("balance", "5864.86"), ("bills_due", "1180.50"),
                                           ("essentials_reserve", "640.00"), ("irregular_reserve", "167.74"),
                                           ("cushion", "50.00")))]
    goal = num("360.00", Unit.EUR_PER_MONTH, "safe_to_spend.savings_goal_eur@1", "ev_sts_goal", "n2", language)
    data = safe_to_spend.SafeToSpendData(
        period=week, safe_to_spend=num("138.79", Unit.EUR, "safe_to_spend.safe_to_spend_7d_eur@1", "ev_sts", "n1",
                                       language),
        savings_goal=goal, usual_week=num("137.80", Unit.EUR_PER_WEEK, "safe_to_spend.usual_week_eur@1", "ev_uw"),
        free_until_payday=num("3826.62", Unit.EUR, "safe_to_spend.free_until_payday_eur@1", "ev_fup", "n3", language),
        balance_limit=num("1784.39", Unit.EUR, "safe_to_spend.balance_limit_7d_eur@1", "ev_bl", "n4", language),
        budget_limit=num("138.79", Unit.EUR, "safe_to_spend.budget_limit_7d_eur@1", "ev_bu", "n5", language),
        binding_limit="budget", components=comps, status="ok", next_payday=date(2026, 10, 15),
        salary_status="received_this_month")
    return safe_to_spend._card(data, language)


def whatif_card(language):
    result = what_if.WhatIfResult(
        scenario=what_if.Scenario(selection={"kind": "category", "value": "Restaurants"},
                                  cut_pct=num("20", Unit.PERCENT, config.USER_INPUT_METHOD, None, "n7", language),
                                  label="Restaurants -20%"),
        status="estimate",
        **{key: num("45.91", Unit(unit), f"what_if.{column}@1", f"ev_wi_{i:08d}", f"n{i + 1}", language)
           for i, (key, column, unit) in enumerate(config.WHAT_IF_NUMBERS)},
        assumptions=["a"], caveats=[])
    return what_if._card(result, 20, language)


def peer_card(language):
    size = num("118", Unit.COUNT, "peer.size@1", "ev_peer_size", "n6", language)
    data = peer.PeerBenchmarkData(
        metric="spend_total", metric_label="Spending", period=WINDOW, shown=True, reason=None,
        you=num("1650.00", Unit.EUR_PER_MONTH, "peer.you_eur@1", "ev_peer_you", "n1", language),
        peer_median=num("1500.00", Unit.EUR_PER_MONTH, "peer.median_eur@1", "ev_peer_med", "n2", language),
        peer_p25=None, peer_p75=None, percentile=None, vs_median=None,
        peer_group=peer.PeerGroup(level="age_band", label="Your age band", size=size, comparable=True),
        peer_source="marts")
    estimate = {"label": config.label(config.PEER_TEXT["estimate_label"], language),
                "text": config.label(config.PEER_TEXT["estimate_age_band"], language)}
    return peer._card(data, estimate, language)


def forecast_card(language, status):
    def n(value, nid, method="balance_forecast.balance_eur@1", unit=Unit.EUR):
        return num(value, unit, method, f"ev_fc_{nid}", nid, language)
    lowest = n("-120.00" if status == "below_zero" else "320.00", "n4")
    data = forecast.BalanceForecastData(
        status=status, today=date(2026, 9, 30), next_payday=date(2026, 10, 15), salary_status="received_this_month",
        balance_now=n("5864.86", "n1", "safe_to_spend.balance_eur@1"),
        bills_until_payday=n("1180.50", "n2", "safe_to_spend.bills_due_eur@1"),
        daily_pace=n("61.20", "n3", "balance_forecast.pace_eur@1", Unit.EUR_PER_DAY),
        lowest=lowest, lowest_date=date(2026, 10, 14), day_before_payday=lowest,
        first_below_zero=lowest if status == "below_zero" else None,
        first_below_zero_date=date(2026, 10, 14) if status == "below_zero" else None,
        steps=[forecast.Step(date=date(2026, 10, 1), kinds=[], label="1 Oct", balance=lowest)])
    return forecast._card(data, language)


def plan_card(language):
    from core.tools import savings_plan as sp
    levers = [sp.Lever(key=c, category=c, label=f"{c}, a fifth less", cut_pct=20, cut_words="a fifth",
                       cut=num("20", Unit.PERCENT, "savings_plan.cut_pct@1", None, f"n{2 * i + 2}", language),
                       saving=num(v, Unit.EUR_PER_MONTH, "what_if.saving_month_eur@1", f"ev_lever_{i}", f"n{2 * i + 3}",
                                  language))
              for i, (c, v) in enumerate((("Restaurants", "45.91"), ("Lifestyle", "17.26")))]
    total = num("63.17", Unit.EUR_PER_MONTH, "savings_plan.total_month_eur@1", "ev_plan_total", "n1", language)
    baselines = [num(v, Unit.EUR_PER_MONTH, "what_if.baseline_month_eur@1", f"ev_base_{i}", f"n{9 + i}", language)
                 for i, v in enumerate(("229.56", "172.58"))]
    return sp._card(levers, total, language, baselines)


def estimate_cards(language):
    """(name, card) for every card that sets an estimate, in the states that matter."""
    cards = [("safe_to_spend", hero_card(language))]
    for name, changes in (("safe_to_save", {}), ("safe_to_save_zero", dict(
            everyday_month_eur="900.00", safe_to_save_monthly_eur="0.00", save_reason="largest_everyday_category",
            save_reason_category="Restaurants", save_reason_month_eur="186.93")), ("safe_to_save_shortfall", dict(
            free_month_eur="-1.59", everyday_month_eur="250.00", safe_to_save_monthly_eur="0.00",
            essentials_shortfall_month_eur="1.59", save_reason="essentials_exceed_income", save_reason_month_eur="1.59"))):
        cards.append((name, save_run(row(**changes), language)[0].card))
    cards.append(("bonus", bonus_run(language=language)[0].card))
    cards.append(("bonus_not_offered", bonus_run(share_pct=10, language=language)[0].card))
    bills = get_recurring_bills(ToolContext(customer_id="CUST00042", as_of=BILLS_TODAY, conn=_FakeStore(),
                                            language=language, _history=history_for_series()))
    cards.append(("bills_pro_rata", bills.card))
    cards.append(("savings_plan", plan_card(language)))         # dev (#369)
    cards += [("whatif", whatif_card(language)), ("peer", peer_card(language)),
              ("forecast_below_zero", forecast_card(language, "below_zero")),
              ("forecast_comfortable", forecast_card(language, "comfortable"))]
    return cards


def numbers_on(card: dict) -> list[dict]:
    """Every Number of a card outside its estimate."""
    out = []

    def walk(o):
        if isinstance(o, dict):
            if {"value", "unit", "method", "display"} <= set(o):
                out.append(o)
            for k, v in o.items():
                if k != "estimate":
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(card)
    return out


@pytest.mark.parametrize("language", ["en", "fi"])
def test_every_estimate_card_says_what_it_observed_and_what_it_assumes(language):
    for name, card in estimate_cards(language):
        assert card is not None and card.estimate is not None, name
        est = card.estimate
        assert est.assumptions, f"{name}: an estimate without assumptions"
        for a in est.assumptions:
            assert a.code in ASSUMPTION_CODES, (name, a.code)
            assert not re.search(r"[0-9]", a.text), (name, a.text)     # a figure goes in `value`
            assert a.text == config.label(config.ASSUMPTION_TEXT[f"{prefix(name)}.{a.code}"], language)
        assert est.observed, f"{name}: an estimate with nothing observed"


def prefix(name: str) -> str:
    """The tool of a card name above, as the keys of config.ASSUMPTION_TEXT spell it."""
    for start, tool in (("safe_to_save", "safe_to_save"), ("safe_to_spend", "safe_to_spend"), ("bonus", "bonus"),
                        ("savings_plan", "savings_plan"),
                        ("bills", "bills"), ("whatif", "what_if"), ("peer", "peer"), ("forecast", "forecast")):
        if name.startswith(start):
            return tool
    raise KeyError(name)


@pytest.mark.parametrize("language", ["en", "fi"])
def test_observed_and_values_are_the_cards_own_numbers(language):
    """Nothing new is computed: each observed Number and each value is a Number the tool already built, with
    its ref. The bonus share and the forecast's balance, bills and pace are on the model view, not the card."""
    off_card = {"bonus": {"share"}, "bonus_not_offered": {"share"},
                "forecast_below_zero": {"balance", "bills", "pace"}, "forecast_comfortable": {"balance", "bills", "pace"},
                # the plan (dev): the levers' baselines and cut shares are in the answer, the card shows the savings
                "savings_plan": {"baseline 1", "baseline 2", "cut 1", "cut 2"}}
    for name, card in estimate_cards(language):
        dumped = card.model_dump(mode="json")
        on_card = {(n["evidence_ref"], n["value"]) for n in numbers_on(dumped)}
        est = dumped["estimate"]
        refs = [(n["evidence_ref"], n["value"]) for n in est["observed"]]
        refs += [(a["value"]["evidence_ref"], a["value"]["value"]) for a in est["assumptions"] if a["value"]]
        missing = [r for r in refs if r not in on_card]
        assert len(missing) <= len(off_card.get(name, ())), (name, missing)


def test_an_empty_assumptions_list_is_allowed_and_logged_once_per_estimate(caplog):
    models._WARNED_EMPTY.difference_update({"Probe|t", "Probe|u"})
    with caplog.at_level(logging.WARNING, logger="core.tools.models"):
        first = models.Estimate(label="Probe", text="t")
        second = models.Estimate(label="Probe", text="t")
        other = models.Estimate(label="Probe", text="u")           # another estimate with the same label
    assert first.assumptions == [] and second.observed == [] and other.assumptions == []
    assert [r.getMessage() for r in caplog.records].count("an estimate card has no assumptions (#380)") == 2


@pytest.mark.parametrize("language", ["en", "fi"])
def test_every_fixed_bonus_assumption_is_on_the_card(language):
    """#503 review: each fixed assumption of the S-Bonus estimate (config.BONUS_ASSUMPTIONS) is an assumption of
    the card, so a new fixed assumption cannot be forgotten and an app that shows "We assume" drops none."""
    for share_pct in (None, 50):
        codes = [a.code for a in bonus_run(share_pct=share_pct, language=language)[0].card.estimate.assumptions]
        for key in config.BONUS_ASSUMPTIONS:
            assert key in config.BONUS_ASSUMPTION_CODES, key
            code = config.BONUS_ASSUMPTION_CODES[key]
            assert (code in codes) if code else ({"bonus_all_at_s_group", "bonus_share"} & set(codes)), (key, codes)


@pytest.mark.parametrize("language", ["en", "fi"])
def test_the_hero_estimate_names_both_limbs(language):
    """#503 review: the budget limit binds for every persona, so the hero lists it as observed and its assumptions
    (a typical month repeats, the monthly amount for saving put aside first) next to the balance limb's."""
    est = hero_card(language).estimate
    assert [n.method for n in est.observed][-1] == "safe_to_spend.budget_limit_7d_eur@1"
    assert {"spending_as_usual", "reserve_for_unexpected", "cushion", "bills_on_usual_days",
            "budget_from_usual_month", "savings_goal_first"} == {a.code for a in est.assumptions}


@pytest.mark.parametrize("language", ["en", "fi"])
def test_the_what_if_assumes_the_coming_months_are_like_the_last(language):
    codes = [a.code for a in whatif_card(language).estimate.assumptions]
    assert codes == ["next_months_like_last", "cut_share"]


def test_the_closed_list_is_one_list_in_the_tools_the_schema_and_the_contract():
    assert schemas.AssumptionCode.__args__ == ASSUMPTION_CODES
    s = CONTRACT.read_text(encoding="utf-8")
    table = s[s.index("| `code` | Used by | Meaning (`value`) |"):]
    table = table[:table.index("\n\n")].split("\n")[2:]          # the rows after the header
    codes = [re.match(r"^\| `([a-z_]+)` \|", line).group(1) for line in table]
    assert sorted(codes) == sorted(ASSUMPTION_CODES) and len(codes) == len(set(codes))
    used = {k.split(".", 1)[1] for k in config.ASSUMPTION_TEXT}
    assert used <= set(ASSUMPTION_CODES)


@pytest.mark.parametrize("language", ["en", "fi"])
def test_the_plan_observes_the_baselines_and_assumes_each_cut(language):
    """#503 review (dev, #369): the plan's observed are the levers' baselines, never the savings (which are the
    estimate); each lever's cut share is the value of a cuts_as_shown assumption."""
    est = plan_card(language).estimate
    assert est.observed and all(n.method == "what_if.baseline_month_eur@1" for n in est.observed)
    assert [a.code for a in est.assumptions] == ["next_months_like_last", "cuts_as_shown", "cuts_as_shown"]
    assert all(a.value is not None and a.value.unit.value == "percent" for a in est.assumptions[1:])


@pytest.mark.parametrize("language", ["en", "fi"])
def test_a_what_if_not_offered_never_observes_a_baseline_of_zero(language):
    """Review of #520: Groceries are regular essentials, so the what-if is not offered and its baseline is 0; the
    estimate lists what the card shows as left out instead, never a zero."""
    result = what_if.WhatIfResult(
        scenario=what_if.Scenario(selection={"kind": "category", "value": "Groceries"},
                                  cut_pct=num("20", Unit.PERCENT, config.USER_INPUT_METHOD, None, "n7", language),
                                  label="Groceries -20%"),
        status="not_offered",
        **{key: num("3773.14" if key == "regular_excluded" else "0.00", Unit(unit), f"what_if.{column}@1",
                    f"ev_wi_{i:08d}", f"n{i + 1}", language)
           for i, (key, column, unit) in enumerate(config.WHAT_IF_NUMBERS)},
        assumptions=["a"], caveats=[])
    observed = what_if._card(result, 20, language).estimate.observed
    assert [n.method for n in observed] == ["what_if.regular_excluded_eur@1"] and all(n.value for n in observed)
