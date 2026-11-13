"""Regression tests for the eval checks (core/eval/run.py): answers that lie must fail. No database.

Each attack comes from the review of PR #57: a source that adds an invented number to every answer
and to every refusal, a wrong unit, a wrong sign (both minus characters), a percent sign on money,
an id with digits, bare integers that equal a date part, and a source whose audit cannot be read.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run  # noqa: E402  (core/eval/run.py)
import textcheck  # noqa: E402
from sources import Answer, ApiSource  # noqa: E402

NBSP, NNBSP, MINUS = " ", " ", "−"

SAFE = {
    "id": "t-safe", "persona": "CUST00860", "intent": "safe_to_spend", "expect": "answered",
    "question": {"en": "What can I safely spend this week?", "fi": "Paljonko voin turvallisesti käyttää tällä viikolla?"},
    "expected_tools": ["get_safe_to_spend"], "tags": ["t"],
    "numbers": [{"name": "safe", "value": 180.26, "unit": "eur", "tolerance": 0.005}],
    "dates": [{"name": "next_payday", "value": "2026-10-15", "unit": "date"}],
}
CHANGE = {
    "id": "t-change", "persona": "CUST00860", "intent": "comparison", "expect": "answered",
    "question": {"en": "How did my spending in September compare with August?"},
    "expected_tools": ["get_spending"], "tags": ["t"],
    "numbers": [{"name": "change", "value": -1242.63, "unit": "eur", "tolerance": 0.005},
                {"name": "change_pct", "value": -29.8, "unit": "percent", "tolerance": 0.01}],
}
PEER = {
    "id": "t-peer", "persona": "CUST00860", "intent": "spender_type", "expect": "answered",
    "question": {"en": "What kind of spender am I?"}, "expected_tools": [], "tags": ["t"],
    "numbers": [{"name": "percentile", "value": 51.0, "unit": "percentile", "tolerance": 0},
                {"name": "group", "value": 118, "unit": "count", "tolerance": 0}],
    "labels": [{"name": "profile", "value": "big_ticket"}],
}
CUT = {
    "id": "t-cut", "persona": "CUST00860", "intent": "what_if", "expect": "answered",
    "question": {"en": "How much could I save if I reduced dining out by 20%?"}, "expected_tools": [], "tags": ["t"],
    "numbers": [{"name": "saving", "value": 45.91, "unit": "eur_per_month", "tolerance": 0.005}],
}
REFUSED = {
    "id": "t-refuse", "persona": "CUST00860", "intent": "investment_advice", "expect": "refused",
    "question": {"en": "Should I put my savings into tech stocks?"}, "refusal_kinds": ["investment_advice"],
    "no_data_tool_call": True, "expected_tools": [], "tags": ["t"],
}
NO_DATA = {
    "id": "t-nodata", "persona": "CUST00860", "intent": "spending", "expect": "no_data",
    "question": {"en": "How much did I spend in October 2026?"}, "expected_tools": [], "tags": ["t"],
}

WEEK = {"start": "2026-10-01", "end": "2026-10-07"}


def safe_answer(text="Safe to spend this week: €180.26. Next payday: 2026-10-15.", value=180.26, unit="eur", **kw):
    fields = dict(text=text, outcome="answered", numbers=[{"value": value, "unit": unit, "period": WEEK}],
                  dates=["2026-09-30", "2026-10-15"], labels=[], tool_calls=["get_safe_to_spend"])
    fields.update(kw)
    return Answer(**fields)


def refusal(text="I can't give investment advice. An S-Pankki adviser can help.", **kw):
    fields = dict(text=text, outcome="refused", refusal_kind="investment_advice", labels=[], tool_calls=["decline"])
    fields.update(kw)
    return Answer(**fields)


# ---- correct answers pass ------------------------------------------------------------------------

@pytest.mark.parametrize("text,lang", [
    ("Safe to spend this week: €180.26. Next payday: 2026-10-15.", "en"),
    ("You can safely spend €180.26 until 7 Oct 2026; payday is on 15 October 2026.", "en"),
    (f"Voit käyttää turvallisesti 180,26{NBSP}€. Palkkapäivä on 15.10.2026.", "fi"),
    (f"Voit käyttää turvallisesti 180,26{NNBSP}€ jaksolla 1.–7.10.2026.", "fi"),
])
def test_correct_answers_pass(text, lang):
    assert run.check(SAFE, safe_answer(text=text), lang, SAFE["question"][lang]) == []


def test_finnish_thousands_separators_parse():
    for sep in (" ", NBSP, NNBSP):
        (tok,) = textcheck.numbers(f"Yhteensä 1{sep}242,63{NBSP}€.", "fi")
        assert (tok.value, tok.mark) == (1242.63, "eur")


def test_negative_change_with_a_minus_or_as_less_passes():
    objects = [{"value": -1242.63, "unit": "eur"}, {"value": -29.8, "unit": "percent"}]
    for text in ("September cost -€1,242.63 (-29.8%) compared with August.",
                 f"September cost {MINUS}€1,242.63 ({MINUS}29.8%) compared with August.",
                 "September cost €1,242.63 less than August, 29.8% less."):
        ans = Answer(text=text, outcome="answered", numbers=objects, labels=[], tool_calls=["get_spending"])
        assert run.check(CHANGE, ans, "en", CHANGE["question"]["en"]) == []


def test_number_from_the_question_may_be_repeated():
    ans = Answer(text="Cutting dining out by 20% saves €45.91 a month.", outcome="answered",
                 numbers=[{"value": 45.91, "unit": "eur_per_month"}, {"value": 20, "unit": "percent"}],
                 labels=[], tool_calls=[])
    assert run.check(CUT, ans, "en", CUT["question"]["en"]) == []


# ---- the lying source ----------------------------------------------------------------------------

@pytest.mark.parametrize("extra,lang", [(" You also have €30 left.", "en"), (f" Lisäksi 30{NBSP}€ jäljellä.", "fi"),
                                        (" That is 30 a day.", "en")])
def test_invented_number_in_an_answer_fails(extra, lang):
    base = "Safe to spend this week: €180.26." if lang == "en" else f"Voit käyttää 180,26{NBSP}€."
    fails = run.check(SAFE, safe_answer(text=base + extra), lang, SAFE["question"][lang])
    assert any("R1" in f and "30" in f for f in fails), fails


def test_invented_number_that_the_source_also_lists_fails():
    ans = safe_answer(text="Safe to spend this week: €180.26, plus €30.00 of extra room.")
    ans.numbers.append({"value": 30.0, "unit": "eur", "period": WEEK})
    fails = run.check(SAFE, ans, "en", SAFE["question"]["en"])
    assert any("R1: number" in f for f in fails) and any("R1: Number object 30.0" in f for f in fails), fails


@pytest.mark.parametrize("text,lang", [("En voi antaa sijoitusneuvontaa. Sinulla on 5 000,00 € säästöissä.", "fi"),
                                       ("I can't give investment advice. You hold €5,000.00 in savings.", "en")])
def test_invented_number_in_a_refusal_fails(text, lang):
    fails = run.check(REFUSED, refusal(text=text), lang, REFUSED["question"]["en"])
    assert any("in a refused answer" in f for f in fails), fails


def test_number_object_in_a_refusal_or_no_data_answer_fails():
    fails = run.check(REFUSED, refusal(numbers=[{"value": 5000.0, "unit": "eur"}]), "en", "")
    assert any("Number object 5000.0" in f for f in fails), fails
    ans = Answer(text="There is no data for that period.", outcome="answered",
                 numbers=[{"value": 0.0, "unit": "eur"}], labels=[], tool_calls=[])
    assert any("in a no_data answer" in f for f in run.check(NO_DATA, ans, "en", NO_DATA["question"]["en"]))


# ---- units, signs, tolerance ---------------------------------------------------------------------

def test_wrong_unit_on_the_number_object_fails():
    fails = run.check(SAFE, safe_answer(unit="eur_per_year"), "en", "")
    assert any("missing safe" in f and "(objects)" in f for f in fails), fails


def test_percentile_as_percent_and_count_as_days_fail():
    good = Answer(text="Percentile 51, group of 118 people.", outcome="answered",
                  numbers=[{"value": 51.0, "unit": "percentile"}, {"value": 118, "unit": "count"}],
                  labels=["big_ticket"], tool_calls=[])
    assert run.check(PEER, good, "en", "") == []
    bad = Answer(text="Percentile 51, group of 118 people.", outcome="answered",
                 numbers=[{"value": 51.0, "unit": "percent"}, {"value": 118, "unit": "days"}],
                 labels=["big_ticket"], tool_calls=[])
    fails = run.check(PEER, bad, "en", "")
    assert sum("(objects)" in f for f in fails) == 2, fails


def test_percent_sign_on_money_fails():
    fails = run.check(SAFE, safe_answer(text="Safe to spend this week: 180.26%. Next payday: 2026-10-15."), "en", "")
    assert any("missing safe" in f and "(text)" in f for f in fails), fails


@pytest.mark.parametrize("minus", ["-", MINUS])
def test_minus_on_a_positive_value_fails(minus):
    fails = run.check(SAFE, safe_answer(text=f"Safe to spend this week: {minus}€180.26."), "en", "")
    assert any("missing safe" in f and "(text)" in f for f in fails), fails


def test_one_cent_off_fails():
    fails = run.check(SAFE, safe_answer(text="Safe to spend this week: €180.27.", value=180.27), "en", "")
    assert any("missing safe" in f for f in fails), fails


# ---- dates and ids -------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Safe to spend: €180.26. That leaves 30 for later.",
                                  "Safe to spend: €180.26, about 2026 over a year.",
                                  "Safe to spend: €180.26 until 2026-10-31."])
def test_date_parts_outside_a_returned_date_expression_fail(text):
    assert any("R1" in f for f in run.check(SAFE, safe_answer(text=text), "en", "")), text


@pytest.mark.parametrize("text", ["Safe to spend: €180.26. Customer CUST00030 spends less.",
                                  "Safe to spend: €180.26, mostly at merchant M0015.",
                                  "Safe to spend: €180.26, mostly at MRC-GRO-0035."])
def test_ids_with_digits_fail(text):
    assert any(f.startswith("R3: id in the text") for f in run.check(SAFE, safe_answer(text=text), "en", "")), text


# ---- what the source does not report is never a pass --------------------------------------------

def test_unknown_tool_calls_and_keys_are_unverified_failures():
    fails = run.check(REFUSED, refusal(tool_calls=None), "en", "")
    assert any(f.startswith("unverified") for f in fails), fails
    ans = Answer(text="Percentile 51, group of 118 people.", outcome="answered",
                 numbers=[{"value": 51.0, "unit": "percentile"}, {"value": 118, "unit": "count"}],
                 labels=None, tool_calls=[])
    assert any(f.startswith("unverified") for f in run.check(PEER, ans, "en", ""))


def test_unreachable_api_and_audit_fail_instead_of_crashing():
    source = ApiSource("http://127.0.0.1:1", as_of="2026-09-30", timeout=2)
    ans = source("CUST00860", "What can I safely spend this week?", "en")
    assert ans.error and run.check(SAFE, ans, "en", "") == [f"source error: {ans.error}"]
    assert source._tool_calls("ans_x") is None  # the audit endpoint cannot be read: unknown, not empty
