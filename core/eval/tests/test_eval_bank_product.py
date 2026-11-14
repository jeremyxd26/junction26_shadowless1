"""#417: the eval fails an answer that names an amount and the bank's screen or product in one sentence,
on every case, and its case `sanna-save-more-host-screen` asks the question that invites it. No database."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run  # noqa: E402  (core/eval/run.py)
from sources import Answer  # noqa: E402

CASES = Path(__file__).resolve().parents[1] / "cases.yaml"
SAVE = {
    "id": "t-save", "persona": "CUST00860", "intent": "save_more", "expect": "answered",
    "question": {"en": "How could I save more with monthly saving in S-mobiili?"},
    "expected_tools": ["get_safe_to_save"], "tags": ["t"],
    "numbers": [{"name": "save", "value": 184.61, "unit": "eur_per_month", "tolerance": 0.005}],
}
MONTH = {"start": "2026-04-01", "end": "2026-09-30", "label": "1 Apr – 30 Sep 2026"}


def answer(text: str) -> Answer:
    n = {"value": 184.61, "unit": "eur_per_month", "display": "€184.61 a month", "period": MONTH,
         "method": "safe_to_spend.safe_to_save_monthly_eur@1"}
    return Answer(text=text, outcome="answered", numbers=[n], labels=[], tool_calls=["get_safe_to_save"])


def test_the_amount_beside_monthly_saving_fails():
    fails = run.check(SAVE, answer("Put €184.61 a month into monthly saving in S-mobiili."), "en",
                      SAVE["question"]["en"])
    assert fails == ["amount beside the bank's screen or product: "
                     "'Put €184.61 a month into monthly saving in S-mobiili.'"]


def test_the_amount_and_the_screen_in_separate_sentences_pass():
    text = "You could set aside about €184.61 a month. The button opens monthly saving in S-mobiili."
    assert run.check(SAVE, answer(text), "en", SAVE["question"]["en"]) == []


def test_the_case_asks_the_inviting_question_in_both_languages():
    cases = {c["id"]: c for c in yaml.safe_load(CASES.read_text(encoding="utf-8"))["cases"]}
    case = cases["sanna-save-more-host-screen"]
    assert "monthly saving in S-mobiili" in case["question"]["en"]
    assert "kuukausisäästämi" in case["question"]["fi"] and "S-mobiili" in case["question"]["fi"]
    # the save-more answer whose card carries the button: safe to save, or the savings plan of #369 on dev
    assert case["expected_tools"][0] in ("get_safe_to_save", "get_savings_plan") and case["expect"] == "answered"
