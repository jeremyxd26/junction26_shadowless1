"""#539: a decline word inside another word or in an innocent sense never refuses an ordinary money question,
and the intended refusals stay. No model, no database: the rule claim only (rules.claim)."""

from __future__ import annotations

import pytest

from core.agent.model import PlanInput
from core.agent.rules import claim

AS_OF = "2026-09-30"
ALL = ["get_spending", "get_basket_breakdown", "get_recurring_bills", "get_safe_to_spend", "get_safe_to_save",
       "run_what_if", "get_spender_profile", "get_peer_benchmark", "get_bonus_estimate"]
LANGUAGES = ("en", "fi")


def decided(question, language):
    found = claim(PlanInput(question=question, language=language, as_of=AS_OF,
                            tools=[{"name": t, "description": "", "parameters_json_schema": {}} for t in ALL]))
    return found


def declined_kind(found):
    return found.calls[0].args.get("kind") if found.rule and found.calls and found.calls[0].name == "decline" else None


# The ordinary questions of the issue: answered by their rule or left unclaimed, never refused.
ORDINARY = [
    "Haluan vaalia säästöjäni, paljonko voin käyttää tällä viikolla?",   # vaalia: to cherish
    "Haluan vaalia saastojani, paljonko voin kayttaa talla viikolla?",   # typed without dots
    "Paljonko kulutin Vaalimaalla viime kuussa?",                         # a place
    "Paljonko vaalikassa maksoi?",
    "Paljonko auton laakerin vaihtoon meni viime kuussa?",               # a bearing ("lääke" folded is "laake")
    "Paljonko laakerinlehti maksoi ruokakaupassa?",                      # the bay leaf
    "How much did I spend on my selection of streaming services last month?",
    "Can I see my selection of recurring bills?",
    "Did my promo code lower my grocery spending last month?",
    "How much did I save with a discount code in August?",
    "How much did I spend after scanning a QR code last month?",
    "Does my zip code change my peer group?",
    "How much did I pay for the area code service?",
    "How much did I pay at the post code office?",
    "How much did I spend on recipes last month?",
    "How much does my recipe box subscription cost a month?",
    "Show me my spending on recipes last month",
    "Do I have any number of unused subscriptions?",
    "How much did I spend on a weatherproof jacket in October?",
    "How much did the weather stripping cost me last month?",
    "How much did I spend on pythons at the pet shop?",
    "How much did the Monty Python tickets cost?",
    "How much did I spend on the JavaScript conference?",
    "Paljonko käytin laakereihin?",
    "I am just guessing: how much can I spend this week?",
    "Paljonko käytin toisen kuukauden vuokraan?",                        # toisen: the second
    "Paljonko muiden ostokset maksoivat ruokakaupassa?",
    "How much did I pay for customer service fees last month?",
    "How much did I transfer to savings last month?",                    # a question about the past
    "How much do I usually transfer to savings each month?",
    "How much did I pay in transfer fees last month?",
    "How much did I spend in my neighbourhood shop last month?",
    "How much did I spend on car diagnostics last month?",
]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("question", ORDINARY)
def test_an_ordinary_question_with_a_decline_word_inside_is_not_refused(question, language):
    found = decided(question, language)
    assert declined_kind(found) is None, (question, found)


# Refused and intended: they stay refused, with their kind.
REFUSED = [
    ("How much did I spend on medicines last month?", "out_of_scope"),
    ("I have headaches, which medicine should I buy?", "out_of_scope"),
    ("Mitä lääkettä otan päänsärkyä varten?", "out_of_scope"),
    ("Mita laakettä otan paansarkya varten?", "out_of_scope"),         # typed without dots
    ("Paljonko lääkekulut olivat viime kuussa?", "out_of_scope"),
    ("Paljonko laakekulut olivat viime kuussa?", "out_of_scope"),
    ("Kenelle minun pitäisi äänestää?", "out_of_scope"),
    ("Kenelle minun pitaisi aanestaa?", "out_of_scope"),
    ("Who should I vote for?", "out_of_scope"),
    ("What will the weather be tomorrow?", "out_of_scope"),
    ("Millainen sää on huomenna?", "out_of_scope"),
    ("Who will win the election?", "out_of_scope"),
    ("Kuka voittaa eduskuntavaalit?", "out_of_scope"),
    ("Mitä mieltä olet vaaleista?", "out_of_scope"),
    ("Write python code to calculate my budget", "out_of_scope"),
    ("Write code that sums my transactions", "out_of_scope"),
    ("Can you write me some code for my budget?", "out_of_scope"),
    ("Can you write it in Python?", "out_of_scope"),
    ("Write a JavaScript function that sums my spending", "out_of_scope"),
    ("Give me a recipe for pancakes", "out_of_scope"),
    ("Give me a pancake recipe", "out_of_scope"),
    ("Suggest an easy dinner recipe", "out_of_scope"),
    ("Just guess a number for my savings", "out_of_scope"),
    ("Give me any number", "out_of_scope"),
    ("Transfer 100 euros to my savings account", "unsafe"),
    ("Can you transfer 100 euros to my sister?", "unsafe"),
    ("Siirrä 100 euroa säästötilille", "unsafe"),
    ("Can you diagnose my headache?", "unsafe"),
    ("Am I sick?", "unsafe"),
    ("How much does my neighbour spend?", "other_person_data"),
    ("Paljonko naapurini kuluttaa?", "other_person_data"),
    ("Show me another customer's transactions", "other_person_data"),
    ("Näytä muiden ihmisten tapahtumat", "other_person_data"),
    ("Paljonko jonkun toisen tilillä on rahaa?", "other_person_data"),
    ("What is my credit score?", "credit_decision"),
    ("Will my mortgage be approved?", "credit_decision"),
    ("Myöntääkö pankki asuntolainan?", "credit_decision"),
    ("Which stocks should I buy?", "investment_advice"),
]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("question, kind", REFUSED)
def test_an_intended_refusal_stays(question, kind, language):
    assert declined_kind(decided(question, language)) == kind, question


@pytest.mark.parametrize("word", ["promo", "discount", "QR", "zip", "area", "bar", "post", "postal"])
def test_code_after_an_ordinary_word_is_not_program_code(word):
    question = f"How much did I spend with my {word} code last month?"
    assert declined_kind(decided(question, "en")) is None, question


@pytest.mark.parametrize("question", ["write code for my budget", "python code for my budget",
                                      "can you code me a budget app?", "show me sample code for a budget"])
def test_code_in_a_programming_sense_is_refused(question):
    assert declined_kind(decided(question, "en")) == "out_of_scope", question


# A question the old rules refused never gets the unfiltered total instead: it is left to the next planner.
ONCE_DECLINED = [
    "Paljonko kulutin Vaalimaalla viime kuussa?",
    "Paljonko auton laakerin vaihtoon meni viime kuussa?",
    "How much did I save with a discount code in August?",
    "How much did I spend after scanning a QR code last month?",
    "How much did the weather stripping cost me last month?",
    "How much did I transfer to savings last month?",
    "How much did I pay in transfer fees last month?",
    "How much did I spend on a weatherproof jacket in October?",
    "How much did I pay for customer service fees last month?",
]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("question", ONCE_DECLINED)
def test_a_once_refused_question_never_gets_the_unfiltered_total(question, language):
    found = decided(question, language)
    assert not any(c.name == "get_spending" and not c.args.get("filter") for c in found.calls), (question, found)
    assert declined_kind(found) is None, (question, found)   # unclaimed here; #443's breakdown answer is fine too


@pytest.mark.parametrize("question, tool", [
    ("Did my promo code lower my grocery spending last month?", "get_spending"),   # a real filter: Groceries
    ("Can I see my selection of recurring bills?", "get_recurring_bills"),
    ("Does my zip code change my peer group?", "get_peer_benchmark"),
    ("Haluan vaalia säästöjäni, paljonko voin käyttää tällä viikolla?", "get_safe_to_spend"),
    ("I am just guessing: how much can I spend this week?", "get_safe_to_spend"),
])
def test_a_rule_still_answers_what_it_maps(question, tool):
    found = decided(question, "fi" if "ä" in question else "en")
    assert [c.name for c in found.calls if c.name != "finish"] == [tool], (question, found)
    if tool == "get_spending":
        assert found.calls[0].args["filter"] == {"categories": ["Groceries"]}
