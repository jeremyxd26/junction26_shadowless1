"""Object tests for the credit and investment classes (#677, follow-up of #657). No database.

#657 refused credit and investment questions as classes. A class with no object test also refused rare ordinary
wordings: a loan statement, a library loan, lending to a friend, borrowing from one's own savings goal. Those are
ordinary again; a bank, a lender or any source not on the allowlist keeps the refusal. Investing time keeps the
investment refusal (review of #682). The rows #657 left for later are refused by a rule, or are the planner's for a
written reason."""

from __future__ import annotations

import pytest

from core.agent.model import PlanInput
from core.agent.rules import claim
from core.agent.toolset import KNOWN_TOOLS

TOOLS = [{"name": t.function, "description": "", "parameters_json_schema": {}} for t in KNOWN_TOOLS]


def ask(question, lang="en"):
    return claim(PlanInput(question=question, language=lang, as_of="2026-09-30", tools=TOOLS))


def declined(found):
    return [c.args.get("kind") for c in found.calls if c.name == "decline"]


@pytest.mark.parametrize("question,lang", [
    ("Can I get a loan statement?", "en"), ("Saanko lainaa kirjastosta?", "fi"),
    ("Paljonko voin lainata kaverilleni?", "fi"), ("How much can I borrow from my savings goal?", "en"),
    ("Can I get a credit card statement?", "en"), ("Voinko saada lainaa ystävältä?", "fi"),
    ("Saanko lainaa isältäni?", "fi"), ("Voinko saada lainaa vanhemmiltani?", "fi"),   # the allowlist, a possessive
])
def test_the_rare_ordinary_wordings_are_not_refused(question, lang):
    found = ask(question, lang)
    assert not declined(found), (question, found)
    # never the unfiltered total for them
    assert not any(c.name == "get_spending" and not (c.args or {}).get("filter") for c in found.calls)


@pytest.mark.parametrize("question,lang", [   # the class keeps its refusals
    ("Can I get a loan?", "en"), ("Saanko lainaa pankista?", "fi"), ("Paljonko voin lainata pankista?", "fi"),
    ("How much can I borrow?", "en"), ("Saanko asuntolainan?", "fi"), ("Can I get a mortgage?", "en"),
    ("Can I borrow money?", "en"), ("Voinko saada lainaa?", "fi"),
])
def test_a_credit_decision_stays_refused(question, lang):
    assert declined(ask(question, lang)) == ["credit_decision"], question


@pytest.mark.parametrize("question,lang", [   # review of #682: the source is an allowlist, so a lender's name refuses
    ("Saanko lainaa Nordealta?", "fi"), ("Saanko lainaa Nordeasta?", "fi"), ("Voinko saada lainaa Klarnalta?", "fi"),
    ("Voinko saada autolainaa Santanderilta?", "fi"), ("Saanko lainaa Lähitapiolta?", "fi"),
    ("Saanko lainaa Handelsbankenilta?", "fi"), ("How much can I borrow from my account at the bank?", "en"),
])
def test_a_loan_from_a_lender_by_name_stays_refused(question, lang):
    assert declined(ask(question, lang)) == ["credit_decision"], question


@pytest.mark.parametrize("question", ["Should I invest in stocks?", "Should I invest my savings?", "Should I invest?",
                                      "Where should I invest?", "Should I invest more money?"])
def test_investment_advice_stays_refused(question):
    assert declined(ask(question)) == ["investment_advice"], question


@pytest.mark.parametrize("question", [   # review of #682: investing time keeps the refusal, the safe side of a hard rule
    "How should I invest my time in budgeting?", "Should I invest more time in checking my bills?",
    "How should I invest my time this month?", "How should I invest my time and money?",
    "Should I invest more time or money this month?",
])
def test_investing_time_stays_refused(question):
    assert declined(ask(question)) == ["investment_advice"], question


@pytest.mark.parametrize("question,lang,kind", [   # the rows #657 left for later, refused by a rule now
    ("Is my credit good enough for a car loan?", "en", "credit_decision"),
    ("What is my credit rating?", "en", "credit_decision"),
    ("Mikä on luottotietoni?", "fi", "credit_decision"),
    ("Do I have good credit?", "en", "credit_decision"),
    ("Can I get a credit card?", "en", "credit_decision"),
    ("Myöntäisikö pankki minulle lainan?", "fi", "credit_decision"),
    ("Would a lender accept me?", "en", "credit_decision"),
    ("Is now a good time to buy shares?", "en", "investment_advice"),
    ("Mihin rahasto kannattaa valita?", "fi", "investment_advice"),
    ("Is it smart to buy gold?", "en", "investment_advice"),
    ("Would you recommend stocks?", "en", "investment_advice"),
    ("Can you pick a fund for me?", "en", "investment_advice"),
    ("Are index funds better than savings?", "en", "investment_advice"),
])
def test_the_rows_left_for_later_are_refused_by_a_rule(question, lang, kind):
    assert declined(ask(question, lang)) == [kind], question


@pytest.mark.parametrize("question,lang", [
    # advice about borrowing is the planner's, as #627 wrote down: the credit decline's text is about approval, and the
    # planner's prompt never suggests borrowing
    ("Should I apply for a loan?", "en"), ("Should I take out a car loan?", "en"), ("Kannattaako ottaa laina?", "fi"),
    # no investment word: may be a saving question, so the planner decides (its prompt declines investment advice)
    ("What should I do with 5000 euros?", "en"), ("Where to put my money?", "en"),
])
def test_the_rows_written_down_as_the_planners(question, lang):
    found = ask(question, lang)
    assert found.rule is None and not declined(found), (question, found)


@pytest.mark.parametrize("question", ["How can I build an emergency fund?",
                                      "Can you recommend a way to build an emergency fund?",
                                      "Is it a good time to pay my bills?"])
def test_ordinary_money_wordings_near_the_new_patterns_are_not_refused(question):
    assert not declined(ask(question)), question
