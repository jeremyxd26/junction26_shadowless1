"""#650: "other Finns", "the average Finn", "keskiverto suomalainen" and "suomalaiset keskimäärin" are the peer
comparison, as "people like me" is (the wording of the Statistics Finland comparison, #585). No database."""

from __future__ import annotations

import pytest

from core.agent.model import PlanInput
from core.agent.rules import RuleModel

ALL = ["get_spending", "get_basket_breakdown", "get_recurring_bills", "get_safe_to_spend", "get_safe_to_save",
       "run_what_if", "get_spender_profile", "get_peer_benchmark", "get_bonus_estimate"]


def plan(question, language):
    return RuleModel().plan(PlanInput(question=question, language=language, as_of="2026-09-30",
                                      tools=[{"name": t, "description": "", "parameters_json_schema": {}} for t in ALL]))


def calls(question, language):
    return [(c.name, c.args) for c in plan(question, language).calls if c.name != "finish"]


@pytest.mark.parametrize("lang,question,metric", [
    ("en", "How does my spending compare to other Finns?", "spend_total"),
    ("en", "Do I spend more than other Finns on groceries?", "Groceries"),
    ("en", "Do I spend more on groceries than the average Finn?", "Groceries"),
    ("en", "Is my grocery spending normal compared to other Finns?", "Groceries"),
    ("en", "Am I spending more than the average Finn?", "spend_total"),
    ("en", "How does my spending compare to the Finnish average?", "spend_total"),
    ("en", "Do I spend more on transportation than other Finns?", "Transportation"),
    ("fi", "Kulutanko ruokaan enemmän kuin keskiverto suomalainen?", "Groceries"),
    ("fi", "Kulutanko ruokaan enemmän kuin suomalaiset keskimäärin?", "Groceries"),
    ("fi", "Kulutanko enemmän kuin keskimääräinen suomalainen?", "spend_total"),
    ("fi", "Miten kulutukseni vertautuu suomalaisiin?", "spend_total"),
    ("fi", "Kulutanko liikkumiseen enemmän kuin suomalaiset keskimäärin?", "Transportation"),
])
def test_a_comparison_with_finns_is_the_peer_benchmark(lang, question, metric):
    # dev 5602596 asked which period for these
    assert calls(question, lang) == [("get_peer_benchmark", {"metric": metric})]


@pytest.mark.parametrize("lang,question", [
    ("en", "Do I spend more on restaurants than other Finns?"),
    ("fi", "Kulutanko vaatteisiin enemmän kuin suomalaiset keskimäärin?"),
])
def test_a_category_outside_the_national_table_keeps_what_people_like_me_gives(lang, question):
    like_me = question.replace("other Finns", "people like me").replace("suomalaiset keskimäärin", "muut kaltaiseni")
    assert calls(question, lang) == calls(like_me, lang)
    assert calls(question, lang)[0][0] == "get_peer_benchmark"


@pytest.mark.parametrize("lang,question", [
    ("en", "How much do Finns spend on groceries?"), ("en", "What do Finns spend on average?"),
    ("en", "Do I spend more than my wife and other Finns?"), ("en", "Does my wife spend more than the average Finn?"),
    ("fi", "Kuluttaako mieheni enemmän kuin keskiverto suomalainen?"),
])
def test_finns_without_the_user_or_with_a_named_person_stay_declined(lang, question):
    assert calls(question, lang) == [("decline", {"kind": "other_person_data"})]


@pytest.mark.parametrize("lang,question", [
    ("en", "Should I invest like the average Finn?"), ("en", "Should I invest like people like me?"),
    ("en", "Should I start investing like the average Finn?"), ("en", "How should I invest compared to people like me?"),
    ("en", "Where should I invest my savings?"), ("en", "Is it smart to invest like other Finns?"),
    ("fi", "Pitäisikö minun sijoittaa kuten keskiverto suomalainen?"),
    ("fi", "Pitäisikö minun sijoittaa kuten muut kaltaiseni?"), ("fi", "Miten minun pitäisi sijoittaa?"),
    ("fi", "Pitäisikö minun alkaa sijoittaa?"), ("fi", "Mihin voin sijoittaa rahani?"),
])
def test_whether_or_how_to_invest_is_declined_before_the_peer_rule(lang, question):
    # review of #655, R7: dev answered the "people like me" forms with the peer total and asked back for the others
    assert calls(question, lang) == [("decline", {"kind": "investment_advice"})]


@pytest.mark.parametrize("lang,question,metric", [
    ("en", "Do I spend more than the average Finn on groceries?", "Groceries"),
    ("en", "How much do I spend compared to people like me?", "spend_total"),
    ("fi", "Kulutanko enemmän kuin muut kaltaiseni?", "spend_total"),
])
def test_a_spending_comparison_next_to_the_invest_rule_stays_the_peer_benchmark(lang, question, metric):
    assert calls(question, lang) == [("get_peer_benchmark", {"metric": metric})]


def test_spending_less_to_invest_is_no_investment_advice():
    assert calls("Should I spend less so I can invest?", "en")[0][0] != "decline"


@pytest.mark.parametrize("lang,question", [
    ("en", "What do other Finns spend on groceries?"), ("fi", "Paljonko keskiverto suomalainen kuluttaa?"),
])
def test_finns_with_no_comparison_with_the_user_are_no_peer_question(lang, question):
    assert "get_peer_benchmark" not in [name for name, _ in calls(question, lang)]
