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
    "how much did I send to my landlord",                           # a question about own payments, not a request
    "did I pay 30 euros to Elisa",
    "What if I pay 50 euros to savings every month?",
    "How much did I pay to my landlord last month?",
    "I paid 500 euros to my landlord, how much is left?",
    "Paljonko lähetin äidilleni elokuussa?",
    "Paljonko maksoin vuokranantajalle 30 euroa?",
    "Jos maksan 50 euroa säästöön kuussa, paljonko säästän?",
    "Pay attention to my grocery spending last month",
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
    ("Send 20 euros to my friend.", "unsafe"),                     # a request to move money (security read of #550)
    ("Move fifty euros to my savings account now.", "unsafe"),
    ("Make a payment of 30 euros to my landlord.", "unsafe"),
    ("Can you send €20 to my sister?", "unsafe"),
    ("Please wire 1000 euros to my brother", "unsafe"),
    ("Send me 50 euros", "unsafe"),
    ("Pay twenty-five euros to Elisa now", "unsafe"),
    ("Lähetä 20 euroa ystävälleni", "unsafe"),
    ("Laheta 20 euroa ystavalleni", "unsafe"),
    ("Maksa 30 euroa vuokranantajalle", "unsafe"),
    ("Voitko lähettää viisikymmentä euroa äidilleni?", "unsafe"),
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


# ---- review of #550, pass 1: fixes 1 to 4 ---------------------------------------------------------------------------

FIX_REFUSED = [
    # a recipe asked for in any words; Python and JavaScript as such
    ("Pancake recipe please", "out_of_scope"), ("Recipe ideas for dinner", "out_of_scope"),
    ("Cookie recipes please", "out_of_scope"), ("Tell me your pancake recipe", "out_of_scope"),
    ("Teach me Python", "out_of_scope"), ("Explain python lists", "out_of_scope"),
    ("Teach me JavaScript", "out_of_scope"), ("Kirjoita python koodi", "out_of_scope"),
    ("Pythonilla koodaaminen on kivaa, kirjoita koodia", "out_of_scope"), ("Kirjoita JavaScript-funktio", "out_of_scope"),
    # the election compounds, and "vaaleista" at the end of a clause
    ("Mikä on vaalikone?", "out_of_scope"), ("Mikä oli vaalitulos?", "out_of_scope"),
    ("Mitä mieltä olet vaalituloksesta?", "out_of_scope"), ("Kuka on vaaliehdokas?", "out_of_scope"),
    ("Milloin vaalikampanja alkaa?", "out_of_scope"), ("Mitä mieltä olet vaaleista?", "out_of_scope"),
    # a present-tense transfer is a request
    ("How do I transfer money to my savings?", "unsafe"), ("how do I transfer", "unsafe"),
    ("Do I transfer 100 euros to savings now?", "unsafe"), ("Do we transfer 500 euros to my account?", "unsafe"),
    ("Transfer costs of 100 euros to my savings account", "unsafe"),
    # a customer service agent is a person; other people's money nouns
    ("Show me the customer service agent's account", "other_person_data"),
    ("Muiden kulutus", "other_person_data"), ("Muiden menot", "other_person_data"),
    ("Muiden rahat", "other_person_data"),
]


@pytest.mark.parametrize("question, kind", FIX_REFUSED)
def test_the_review_rows_are_refused_again(question, kind):
    assert declined_kind(decided(question, "fi" if any(ch in question for ch in "äö") or
                                 question.split()[0] in ("Mikä", "Kuka", "Milloin", "Muiden", "Kirjoita",
                                                          "Pythonilla") else "en")) == kind, question


FIX_ORDINARY = [
    "How much does my recipe box subscription cost a month?", "Show me my spending on recipes last month",
    "How much did the Monty Python tickets cost?", "How much did I spend on pythons at the pet shop?",
    "How much did I spend on the JavaScript conference?", "Paljonko käytin Python-kirjaan?",
    "I used a promo code a friend sent me, how much did I save last month?",
    "How much did I transfer to savings last month?", "How much do I usually transfer to savings each month?",
    "How much did I pay in transfer fees last month?", "What was my last transfer to savings?",
    "When was my last transfer to savings?", "How much does a bank transfer cost me per year?",
    "Paljonko maksoivat vaaleista housuista?",                           # light trousers, not the elections
    "Paljonko maksoin lainapäätöksen jälkeen kodin sisustukseen?",       # after the loan decision: own spending
    "Does the customer service fee show up in my bills?",
]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("question", FIX_ORDINARY)
def test_the_review_rows_stay_ordinary(question, language):
    assert declined_kind(decided(question, language)) is None, question


def test_other_peoples_purchases_stay_the_planners():
    # the issue's row: "muiden ostokset" is left to the next planner (the people rules cannot tell whose), not refused
    found = decided("Paljonko muiden ostokset maksoivat ruokakaupassa?", "fi")
    assert found.rule is None and declined_kind(found) is None


# The decline entries before #539 (base 858c0b5), entries 2 to 6, as they were: every alternative must still be in
# DECLINED_BEFORE_539, so that a question they refused never gets the unfiltered total (review of #550, fix 5).
OLD_ENTRIES = (
    r"\bCUST\d+|\bcustomer\b|neighbou?r|naapuri|someone else|other (people|customers)|muiden|toisen",
    r"mortgage|credit ?score|creditworth|approve (my |a )?loan|loan (be )?approved|asuntolaina|luottokelpo|myöntääkö|"
    r"lainapäätös",
    r"\b(should|which|what|best)\b.*\b(stocks?|shares?|funds?|etfs?|crypto|bitcoin)\b|\binvest(ing)? (in|into)\b|"
    r"\bput (my|the) (money|savings) into\b|kannattaako.*(sijoit|osak|rahasto)|mihin (minun )?(pitäisi|kannattaa) sijoittaa",
    r"\bam i (ill|sick|pregnant)\b|what illness|diagnos|olenko (sairas|raskaana)",
    r"just (estimate|guess)|any number|make up (a |an |some )?(number|amount|figure)|"
    r"guess (a |an |some )?(number|amount|figure)|invent (a |an )?(number|amount)|keksi (jokin |joku )?(luku|summa)|"
    r"arvaa (jokin |joku )?(luku|summa)|mikä tahansa (luku|summa)|python|javascript|\bcode\b|\bvote\b|äänestää|election|"
    r"vaali|medicine|headache|lääke|päänsärky|weather|recipe",
)


def _top_level(pattern):
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(pattern):
        if ch == "(" and pattern[i - 1:i] != "\\":
            depth += 1
        elif ch == ")" and pattern[i - 1:i] != "\\":
            depth -= 1
        elif ch == "|" and depth == 0:
            parts.append(pattern[start:i])
            start = i + 1
    return parts + [pattern[start:]]


def test_the_once_refused_guard_keeps_every_old_alternative():
    from core.agent import rules
    from core.agent.guard import fold_pattern
    guard = set(_top_level(rules.DECLINED_BEFORE_539))
    missing = [alt for entry in OLD_ENTRIES for alt in _top_level(fold_pattern(entry)) if alt not in guard]
    assert missing == [], missing
