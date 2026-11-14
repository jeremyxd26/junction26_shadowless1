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
    assert draft["cited"] == ["n9", "n11", "n21", "n31"]
    assert draft["text"].startswith("1 Apr – 30 Sep 2026, monthly average: Total spending: {{n9}}; Regular essentials: {{n11}}")


def test_a_label_with_a_digit_that_is_not_a_date_is_left_out():
    view = {**SAFE, "period": "Next 7 days"}
    draft = template_draft([view], [], "en", None, "What can I safely spend this week?")
    assert "7" not in draft["text"] and draft["cited"] == ["n6", "n8", "n9"]
    kept = template_draft([{**SPENDING}], [], "en", None, "How much on taxis last month?")
    assert kept["text"].startswith("August 2026: ")


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


def test_save_more_cites_four_numbers_and_offers_a_cut_without_an_amount():
    # Review of PR #126: the three basket shares and the bills due; the offer names the largest everyday
    # category and asks by how much, never suggesting an amount.
    for question, lang, offer in [
            ("How could I save more?", "en", "Want to see what cutting restaurants would do? Tell me by how much."),
            ("Miten voisin säästää enemmän?", "fi",
             "Haluatko nähdä, mitä vähentäminen luokassa Restaurants tekisi? Kerro, kuinka paljon.")]:
        draft = template_draft([EVERYDAY, BILLS], [], lang, None, question)
        assert draft["cited"] == ["n41", "n42", "n43", "n5"]
        assert draft["text"].endswith(offer)
        assert not any(w in draft["text"] for w in ("half", "puoleen", "%"))


def test_the_offer_only_follows_the_save_more_plan():
    after_what_if = template_draft([WHAT_IF], [], "en", None, "How could I save more by cutting restaurants 20%?")
    assert "Want to see" not in after_what_if["text"]
    assert "Want to see" not in template_draft([BILLS], [], "en", None, "Which bills are coming up next?")["text"]
    no_categories = template_draft([BASKETS, BILLS], [], "en", None, "How could I save more?")["text"]
    assert no_categories.endswith("Name a category and tell me by how much.")


@pytest.mark.parametrize("question", ["Which bills are due before payday?", "Which bills are coming up next?",
                                      "Mitkä laskut ovat tulossa seuraavaksi?",
                                      "Mitä laskuja on tulossa ennen palkkapäivää?"])
def test_a_bills_question_gets_the_bills_due_even_when_it_names_payday(question):
    assert ids(BILLS, question) == ["n5", "n2", "n4"]


@pytest.mark.parametrize("question", ["When is my next payday?", "Milloin on seuraava palkkapäivä?",
                                      "Paljonko tuloni ovat kuukaudessa?"])
def test_a_payday_question_without_bills_gets_the_income(question):
    assert ids(BILLS, question) == ["n6"]
