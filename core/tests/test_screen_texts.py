"""#554: texts the API sends for the screen are localised and in plain language: the persona taglines in
Finnish, the evidence method summaries without file names, and the review's "why" saying what the answer
changes. No database."""

from __future__ import annotations

import re
from datetime import date

import pytest

from core.agent import template
from core.app.api import personas, texts
from core.tools import config


def test_finnish_personas_carry_finnish_taglines():
    en = {p["customer_id"]: p["tagline"] for p in personas.build("en", date(2026, 9, 30)).model_dump()["personas"]}
    fi = {p["customer_id"]: p["tagline"] for p in personas.build("fi", date(2026, 9, 30)).model_dump()["personas"]}
    assert set(en) == set(fi) and len(fi) == 4
    for customer, tagline in fi.items():
        assert tagline and tagline != en[customer], customer      # every persona has its own Finnish line
        assert not re.search(r"[0-9]", tagline), customer          # taglines carry no numbers (personas.yaml)
    assert "kodin ja tekniikan" in fi["CUST00860"]


@pytest.mark.parametrize("method", sorted(texts.METHODS))
def test_no_method_summary_names_a_file(method):
    for lang, summary in zip(("en", "fi"), texts.METHODS[method].summary):
        assert summary.strip(), (method, lang)
        assert "core/" not in summary and ".sql" not in summary, (method, lang, summary)


def test_the_safe_to_spend_summary_says_what_it_is_made_of():
    en, fi = texts.METHODS["safe_to_spend.safe_to_spend_7d_eur@1"].summary
    assert "smaller of what your balance allows and what your monthly budget allows" in en
    assert "savings goal" in en and "säästötavoite" in fi


def test_the_review_why_says_that_the_answer_can_change_safe_to_spend():
    for why in (config.REVIEW_TEXT["why"], template.REVIEW_WHY):
        en, fi = why
        assert "which basket it goes into, which can change your safe to spend" in en
        assert "mihin koriin se kuuluu" in fi and "turvallisesti käytettävissä" in fi
        assert "only how your own spending is grouped" not in en and "vain sitä" not in fi


SAFE_TO_SAVE = {   # each number of metrics.md section 3.1 gets its own sentence (review of #612)
    "safe_to_save_monthly_eur": "after bills, essentials, the reserve and your usual everyday spending",
    "free_month_eur": "before everyday spending",
    "everyday_month_eur": "everyday spending in a typical month",
    "essentials_shortfall_month_eur": "exceed your income in a typical month",
    "safe_to_save_eur": "never below zero",
    "everyday_until_payday_eur": "for the days until payday",
    "save_reason_month_eur": "why a typical month leaves nothing",
}


@pytest.mark.parametrize("column, phrase", sorted(SAFE_TO_SAVE.items()))
def test_each_safe_to_save_number_has_its_own_true_sentence(column, phrase):
    en, fi = texts.METHODS[f"safe_to_spend.{column}@1"].summary
    assert phrase in en and fi.strip()


def test_the_safe_to_save_sentences_are_all_different():
    summaries = [texts.METHODS[f"safe_to_spend.{c}@1"].summary for c in SAFE_TO_SAVE]
    assert len(set(summaries)) == len(summaries)


def test_the_savings_goal_is_not_called_the_customers_own_choice():
    en, fi = texts.METHODS["safe_to_spend.savings_goal_eur@1"].summary
    assert en.startswith("A monthly savings goal, set aside first") and "you set aside" not in en
    assert "jonka laitat" not in fi
