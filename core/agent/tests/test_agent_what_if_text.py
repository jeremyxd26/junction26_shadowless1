"""#600 part 2: a model what-if draft that names the period before a number whose display already carries it ("Based on
a typical month of {{n}}" renders "a typical month of €294.73 a month") is rejected and retried, then the template
writes; the template's own what-if text is clean. No model, no database."""

from __future__ import annotations

from datetime import date

import pytest
from test_agent_human_answers import CASES, answer

from core.agent.validator import render, repeated_period
from core.tools.models import Number, Period, Unit

WINDOW = Period(start=date(2026, 4, 1), end=date(2026, 9, 30), label="1 Apr – 30 Sep 2026")


def numbers(lang):
    month = "{} a month" if lang == "en" else "{} € / kk"
    year = "{} a year" if lang == "en" else "{} € / v"
    return {
        "n1": Number(id="n1", value=294.73, unit=Unit.EUR_PER_MONTH, period=WINDOW, method="what_if.baseline_month_eur@1",
                     evidence_ref="ev_000000000001", label="Restaurants",
                     display=month.format("€294.73" if lang == "en" else "294,73")),
        "n2": Number(id="n2", value=58.95, unit=Unit.EUR_PER_MONTH, period=WINDOW, method="what_if.saving_month_eur@1",
                     evidence_ref="ev_000000000002", label="You would save",
                     display=month.format("€58.95" if lang == "en" else "58,95")),
        "n3": Number(id="n3", value=707.4, unit=Unit.EUR_PER_YEAR, period=WINDOW, method="what_if.saving_year_eur@1",
                     evidence_ref="ev_000000000003", label="Per year",
                     display=year.format("€707.40" if lang == "en" else "707,40")),
        "n4": Number(id="n4", value=242.49, unit=Unit.EUR, period=WINDOW, method="spending.total@1",
                     evidence_ref="ev_000000000004", label="Takeaway and fast food", display="€242.49"),
    }


@pytest.mark.parametrize("text, lang", [
    # the stand's two texts (QA on 33797a3, ans_unkz7msd and ans_34a3jpwa)
    ("Based on a typical month of {{n1}} on Restaurants, cutting back by 20% could save you {{n2}} an estimate "
     "based on past months.", "en"),
    ("Based on your takeaway and fast food in a typical month of {{n1}}, a cut of 20% would save you {{n2}}. This is "
     "an estimate based on past months.", "en"),
    ("In an average month you spend {{n1}} on restaurants, so a 20% cut could save about {{n2}}.", "en"),
    ("Your usual year of savings would be {{n3}}.", "en"),
    ("Tavallisena kuukautena käytät ravintoloihin {{n1}}, joten 20 %:n leikkaus säästäisi noin {{n2}}.", "fi"),
    ("Tyypillisen kuukauden kulutuksesi {{n1}} pienenisi, ja säästäisit noin {{n2}}.", "fi"),
])
def test_a_period_named_before_its_number_is_a_repeated_period(text, lang):
    found = repeated_period(text, numbers(lang))
    assert found, text
    assert found.endswith(numbers(lang)["n1" if "{{n1}}" in text else "n3"].display), found


@pytest.mark.parametrize("text, lang", [
    ("Cutting restaurants by 20% could save you about {{n2}}, or {{n3}}: an estimate based on past months.", "en"),
    ("Right now you spend {{n1}} on restaurants; a 20% cut could save about {{n2}}.", "en"),
    ("In a typical month of August 2026 you spent {{n4}} on takeaway and fast food.", "en"),   # no period unit
    ("That is a typical month for you. A 20% cut could save about {{n2}}.", "en"),            # another sentence
    ("Nyt käytät ravintoloihin {{n1}}, ja 20 %:n leikkaus säästäisi noin {{n2}}.", "fi"),
])
def test_a_plain_what_if_draft_passes(text, lang):
    assert repeated_period(text, numbers(lang)) is None, text


@pytest.mark.parametrize("lang", ["en", "fi"])
@pytest.mark.parametrize("key", sorted(k for k in CASES if k.startswith("what_if") or "what_if" in k))
def test_the_template_what_if_text_is_clean(key, lang):
    # the template writes after two rejected drafts: no period said twice, every sentence ends where it should
    draft, v, _, _ = answer(key, lang)
    text = draft["text"]
    assert repeated_period(text, v.numbers) is None, text
    rendered = render(text, v.numbers)
    assert "a month a month" not in rendered and "/ kk / kk" not in rendered, rendered
    assert rendered.rstrip().endswith("."), rendered
