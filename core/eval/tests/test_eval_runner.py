"""Regression tests for the eval checks (core/eval/run.py, core/answer_text.py). No database.

Every answer that lies must fail. The attacks come from the reviews of PR #57: invented numbers in
answers and refusals, a lying source that also declares its invented number, wrong units and signs
(hyphen, minus sign, en dash, figure dash), a percent sign on money, ids with digits (also glued to
letters), money swallowed by a date expression, dates that were not returned, a number from the
question turned into money, a display that does not state its own value, and a source whose audit
cannot be read.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run  # noqa: E402  (core/eval/run.py)
from core import answer_text  # noqa: E402
from sources import Answer, ApiSource  # noqa: E402

NBSP, NNBSP = " ", " "
MINUSES = ["-", "−", "–", "‒"]   # hyphen-minus, minus sign, en dash, figure dash

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


def num(value, unit, display, period=WEEK, method="safe_to_spend.safe_to_spend_7d_eur@1"):
    return {"value": value, "unit": unit, "display": display, "period": period, "method": method}


def safe_answer(text="Safe to spend this week: €180.26. Next payday: 2026-10-15.", numbers=None, **kw):
    fields = dict(text=text, outcome="answered", numbers=numbers or [num(180.26, "eur", "€180.26")],
                  dates=["2026-09-30", "2026-10-15"], labels=[], tool_calls=["get_safe_to_spend"])
    fields.update(kw)
    return Answer(**fields)


def fi_safe(text):
    return safe_answer(text=text, numbers=[num(180.26, "eur", f"180,26{NBSP}€")])


def refusal(text="I can't give investment advice. An S-Pankki adviser can help.", **kw):
    fields = dict(text=text, outcome="refused", refusal_kind="investment_advice", labels=[], tool_calls=["decline"])
    fields.update(kw)
    return Answer(**fields)


def fails_with(case, ans, lang, needle, question=""):
    fails = run.check(case, ans, lang, question)
    assert any(needle in f for f in fails), fails
    return fails


# ---- correct answers pass ------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Safe to spend this week: €180.26. Next payday: 2026-10-15.",
    "You can safely spend €180.26 until 7 Oct 2026; payday is on 15 October 2026.",
    "For 1–7 Oct 2026 you can spend €180.26.",
])
def test_correct_english_answers_pass(text):
    assert run.check(SAFE, safe_answer(text=text), "en", SAFE["question"]["en"]) == []


@pytest.mark.parametrize("text", [f"Voit käyttää turvallisesti 180,26{NBSP}€. Palkkapäivä on 15.10.2026.",
                                  f"Voit käyttää 180,26{NBSP}€ jaksolla 1.–7.10.2026.",
                                  f"Voit käyttää 180,26{NBSP}€ ennen palkkapäivää 15. lokakuuta 2026."])
def test_correct_finnish_answers_pass(text):
    assert run.check(SAFE, fi_safe(text), "fi", SAFE["question"]["fi"]) == []


def test_finnish_thousands_separators_parse():
    for sep in (" ", NBSP, NNBSP):
        assert answer_text.parse_display(f"1{sep}242,63{NBSP}€", "fi") == (1242.63, "eur")


def test_negative_change_with_its_display_passes():
    for minus in ("-", "−"):
        objects = [num(-1242.63, "eur", f"{minus}€1,242.63"), num(-29.8, "percent", f"{minus}29.8%")]
        ans = Answer(text=f"September cost {minus}€1,242.63 ({minus}29.8%) compared with August.", outcome="answered",
                     numbers=objects, labels=[], tool_calls=["get_spending"])
        assert run.check(CHANGE, ans, "en", CHANGE["question"]["en"]) == []


def test_number_from_the_question_as_user_input_percent_passes():
    ans = Answer(text="Cutting dining out by 20.0% saves €45.91 a month.", outcome="answered",
                 numbers=[num(45.91, "eur_per_month", "€45.91"), num(20.0, "percent", "20.0%", method="user_input@1")],
                 labels=[], tool_calls=[])
    assert run.check(CUT, ans, "en", CUT["question"]["en"]) == []


# ---- invented numbers ----------------------------------------------------------------------------

@pytest.mark.parametrize("extra", [" You also have €30 left.", " That is 30 a day.", " Plus 2026 more."])
def test_invented_number_in_an_answer_fails(extra):
    fails_with(SAFE, safe_answer(text="Safe to spend this week: €180.26." + extra), "en", "R1")


def test_invented_finnish_number_fails():
    fails_with(SAFE, fi_safe(f"Voit käyttää 180,26{NBSP}€. Lisäksi 30{NBSP}€ jäljellä."), "fi", "R1")


def test_invented_number_that_the_source_also_declares_fails():
    ans = safe_answer(text="Safe to spend this week: €180.26, plus €30.00 of extra room.",
                      numbers=[num(180.26, "eur", "€180.26"), num(30.0, "eur", "€30.00")])
    fails_with(SAFE, ans, "en", "R1: Number object 30.0 eur is not an expected value")


def test_display_that_does_not_state_its_value_fails():
    ans = safe_answer(text="Safe to spend this week: €30.", numbers=[num(180.26, "eur", "€30")])
    fails_with(SAFE, ans, "en", "does not state it")


@pytest.mark.parametrize("text,lang", [("En voi antaa sijoitusneuvontaa. Sinulla on 5 000,00 € säästöissä.", "fi"),
                                       ("I can't give investment advice. You hold €5,000.00 in savings.", "en"),
                                       ("I can't give investment advice. You hold EUR5000.", "en")])
def test_invented_number_in_a_refusal_fails(text, lang):
    fails_with(REFUSED, refusal(text=text), lang, "R1")


def test_number_object_in_a_refusal_or_no_data_answer_fails():
    fails_with(REFUSED, refusal(numbers=[num(5000.0, "eur", "€5,000.00")]), "en", "in a refused answer")
    ans = Answer(text="There is no data for that period.", outcome="answered",
                 numbers=[num(0.0, "eur", "€0.00")], labels=[], tool_calls=[])
    fails_with(NO_DATA, ans, "en", "in a no_data answer")


# ---- units, signs, tolerance ---------------------------------------------------------------------

def test_wrong_unit_on_the_number_object_fails():
    fails_with(SAFE, safe_answer(numbers=[num(180.26, "eur_per_year", "€180.26")]), "en", "(objects)")


def test_percentile_as_percent_and_count_as_days_fail():
    good = Answer(text="Percentile 51, group of 118 people.", outcome="answered",
                  numbers=[num(51.0, "percentile", "51"), num(118, "count", "118")], labels=["big_ticket"], tool_calls=[])
    assert run.check(PEER, good, "en", "") == []
    bad = Answer(text="Percentile 51, group of 118 people.", outcome="answered",
                 numbers=[num(51.0, "percent", "51"), num(118, "days", "118")], labels=["big_ticket"], tool_calls=[])
    assert sum("(objects)" in f for f in run.check(PEER, bad, "en", "")) == 2


def test_percent_sign_on_money_fails():
    fails_with(SAFE, safe_answer(text="Safe to spend this week: €180.26%."), "en", "R1")
    fails_with(SAFE, safe_answer(text="Safe to spend: 180.26%.", numbers=[num(180.26, "eur", "180.26%")]), "en",
               "does not state it")


@pytest.mark.parametrize("minus", MINUSES)
def test_any_minus_or_dash_before_a_positive_value_fails(minus):
    fails_with(SAFE, safe_answer(text=f"Safe to spend this week: {minus}€180.26."), "en", "R1")


def test_one_cent_off_fails():
    ans = safe_answer(text="Safe to spend this week: €180.27.", numbers=[num(180.27, "eur", "€180.27")])
    fails_with(SAFE, ans, "en", "missing safe")


def test_number_from_the_question_turned_into_money_fails():
    ans = Answer(text="Cutting dining out saves €45.91 a month, or €20.00 a month more.", outcome="answered",
                 numbers=[num(45.91, "eur_per_month", "€45.91"), num(20.0, "eur_per_month", "€20.00", method="user_input@1")],
                 labels=[], tool_calls=[])
    fails_with(CUT, ans, "en", "R1: Number object 20.0 eur_per_month is not an expected value", CUT["question"]["en"])


# ---- dates ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Safe to spend: €180.26. In September 30 € went to fees.",   # a date expression must not swallow money
    "Safe to spend: €180.26, and after October 15 € more.",
    "Safe to spend: €180.26. Payday on 30 October 2026.",          # a real date that was not returned
    "Safe to spend: €180.26. Payday on 30.10.2026.",
    "Safe to spend: €180.26 until 2026-10-31.",
    "Safe to spend: €180.26, about 2026 over a year.",
])
def test_dates_that_are_not_returned_dates_fail(text):
    fails_with(SAFE, safe_answer(text=text), "en", "R1")


# ---- ids -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Safe to spend: €180.26. Customer CUST00030 spends less.", "Safe to spend: €180.26, mostly at merchant M0015.",
    "Safe to spend: €180.26, mostly at MRC-GRO-0035.", "Safe to spend: €180.26, mostly at merchant X12345.",
    "Safe to spend: €180.26, at MRC_00042.", "Safe to spend: €180.26, see TX99812.",
    "Safe to spend: €180.26, from IBAN DE89 3704 0044 0532 0130 00.", "Safe to spend: €180.26, like customer C00001.",
])
def test_ids_with_digits_fail(text):
    fails_with(SAFE, safe_answer(text=text), "en", "R1")


# ---- what the source does not report is never a pass --------------------------------------------

def test_unknown_tool_calls_and_keys_are_unverified_failures():
    fails_with(REFUSED, refusal(tool_calls=None), "en", "unverified")
    ans = Answer(text="Percentile 51, group of 118 people.", outcome="answered",
                 numbers=[num(51.0, "percentile", "51"), num(118, "count", "118")], labels=None, tool_calls=[])
    fails_with(PEER, ans, "en", "unverified")


def test_unreachable_api_and_audit_fail_instead_of_crashing():
    source = ApiSource("http://127.0.0.1:1", as_of="2026-09-30", timeout=2)
    ans = source("CUST00860", "What can I safely spend this week?", "en")
    assert ans.error and run.check(SAFE, ans, "en", "") == [f"source error: {ans.error}"]
    assert source._tool_calls("ans_x") is None  # the audit endpoint cannot be read: unknown, not empty
