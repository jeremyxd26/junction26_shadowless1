"""#540: "What can Sentti do?" gets the introduction, and "what does <bill> cost a month / a year?" plans the bills
tool (that bill's typical month) or the spending of the category over the last 12 months. Every row of the issue's
table, the controls that must not change, and the answer sentences. No model, no database."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from core.agent import guard, template
from core.agent.model import PlanInput
from core.agent.rules import RuleModel, meta_intent
from core.agent.toolset import default_registry
from core.tools import bills, config
from core.tools.models import Number, Period, Unit

TOOLS = default_registry().schemas()


def planned(question: str):
    lang = guard.detect_language(question) or "en"
    plan = RuleModel().plan(PlanInput(question=guard.clean(question), language=lang, as_of="2026-09-30",
                                      tools=TOOLS, history=[]))
    return [(c.name, c.args) for c in plan.calls if c.name != "finish"]


@pytest.mark.parametrize("question", [
    "Mitä Sentti osaa?", "Mitä Sentti osaa tehdä?", "What can Sentti do?", "What can Sentti help me with?",
    "Mitä osaat?", "What can you do?",
])
def test_what_sentti_can_do_gets_the_introduction(question):
    assert meta_intent(question) == "capabilities", question


@pytest.mark.parametrize("question", [
    "Paljonko sähkö maksaa kuukaudessa?", "Paljonko vuokra maksaa kuukaudessa?", "Paljonko vesi maksaa kuussa?",
    "What does my rent cost a month?", "How much does electricity cost per month?",
    "Mitä asuminen maksaa kuukaudessa?",
])
def test_what_a_bill_costs_a_month_plans_the_bills(question):
    assert planned(question) == [("get_recurring_bills", {})], question


@pytest.mark.parametrize("question, category", [
    ("Mitä vuokra maksaa vuodessa?", "Housing"), ("Mitä sähkö maksaa vuodessa?", "Utilities"),
    ("How much is my rent a year?", "Housing"),
])
def test_what_a_bill_costs_a_year_plans_the_spending_of_the_last_12_months(question, category):
    assert planned(question) == [("get_spending", {"filter": {"categories": [category]},
                                                   "period": {"preset": "last_12_months"}})], question


@pytest.mark.parametrize("question, expected", [
    ("What does food cost a month?", "ask_clarifying_question"),      # not a bill category: unchanged
    ("Which bills are due this month?", "get_recurring_bills"),
    ("Mitä laskuja on tulossa tässä kuussa?", "get_recurring_bills"),
    ("How much did I spend on rent in the last 12 months?", "get_spending"),
    ("How much are my bills a month?", "get_recurring_bills"),
])
def test_the_controls_plan_as_before(question, expected):
    assert planned(question)[0][0] == expected, question


# Not the customer's own bill a month or a year: a scenario, a number, renting something, a duration, a named month.
# Each keeps the plan it had before #540 (the decision table of the PR).
@pytest.mark.parametrize("question, expected", [
    ("What if my rent costs 50 more a month?", "ask_clarifying_question"),
    ("Mitä jos sähkö maksaa 20 euroa enemmän kuukaudessa?", "ask_clarifying_question"),
    ("What would my rent cost a year if it went up 5%?", "ask_clarifying_question"),
    ("How much does it cost to rent a car for a month?", "ask_clarifying_question"),
    ("Paljonko sähkö maksaa tässä kuussa?", "get_spending"),
    ("Paljonko sähkö maksaa ensi kuussa?", "ask_clarifying_question"),
    ("What does my rent cost this month?", "get_spending"),
    ("How much will electricity cost next year?", "ask_clarifying_question"),
])
def test_not_a_bill_a_month_or_a_year(question, expected):
    assert template.bill_cost(guard.fold(question)) is None, question
    assert planned(question)[0][0] == expected, question


def bills_view(language: str, with_utilities: bool = True) -> dict:
    """The shape of bills.model_view: no bill id (#487), the series label in the answer's language."""
    def n(nid, value, display):
        return {"id": nid, "value": value, "unit": "eur_per_month", "label": "x", "display": display}
    labels = {"en": ("Housing", "Utilities"), "fi": ("Asuminen", "Kodin laskut")}[language]
    rows = [{"label": labels[0], "status": "done_this_month", "typical_day": 3,
             "typical_month": n("n2", 836.65, "€836.65 a month"), "due_until_payday": n("n3", 0.0, "€0.00"),
             "next_expected": "2026-10-03"}]
    if with_utilities:
        rows.append({"label": labels[1], "status": "spread", "typical_day": None,
                     "typical_month": n("n4", 186.4, "€186.40 a month"), "due_until_payday": n("n5", 91.85, "€91.85"),
                     "next_expected": None})
    return {"tool": "get_recurring_bills", "window": "Apr-Sep 2026", "due_period": "1-15 Oct 2026",
            "next_payday": "2026-10-15", "salary_status": "received_this_month",
            "upcoming_total": {"id": "n1", "value": 928.5, "unit": "eur", "label": "x", "display": "€928.50"},
            "bills": rows, "income": [], "notes": []}


def test_the_fixture_has_the_shape_of_the_real_model_view():
    """The one-bill sentence finds the bill by its series label, since the model view has no bill id (#487)."""
    def num(value):
        return Number(value=value, unit=Unit.EUR_PER_MONTH, method="bills.typical@1",
                      period=Period(start=date(2026, 4, 1), end=date(2026, 9, 30), label="Apr-Sep 2026"),
                      evidence_ref="ev_000000000001", label="x", display="x")
    item = SimpleNamespace(bill_id="bill_utilities_payment", label=config.SERIES_LABELS["utilities_payment"][0],
                           status="spread", typical_day=None, typical_month=num(186.4), due_until_payday=num(91.85),
                           next_expected=None)
    data = SimpleNamespace(window=SimpleNamespace(label="Apr-Sep 2026"), due_period=SimpleNamespace(label="1-15 Oct"),
                           next_payday=date(2026, 10, 15), salary_status="received_this_month",
                           upcoming_total=num(928.5), bills=[item], income=[])
    real = bills._model_view(data, [])["bills"][0]
    assert set(real) == set(bills_view("en")["bills"][1]) and "bill_id" not in real
    for language in ("en", "fi"):
        assert [b["label"] for b in bills_view(language)["bills"]] == [
            config.label(config.SERIES_LABELS[k], language) for k in ("housing_payment", "utilities_payment")]


def answer(question: str, language: str, view: dict) -> str:
    draft = template.template_draft([view], [], language, None, question)
    return draft["text"] if isinstance(draft, dict) else draft


@pytest.mark.parametrize("question, language, sentence", [
    ("Paljonko sähkö maksaa kuukaudessa?", "fi", "Kodin laskut: tavallisesti {{n4}}."),
    ("Paljonko vuokra maksaa kuukaudessa?", "fi", "Asuminen: tavallisesti {{n2}}."),
    ("How much does electricity cost per month?", "en", "Your utilities bills usually come to {{n4}}."),
    ("What does my rent cost a month?", "en", "Your housing bills usually come to {{n2}}."),
    ("Paljonko vesi maksaa kuussa?", "fi", "Kodin laskut: tavallisesti {{n4}}."),
])
def test_the_answer_names_that_bills_typical_month(question, language, sentence):
    assert sentence in answer(question, language, bills_view(language))


def test_without_that_bill_the_regular_bills_are_named():
    text = answer("How much does electricity cost per month?", "en", bills_view("en", with_utilities=False))
    assert "Your regular bills are housing at {{n2}}." in text and "utilities" not in text


@pytest.mark.parametrize("question, language", [("Which bills are due this month?", "en"),
                                                ("Mitä laskuja on tulossa tässä kuussa?", "fi")])
def test_the_due_bills_answer_stays(question, language):
    text = answer(question, language, bills_view(language))
    assert "{{n1}}" in text and "tavallisesti" not in text and "usually" not in text
