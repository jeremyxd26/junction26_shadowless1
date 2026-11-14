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


def test_finnish_thousands_separators_match_the_formatter():
    for sep in (" ", NBSP, NNBSP):
        assert answer_text.display_matches(f"1{sep}242,63{NBSP}€", 1242.63, "eur", "fi")


def test_negative_change_with_its_display_passes():
    for minus in ("-", "−"):
        objects = [num(-1242.63, "eur", f"{minus}€1,242.63"), num(-29.8, "percent", f"{minus}29.8%")]
        ans = Answer(text=f"September cost {minus}€1,242.63 ({minus}29.8%) compared with August.", outcome="answered",
                     numbers=objects, labels=[], tool_calls=["get_spending"])
        assert run.check(CHANGE, ans, "en", CHANGE["question"]["en"]) == []


def test_number_from_the_question_as_user_input_percent_passes():
    ans = Answer(text="Cutting dining out by 20% saves €45.91 a month.", outcome="answered",
                 numbers=[num(45.91, "eur_per_month", "€45.91 a month"), num(20.0, "percent", "20%", method="user_input@1")],
                 labels=[], tool_calls=[])
    assert run.check(CUT, ans, "en", CUT["question"]["en"]) == []


def test_a_typed_cut_shown_with_a_decimal_fails():
    """#111: the formatter writes a whole typed percentage as "20%", so "20.0%" does not state it."""
    ans = Answer(text="Cutting dining out by 20.0% saves €45.91 a month.", outcome="answered",
                 numbers=[num(45.91, "eur_per_month", "€45.91 a month"), num(20.0, "percent", "20.0%", method="user_input@1")],
                 labels=[], tool_calls=[])
    assert any("does not state it" in f for f in run.check(CUT, ans, "en", CUT["question"]["en"]))


# ---- invented numbers ----------------------------------------------------------------------------

@pytest.mark.parametrize("extra", [" You also have €30 left.", " That is 30 a day.", " Plus 2026 more."])
def test_invented_number_in_an_answer_fails(extra):
    fails_with(SAFE, safe_answer(text="Safe to spend this week: €180.26." + extra), "en", "R1")


def test_invented_finnish_number_fails():
    fails_with(SAFE, fi_safe(f"Voit käyttää 180,26{NBSP}€. Lisäksi 30{NBSP}€ jäljellä."), "fi", "R1")


def test_invented_number_that_the_source_also_declares_fails():
    ans = safe_answer(text="Safe to spend this week: €180.26, plus €30.00 of extra room.",
                      numbers=[num(180.26, "eur", "€180.26"), num(30.0, "eur", "€30.00")])
    fails_with(SAFE, ans, "en", "unverified: Number object 30.0 eur")          # tools unknown: never a pass
    ans.tool_numbers = [{"id": None, "value": 180.26, "unit": "eur"}]               # the tools returned only 180.26
    fails_with(SAFE, ans, "en", "R1: Number object 30.0 eur was not returned by a tool of this answer")


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
    good = Answer(text="You are at the 51st percentile, in a group of 118 people.", outcome="answered",
                  numbers=[num(51.0, "percentile", "51st percentile"), num(118, "count", "118")], labels=["big_ticket"],
                  tool_calls=[])
    assert run.check(PEER, good, "en", "") == []
    bad = Answer(text="Percentile 51.0%, group of 118 people.", outcome="answered",
                 numbers=[num(51.0, "percent", "51.0%"), num(118, "days", "118")], labels=["big_ticket"], tool_calls=[])
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
                 numbers=[num(45.91, "eur_per_month", "€45.91 a month"),
                          num(20.0, "eur_per_month", "€20.00 a month", method="user_input@1")],
                 labels=[], tool_calls=[])
    fails_with(CUT, ans, "en", "R1: Number object 20.0 eur_per_month is declared as user input", CUT["question"]["en"])


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
    ans = Answer(text="Percentile 51.0%, group of 118 people.", outcome="answered",
                 numbers=[num(51.0, "percentile", "51.0%"), num(118, "count", "118")], labels=None, tool_calls=[])
    fails_with(PEER, ans, "en", "unverified")


def test_unreachable_api_and_audit_fail_instead_of_crashing():
    source = ApiSource("http://127.0.0.1:1", as_of="2026-09-30", timeout=2)
    ans = source("CUST00860", "What can I safely spend this week?", "en")
    assert ans.error and run.check(SAFE, ans, "en", "") == [f"source error: {ans.error}"]
    assert source._tool_calls("ans_x") is None  # the audit endpoint cannot be read: unknown, not empty


# ---- third review: displays next to a unit, the dash class, look-alike digits, date order ---------

TAXI = {
    "id": "t-taxi", "persona": "CUST00860", "intent": "spending", "expect": "answered",
    "question": {"en": "How much did I spend on taxis last month?", "fi": "Paljonko käytin takseihin viime kuussa?"},
    "expected_tools": [], "tags": ["t"],
    "numbers": [{"name": "taxi_total", "value": 52.84, "unit": "eur", "tolerance": 0.005},
                {"name": "taxi_rides", "value": 1, "unit": "count", "tolerance": 0}],
}
AUG = {"start": "2026-08-01", "end": "2026-08-31"}


def taxi_answer(text, lang="en"):
    total = "€52.84" if lang == "en" else f"52,84{NBSP}€"
    return Answer(text=text, outcome="answered", labels=[], tool_calls=[],
                  numbers=[num(52.84, "eur", total, AUG), num(1, "count", "1", AUG)])


@pytest.mark.parametrize("text,lang", [
    ("Taxis cost €52.84 over 1 ride, plus a tip 1 € each.", "en"),
    ("Taxis cost €52.84 over 1 ride, that is 1 % of spending.", "en"),
    (f"Takseihin meni 52,84{NBSP}€, 1 kyyti ja juomaraha 1 €.", "fi"),
])
def test_declared_count_cannot_be_reused_as_money_or_percent(text, lang):
    fails_with(TAXI, taxi_answer(text, lang), lang, "R1")


def test_display_after_a_colon_with_nbsp_is_removed():
    ans = taxi_answer(f"Summa:{NBSP}52,84{NBSP}€, kyytejä: 1.", "fi")
    assert run.check(TAXI, ans, "fi", TAXI["question"]["fi"]) == []
    assert run.check(SAFE, fi_safe(f"Summa: 180,26{NBSP}€."), "fi", "") == []


@pytest.mark.parametrize("text", ["Taxis cost €52.84 over 1 ride, and €⁵⁰ more.", "Taxis cost €52.84 over 1 ride, ⑤ times."])
def test_look_alike_digits_fail(text):
    fails_with(TAXI, taxi_answer(text), "en", "R1")


def test_a_declared_count_inside_a_returned_range_does_not_break_the_date():
    case = {"id": "t-r3", "persona": "CUST00849", "intent": "spending", "expect": "answered",
            "question": {"en": "How much did I spend on restaurants in the last 3 months?"}, "expected_tools": [], "tags": ["t"],
            "numbers": [{"name": "total", "value": 1102.0, "unit": "eur", "tolerance": 0.005},
                        {"name": "n", "value": 30, "unit": "count", "tolerance": 0, "required": False}]}
    q3 = {"start": "2026-07-01", "end": "2026-09-30"}
    ans = Answer(text="1 Jul – 30 Sep 2026. Restaurants: €1,102.00. Transactions: 30.", outcome="answered",
                 numbers=[num(1102.0, "eur", "€1,102.00", q3), num(30, "count", "30", q3)], labels=[], tool_calls=[])
    assert run.check(case, ans, "en", case["question"]["en"]) == []
    # The count is optional: an answer without it passes too.
    ans2 = Answer(text="1 Jul – 30 Sep 2026. Restaurants: €1,102.00.", outcome="answered",
                  numbers=[num(1102.0, "eur", "€1,102.00", q3)], labels=[], tool_calls=[])
    assert run.check(case, ans2, "en", case["question"]["en"]) == []


# ---- fourth review: a closing € before a date or amount, unit words, display suffixes ------------

@pytest.mark.parametrize("text", [
    f"Voit käyttää 180,26{NBSP}€ 15.10.2026 asti.",
    f"Voit käyttää 180,26{NBSP}€ 2026-10-15 asti.",
    f"Voit käyttää 180,26{NBSP}€ 15. lokakuuta 2026 asti.",
])
def test_a_closing_euro_sign_before_a_date_is_fine(text):
    assert run.check(SAFE, fi_safe(text), "fi", SAFE["question"]["fi"]) == []


def test_a_closing_euro_sign_before_another_amount_is_fine():
    case = {**CUT, "numbers": [{"name": "saving", "value": 45.91, "unit": "eur", "tolerance": 0.005},
                               {"name": "base", "value": 229.56, "unit": "eur", "tolerance": 0.005}]}
    ans = Answer(text=f"Säästö olisi 45,91{NBSP}€ 229,56{NBSP}€:sta.", outcome="answered", labels=[], tool_calls=[],
                 numbers=[num(45.91, "eur", f"45,91{NBSP}€"), num(229.56, "eur", f"229,56{NBSP}€")])
    assert run.check(case, ans, "fi", "Paljonko säästäisin?") == []


@pytest.mark.parametrize("text,lang", [("Taxis cost €52.84 over 1 ride, tip € 1 each.", "en"),
                                       ("Taxis cost €52.84 over 1 ride, and 1 euro of tip.", "en"),
                                       ("Taxis cost €52.84 over 1 ride, and 1 EUR of tip.", "en"),
                                       ("Taxis cost €52.84 over 1 ride, 1 percent of spending.", "en"),
                                       (f"Takseihin meni 52,84{NBSP}€, 1 kyyti, 1 prosenttia kulutuksesta.", "fi")])
def test_a_count_next_to_a_currency_or_unit_word_fails(text, lang):
    fails_with(TAXI, taxi_answer(text, lang), lang, "R1")


# ---- fifth review: a display is valid only if it equals the server's formatter output -------------

@pytest.mark.parametrize("value,unit,en,fi", [
    (180.26, "eur", "€180.26", "180,26 €"),
    (-1242.63, "eur", "-€1,242.63", "-1 242,63 €"),
    (12.5, "eur_per_day", "€12.50 a day", "12,50 € / pv"),
    (180.26, "eur_per_week", "€180.26 a week", "180,26 € / vk"),
    (1209.05, "eur_per_month", "€1,209.05 a month", "1 209,05 € / kk"),
    (551.0, "eur_per_year", "€551.00 a year", "551,00 € / v"),
    (-29.8, "percent", "-29.8%", "-29,8 %"),
    (51.0, "percentile", "51st percentile", "51. persentiili"),
    (118, "count", "118", "118"),
    (15, "days", "15 days", "15 pv"),
    (6, "months", "6 months", "6 kk"),
])
def test_every_formatter_display_passes(value, unit, en, fi):
    assert answer_text.formatted(value, unit, "en") == en and answer_text.formatted(value, unit, "fi") == fi
    for display in (en, en.replace("-", "−")):
        assert answer_text.display_matches(display, value, unit, "en")
    for display in (fi, fi.replace(" ", NBSP), fi.replace(" ", NNBSP)):
        assert answer_text.display_matches(display, value, unit, "fi")


@pytest.mark.parametrize("display,value,unit", [
    ("1 euro", 1, "count"), ("1 EUR", 1, "count"), ("1 prosenttia", 1, "count"), ("1 $", 1, "count"),
    ("20% euros", 20.0, "percent"), ("€45.91 a year", 45.91, "eur_per_month"), ("€30", 180.26, "eur"),
    ("€180.26", 180.26, "eur_per_month"), ("180.26%", 180.26, "eur"), ("€180.26", -180.26, "eur"),
    ("51", 51.0, "percentile"), ("118", 118, "days"),
])
def test_displays_that_are_not_the_formatter_output_fail(display, value, unit):
    assert not answer_text.display_matches(display, value, unit, "en")
    assert not answer_text.display_matches(display, value, unit, "fi")


@pytest.mark.parametrize("display,value,unit,language,ok", [
    ("4,120", 4120, "count", "en", True),
    ("4 120", 4120, "count", "fi", True),
    ("4,120", 4120, "count", "fi", False),     # reads as 4.12 in Finnish
    ("4 120", 4120, "count", "en", False),
    ("€180.26", 180.26, "eur", "fi", False),   # the English form in a Finnish answer
    ("180,26 €", 180.26, "eur", "en", False),
    ("12,5 %", 12.5, "percent", "en", False),
    ("€180.26", 180.26, "eur", None, False),   # no language, no match
])
def test_only_the_answers_own_language_counts(display, value, unit, language, ok):
    """Review of #128: the form of the stated language only, not either language's."""
    assert answer_text.display_matches(display, value, unit, language) is ok


# ---- #111: the check compares through the same method-aware formatter -----------------------------

@pytest.mark.parametrize("display,value,unit,method,language,ok", [
    ("20%", 20.0, "percent", "user_input@1", "en", True),
    ("20 %", 20.0, "percent", "user_input@1", "fi", True),
    ("20.0%", 20.0, "percent", "user_input@1", "en", False),
    ("20.0%", 20.0, "percent", None, "en", True),
    ("72nd percentile", 72.0, "percentile", "peer_benchmark.percentile@1", "en", True),
    ("72. persentiili", 72.0, "percentile", "peer_benchmark.percentile@1", "fi", True),
    ("72.0%", 72.0, "percentile", "peer_benchmark.percentile@1", "en", False),
    ("32.3% more", 32.3, "percent", "peer_benchmark.vs_median_pct@1", "en", True),
    ("31,0 % vähemmän", -31.0, "percent", "peer_benchmark.vs_median_pct@1", "fi", True),
    ("-31.0%", -31.0, "percent", "peer_benchmark.vs_median_pct@1", "en", False),
    ("31.0% more", -31.0, "percent", "peer_benchmark.vs_median_pct@1", "en", False),
    ("14.2 a month", 14.2, "count", "spender_profile.everyday_tx_month@1", "en", True),
    ("14", 14.2, "count", "spender_profile.everyday_tx_month@1", "en", False),
    ("€0.00", -0.001, "eur", None, "en", True),
    ("-€0.00", -0.001, "eur", None, "en", False),
])
def test_display_is_checked_with_the_numbers_method(display, value, unit, method, language, ok):
    assert answer_text.display_matches(display, value, unit, language, method=method) is ok


def test_same_value_uses_the_method():
    vs = "peer_benchmark.vs_median_pct@1"
    assert answer_text.same_value(32.3, 32.34, "percent", vs)
    assert not answer_text.same_value(32.3, -32.3, "percent", vs)   # "more" is not "less"
    assert answer_text.same_value(20, 20.0, "percent", "user_input@1")


def test_a_capitalised_month_after_a_number_starts_a_sentence():
    case = {"id": "t-cap", "persona": "CUST00349", "intent": "spending", "expect": "answered",
            "question": {"fi": "Paljonko käytin ravintoloihin heinäkuussa?"}, "expected_tools": [], "tags": ["t"],
            "numbers": [{"name": "n", "value": 10, "unit": "count", "tolerance": 0}]}
    jul = {"start": "2026-07-01", "end": "2026-07-31"}
    ans = Answer(text="Ostoksia oli 10. Heinäkuussa 2026 käytit ravintoloihin.", outcome="answered",
                 numbers=[num(10, "count", "10", jul)], labels=[], tool_calls=[])
    assert run.check(case, ans, "fi", case["question"]["fi"]) == []


# ---- sixth review: the rounding edge, more unit words ---------------------------------------------

@pytest.mark.parametrize("value,display", [(45.915, "€45.92 a month"), (45.909, "€45.91 a month")])
def test_a_value_at_the_rounding_edge_is_judged_by_its_display(value, display):
    ans = Answer(text=f"Cutting dining out by 20% saves {display}.", outcome="answered", labels=[], tool_calls=[],
                 numbers=[num(value, "eur_per_month", display), num(20.0, "percent", "20%", method="user_input@1")])
    fails = run.check(CUT, ans, "en", CUT["question"]["en"])
    if display == "€45.91 a month":   # shown as the SQL value: the user sees the right number
        assert fails == []
    else:                             # 45.915 is shown as 45.92, which is not the SQL value 45.91
        assert any("missing saving" in f for f in fails), fails


def test_zero_point_zero_zero_five_is_not_zero():
    case = {"id": "t-zero", "persona": "CUST00493", "intent": "spending", "expect": "answered",
            "question": {"en": "How much did I spend on taxis this month?"}, "expected_tools": [], "tags": ["t"],
            "numbers": [{"name": "taxi", "value": 0.0, "unit": "eur", "tolerance": 0.005}]}
    ans = Answer(text="Taxis this month: €0.01.", outcome="answered", labels=[], tool_calls=[],
                 numbers=[num(0.005, "eur", "€0.01")])
    fails_with(case, ans, "en", "missing taxi")


@pytest.mark.parametrize("word", ["cent", "cents", "senttiä", "USD", "pct", "e"])
def test_more_unit_words_after_a_count_fail(word):
    lang = "fi" if word in ("senttiä", "e") else "en"
    total = "€52.84" if lang == "en" else f"52,84{NBSP}€"
    fails_with(TAXI, taxi_answer(f"Taxis: {total}, 1 ride and 1 {word} extra.", lang), lang, "R1")


# ---- issue #112: verified tool numbers beyond the case's list -------------------------------------

class FakeDeriver:
    """Stands in for derive.Deriver: SQL says the yearly saving is 550.95."""

    def problem(self, case, number):
        if number.get("method") == "what_if.saving_year_eur@1" and number["value"] != 550.95:
            return f"Number object {number['value']} {number['unit']} (what_if.saving_year_eur@1) does not match the SQL value"
        return None


def cut_answer(text, extra):
    numbers = [dict(num(45.91, "eur_per_month", "€45.91 a month", method="what_if.saving_month_eur@1"), id="n2"), extra]
    return Answer(text=text, outcome="answered", labels=[], tool_calls=[], numbers=numbers,
                  tool_numbers=[{"id": n["id"], "value": n["value"], "unit": n["unit"]} for n in numbers])


def test_a_verified_tool_number_beyond_the_case_passes():
    year = dict(num(550.95, "eur_per_year", "€550.95 a year", method="what_if.saving_year_eur@1"), id="n4")
    ans = cut_answer("Cutting dining out saves €45.91 a month, or €550.95 a year.", year)
    assert run.check(CUT, ans, "en", CUT["question"]["en"], FakeDeriver()) == []


def test_a_tool_number_that_does_not_match_sql_fails():
    year = dict(num(560.0, "eur_per_year", "€560.00 a year", method="what_if.saving_year_eur@1"), id="n4")
    ans = cut_answer("Cutting dining out saves €45.91 a month, or €560.00 a year.", year)
    fails = run.check(CUT, ans, "en", CUT["question"]["en"], FakeDeriver())
    assert any("does not match the SQL value" in f for f in fails), fails


def test_the_yearly_figure_where_the_monthly_one_is_asked_fails():
    """Red-team probe of #112: a correct tool number with the wrong meaning for the question. The case
    requires the monthly saving, so an answer that gives only the yearly one fails as "missing"."""
    year = dict(num(550.95, "eur_per_year", "€550.95 a year", method="what_if.saving_year_eur@1"), id="n4")
    ans = Answer(text="Cutting dining out saves €550.95 a year.", outcome="answered", labels=[], tool_calls=[],
                 numbers=[year], tool_numbers=[{"id": "n4", "value": 550.95, "unit": "eur_per_year"}])
    fails_with(CUT, ans, "en", "missing saving", CUT["question"]["en"])
