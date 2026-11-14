"""The template answer: one takeaway per tool, the main number and at most three supporting ones."""

from __future__ import annotations

import pytest

from core.agent.template import TAKEAWAY_SIZE, takeaway, template_draft


def n(i, value, unit="eur", label="x"):
    return {"id": f"n{i}", "value": value, "unit": unit, "label": label}


SPENDING = {"tool": "get_spending", "period": "August 2026", "total": n(1, 52.84, label="Taxi"),
            "tx_count": n(2, 1, "count", "Transactions"), "comparison": None, "groups": [], "notes": []}
COMPARED = {**SPENDING, "comparison": {"label": "vs July 2026", "baseline": n(3, 40.0, label="July 2026"),
                                       "change": n(4, 12.84), "change_pct": n(5, 32.1, "percent")}}
BASKETS = {"tool": "get_basket_breakdown", "period": "1 Apr – 30 Sep 2026", "monthly_average": True,
           "total": n(9, 3010.59, "eur_per_month", "Total spending"),
           "baskets": [{"key": k, "label": lab, "amount": n(i, 1.0, "eur_per_month", lab), "share": n(i + 1, 10.0, "percent", "Share"),
                        "categories": [{"amount": n(i + 2, 1.0, "eur_per_month", "Housing")}]}
                       for i, (k, lab) in zip((10, 20, 30), [("regular_essentials", "Regular essentials"),
                                                             ("unexpected_necessities", "Unexpected necessities"),
                                                             ("everyday_spending", "Everyday spending")])]}
SAFE = {"tool": "get_safe_to_spend", "safe_to_spend": n(6, 180.26), "free_until_payday": n(7, 12567.56),
        "balance_limit": n(8, 5864.86), "budget_limit": n(9, 180.26), "components": [{"amount": n(10, 14276.35)}]}
WHAT_IF = {"tool": "run_what_if", "cut_pct": n(1, 20, "percent"), "baseline_per_month": n(2, 229.56, "eur_per_month"),
           "saving_per_month": n(3, 45.91, "eur_per_month"), "saving_per_week": n(4, 10.56, "eur_per_week"),
           "saving_per_year": n(5, 550.95, "eur_per_year")}
BILLS = {"tool": "get_recurring_bills", "next_payday": "2026-10-15", "upcoming_total": n(5, 928.5, label="Bills before payday"),
         "bills": [{"label": "Housing", "typical_month": n(1, 836.65, "eur_per_month"), "due_until_payday": n(2, 836.65)},
                   {"label": "Utilities", "typical_month": n(3, 186.4, "eur_per_month"), "due_until_payday": n(4, 91.86)}],
         "income": [{"label": "Salary", "typical_month": n(6, 3187.25, "eur_per_month")}]}


def ids(view, question=""):
    return [i for _, i in takeaway(view, question)[0]]


def test_spending_total_and_count_or_the_comparison():
    assert ids(SPENDING) == ["n1", "n2"]
    assert ids(COMPARED) == ["n1", "n3", "n4", "n5"]


def test_baskets_total_and_the_three_shares_named_by_basket():
    chosen, _ = takeaway(BASKETS)
    assert [i for _, i in chosen] == ["n9", "n11", "n21", "n31"]
    assert [lab for lab, _ in chosen][1:] == ["Regular essentials", "Unexpected necessities", "Everyday spending"]


def test_safe_to_spend_and_what_if():
    assert ids(SAFE) == ["n6", "n8", "n9"]
    assert ids(WHAT_IF) == ["n3", "n2", "n5"]       # the user's own cut stays out of the text


def test_bills_follow_the_question():
    assert ids(BILLS, "Which bills are coming up next?") == ["n5", "n2", "n4"]
    assert ids(BILLS, "What are my regular monthly bills?") == ["n1", "n3"]
    chosen, extra = takeaway(BILLS, "When is my next payday and how much do I usually get?")
    assert [i for _, i in chosen] == ["n6"] and extra == ["Next payday: 2026-10-15."]


def test_at_most_four_numbers_and_the_draft_cites_exactly_them():
    many = {"tool": "unknown_tool", **{f"k{i}": n(i, float(i)) for i in range(1, 9)}}
    assert len(ids(many)) == TAKEAWAY_SIZE
    draft = template_draft([BASKETS], [], "en", None, "Where did my money go?")
    # #342: the shares in sentences, largest first, then the monthly average.
    assert draft["cited"] == ["n11", "n21", "n31"]      # the monthly average stays on the card
    assert draft["text"].startswith("The largest share of your spending, {{n11}}, went to regular essentials.")


def test_a_label_with_a_digit_that_is_not_a_date_is_left_out():
    view = {**SAFE, "period": "Next 7 days"}
    draft = template_draft([view], [], "en", None, "What can I safely spend this week?")
    assert "7" not in draft["text"] and draft["cited"] == ["n6", "n8", "n9"]
    kept = template_draft([{**SPENDING}], [], "en", None, "How much on taxis last month?")
    assert kept["text"] == "You spent {{n1}} on taxi in August 2026, in {{n2}} transaction."   # #342: a count of 1


EVERYDAY = {"tool": "get_basket_breakdown", "period": "1 Apr – 30 Sep 2026", "monthly_average": True,
            "total": n(40, 3010.59, "eur_per_month", "Total spending"),
            "baskets": [{"key": "regular_essentials", "label": "Regular essentials", "share": n(41, 62.7, "percent", "Share"),
                         "categories": [{"key": "Housing", "label": "Housing", "amount": n(46, 1209.05, "eur_per_month")}]},
                        {"key": "unexpected_necessities", "label": "Unexpected necessities",
                         "share": n(42, 17.3, "percent", "Share"), "categories": []},
                        {"key": "everyday_spending", "label": "Everyday spending", "share": n(43, 19.9, "percent", "Share"),
                         "categories": [{"key": "Groceries", "label": "Groceries", "amount": n(44, 150.0, "eur_per_month")},
                                        {"key": "Restaurants", "label": "Restaurants",
                                         "amount": n(45, 229.56, "eur_per_month")}]}]}


SAVE = {"tool": "get_safe_to_save", "monthly": n(50, 364.31, "eur_per_month", "Safe to save a month"),
        "stock": n(51, 2100.0, "eur", "Beyond what you need until payday"), "reason": None}


def test_save_more_cites_four_numbers_and_offers_a_cut_without_an_amount():
    # #216: the monthly safe-to-save figure first, then the three basket shares; the offer names the
    # largest everyday category and asks by how much, never suggesting an amount.
    for question, lang, offer in [
            ("How could I save more?", "en", "Tell me how much you would cut restaurants by, and I'll show what you'd save."),
            ("Miten voisin säästää enemmän?", "fi",
             "Kerro, kuinka paljon vähentäisit luokassa Restaurants, niin näytän säästön.")]:
        draft = template_draft([SAVE, EVERYDAY], [], lang, None, question)
        assert draft["cited"] == ["n50"]   # #342, Renat's length rule: the shares stay on the basket card
        assert draft["text"].endswith(offer)
        assert not any(w in draft["text"] for w in ("half", "puoleen", "%"))


def test_the_offer_only_follows_the_save_more_plan():
    after_what_if = template_draft([WHAT_IF], [], "en", None, "How could I save more by cutting restaurants 20%?")
    assert "Tell me how much" not in after_what_if["text"]
    assert "Tell me how much" not in template_draft([BILLS], [], "en", None, "Which bills are coming up next?")["text"]
    no_categories = template_draft([BASKETS, BILLS], [], "en", None, "How could I save more?")["text"]
    assert no_categories.endswith("Name a category and how much you would cut it by, and I'll show what you'd save.")


@pytest.mark.parametrize("question", ["Which bills are due before payday?", "Which bills are coming up next?",
                                      "Mitkä laskut ovat tulossa seuraavaksi?",
                                      "Mitä laskuja on tulossa ennen palkkapäivää?"])
def test_a_bills_question_gets_the_bills_due_even_when_it_names_payday(question):
    assert ids(BILLS, question) == ["n5", "n2", "n4"]


@pytest.mark.parametrize("question", ["When is my next payday?", "Milloin on seuraava palkkapäivä?",
                                      "Paljonko tuloni ovat kuukaudessa?"])
def test_a_payday_question_without_bills_gets_the_income(question):
    assert ids(BILLS, question) == ["n6"]


@pytest.mark.parametrize("question", ["What's my take-home pay?", "What is my net pay?", "Paljonko tienaan?",
                                      "How much do I earn?", "Paljonko ansaitsen kuukaudessa?"])
def test_every_income_phrasing_the_rule_routes_gets_the_income(question):
    # Review of PR #296: these reached the bills tool but cited the bills due.
    assert ids(BILLS, question) == ["n6"]



def test_safe_to_save_with_nothing_left_gives_the_tools_reason():
    zero = {**SAVE, "monthly": n(50, 0, "eur_per_month", "Safe to save a month"),
            "reason": {"kind": "essentials_exceed_income", "category": None, "amount": n(52, 120.0, "eur_per_month"),
                       "text": "Bills and essentials already use up your income."}}
    draft = template_draft([zero], [], "en", None, "How much could I save a month?")
    assert draft["cited"][0] == "n50" and "Bills and essentials already use up your income." in draft["text"]


BONUS = {"tool": "get_bonus_estimate", "kind": "estimate", "status": "estimate",
         "share": n(60, 100, "percent", "Share at S-Group stores"), "grocery_month": n(61, 410.2, "eur_per_month", "Groceries a month"),
         "level_base": n(62, 410.2, "eur_per_month"), "bonus_percent": n(63, 2.0, "percent"),
         "bonus_month": n(64, 21.05, "eur_per_month", "Bonus a month"),
         "payment_benefit_month": n(65, 4.1, "eur_per_month", "Payment benefit a month"),
         "total_month": n(66, 25.15, "eur_per_month", "Bonus and payment benefit a month"),
         "total_year": n(67, 301.8, "eur_per_year", "Bonus and payment benefit a year"), "lowest_level": None,
         "reason": None, "assumptions": ["Assumes you are the only shopper in a co-op household.",
                                         "Assumes the share at S-Group stores; it is a what-if, not a fact about where you shop."]}


def test_the_bonus_answer_states_the_estimate_and_its_assumption():
    draft = template_draft([BONUS], [], "en", None, "How much S-Bonus could I get?")
    assert draft["cited"] == ["n66", "n60", "n67", "n61"]          # the share is cited with its own label
    assert "Share at S-Group stores: {{n60}}" in draft["text"]
    assert draft["text"].endswith("not a fact about where you shop.")
    nothing = {**BONUS, "status": "not_offered", "reason": "These purchases stay below the lowest Bonus level, so no Bonus would be paid."}
    draft = template_draft([nothing], [], "en", None, "How much S-Bonus could I get?")
    assert draft["cited"] == [] and "below the lowest Bonus level" in draft["text"]


PEER = {"tool": "get_peer_benchmark", "metric": "spend_total", "period": "1 Apr – 30 Sep 2026", "shown": True, "reason": None,
        "you": n(70, 3010.59, "eur_per_month", "You"), "peer_median": n(71, 2975.65, "eur_per_month", "Median of people like you"),
        "peer_p25": n(72, 2313.0, "eur_per_month"), "peer_p75": n(73, 3713.9, "eur_per_month"),
        "percentile": n(74, 51, "percentile", "Your position"), "vs_median": n(75, 1.2, "percent", "Compared with the median"),
        "peer_group": {"level": "age_band+area3", "label": "35-44, 005xx", "size": n(76, 118, "count", "People in the group"),
                       "comparable": True}}


def test_the_peer_answer_states_position_difference_median_and_group_size():
    draft = template_draft([PEER], [], "en", None, "How do I compare with people like me?")
    assert draft["cited"] == ["n74", "n75", "n71", "n76"]
    hidden = {**PEER, "shown": False, "reason": "group_too_small"}
    draft = template_draft([hidden], [], "en", None, "How do I compare with people like me?")
    assert draft["cited"] == [] and "too few people like you" in draft["text"]


def test_the_offer_names_only_a_category_the_rules_can_cut():
    shopping = {**EVERYDAY, "baskets": [b if b["key"] != "everyday_spending" else
                                        {**b, "categories": [{"key": "Health", "label": "Health",
                                                              "amount": n(80, 900.0, "eur_per_month")},
                                                             *b["categories"]]} for b in EVERYDAY["baskets"]]}
    text = template_draft([SAVE, shopping], [], "en", None, "How could I save more?")["text"]
    assert "health" not in text.lower() and text.endswith("cut restaurants by, and I'll show what you'd save.")



def test_the_profile_answer_names_the_type_before_its_numbers():
    # Review of #246: with the model off, "What kind of spender am I?" names the profile type.
    view = {"tool": "get_spender_profile", "period": "1 Apr – 30 Sep 2026",
            "profile": {"key": "big_ticket", "label": "Big ticket", "description": "A few large purchases shape your months."},
            "traits": [], "features": [{"key": "keep_rate", "decides_label": "Keep rate",
                                        "value": n(90, 15.4, "percent", "Keep rate")}],
            "top_everyday_category": None, "notes": []}
    for lang, lead in [("en", "Your spender profile: Big ticket. A few large purchases shape your months."),
                       ("fi", "Kuluttajaprofiilisi: Big ticket. A few large purchases shape your months.")]:
        text = template_draft([view], [], lang, None, "What kind of spender am I?")["text"]
        assert text.startswith(lead) and "{{n90}}" in text



@pytest.mark.parametrize("binding,lang,reason", [
    ("budget", "en", "because your monthly budget is the limit ({{n9}}); your balance would allow more ({{n8}})."),
    ("balance", "en", "because your balance is the limit ({{n8}}); your monthly budget would allow more ({{n9}})."),
    ("budget", "fi", "koska kuukausibudjettisi on raja ({{n9}}); saldosi sallisi enemmän ({{n8}})."),
])
def test_safe_to_spend_is_one_sentence_with_the_binding_limit(binding, lang, reason):
    # After #246: the amount and which limit binds, the same three numbers as before.
    view = {**SAFE, "binding_limit": binding, "balance_limit": n(8, 5864.86 if binding == "budget" else 120.0),
            "budget_limit": n(9, 180.26)}
    draft = template_draft([view], [], lang, None, "What can I safely spend this week?")
    assert sorted(draft["cited"]) == ["n6", "n8", "n9"]
    assert draft["text"].startswith(("Safe to spend in the coming week: {{n6}}", "Turvallisesti")) and reason in draft["text"]
    assert not any(c.isdigit() for c in draft["text"].replace("{{n6}}", "").replace("{{n8}}", "").replace("{{n9}}", ""))
