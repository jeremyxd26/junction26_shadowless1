"""Pay yourself first in a model draft (#552): the checks that hold the composer to the safe-to-spend view. No
database.

On the stand every safe-to-spend answer dropped the savings goal set aside first, and "why is my safe to spend
lower?" blamed the balance and the bills while the monthly budget after the goal was the limit that binds. A draft
that answers with safe to spend now must cite the goal when the budget side binds and the goal is above zero, and
must name the binding limit as the cause: by the first limit word after a cause word, and by the Numbers it cites.
"""

from __future__ import annotations

import pytest

from core.agent.validator import draft_problems, safe_to_spend_problems


def view(binding="budget", goal=360.0, safe=138.79, balance_limit=5906.19, budget_limit=138.79):
    """A get_safe_to_spend model view with Sanna's numbers (dev 281c6d1): the ids as the tool gives them."""
    def n(i, value, label):
        return {"id": i, "value": value, "unit": "eur", "label": label}
    return {
        "tool": "get_safe_to_spend", "period": "Next 7 days", "status": "ok", "binding_limit": binding,
        "safe_to_spend": n("n6", safe, "Safe to spend"), "free_until_payday": n("n7", 6100.0, "Free until payday"),
        "balance_limit": n("n8", balance_limit, "Your balance allows"),
        "budget_limit": n("n9", budget_limit, "Your monthly budget allows"),
        "savings_goal": {"id": "n10", "value": goal, "unit": "eur_per_month", "label": "Set aside first each month"},
        "usual_week": {"id": "n11", "value": 159.45, "unit": "eur", "label": "Usual everyday pace"},
        "components": [{"key": "balance", "label": "Money on your account", "operation": "add",
                        "amount": n("n1", 7800.0, "Balance")},
                       {"key": "bills_due", "label": "Bills due before payday", "operation": "subtract",
                        "amount": n("n2", 928.50, "Bills before payday")}],
        "next_payday": "2026-10-15", "salary_status": "expected", "notes": [],
    }


SANNA = view()
BALANCE_BINDS = view(binding="balance", goal=360.0, safe=82.40, balance_limit=82.40, budget_limit=138.79)
NO_GOAL = view(goal=0.0)


def problems(text, v=SANNA):
    return safe_to_spend_problems(text, [v])


@pytest.mark.parametrize("draft", [   # the stand's answers, with the numbers as tokens
    "For the next seven days, you have {{n6}} that is safe to spend. This is an estimate based on past months.",
    "For the next seven days, your estimate is {{n6}} as safe to spend. This is an estimate based on past months.",
    "Seuraavien seitsemän päivän aikana sinulla on turvallisesti käytettävissä arviolta {{n6}}. Tämä arvio pitää "
    "puskurin turvassa ennen seuraavaa palkkapäivää.",
])
def test_a_safe_to_spend_answer_without_the_goal_is_rejected(draft):
    assert any("savings goal is set aside first" in p for p in problems(draft)), problems(draft)


def test_the_stands_why_answer_naming_the_balance_and_bills_is_rejected():
    draft = ("For the next seven days, your safe to spend is estimated at {{n6}}. This is based on your balance and "
             "upcoming bills before payday on 15 October 2026.")
    found = problems(draft)
    assert any("set by the budget limit, not the balance" in p for p in found), found
    assert any("savings goal is set aside first" in p for p in found), found


def test_the_stands_finnish_why_answer_citing_the_bills_is_rejected():
    draft = ("Seuraavien seitsemän päivän aikana turvallisesti käytettävissä on {{n6}}, ja ennen 15. lokakuuta 2026 "
             "erääntyvät laskut ovat {{n2}}.")
    found = problems(draft)
    assert any("set by the budget limit: cite it" in p for p in found), found


@pytest.mark.parametrize("draft", [   # written by the prompt lines of #570 (a) and (b)
    "About {{n6}} is safe to spend this week, after setting aside {{n10}} first.",
    "Voit käyttää tällä viikolla noin {{n6}}, kun ensin laitat sivuun {{n10}}.",
    "This week {{n6}} is safe to spend because your monthly budget sets the limit, after setting aside {{n10}} first.",
    "Tällä viikolla turvallisesti käytettävissä on {{n6}}, koska kuukausibudjettisi asettaa rajan, kun ensin laitat "
    "sivuun {{n10}}.",
    "{{n6}} is safe to spend this week because of your monthly budget after the savings goal of {{n10}} set aside "
    "first; your balance alone would allow {{n8}}.",
])
def test_a_draft_written_by_the_prompt_lines_passes(draft):
    assert problems(draft) == []


def test_when_the_balance_binds_the_balance_is_the_cause_and_the_goal_is_not_required():
    good = "This week {{n6}} is safe to spend because your balance sets the limit, after the bills before payday."
    assert problems(good, BALANCE_BINDS) == []
    bad = "This week {{n6}} is safe to spend because your monthly budget sets the limit."
    assert any("set by the balance limit, not the budget" in p for p in problems(bad, BALANCE_BINDS))
    only_other = "This week {{n6}} is safe to spend; your monthly budget would allow {{n9}}."
    assert any("set by the balance limit: cite it" in p for p in problems(only_other, BALANCE_BINDS))


def test_a_zero_goal_is_never_said_and_never_required():
    """The reviewer's state: goal 0 with the budget binding names the budget limit and no goal."""
    assert problems("This week {{n6}} is safe to spend because your monthly budget sets the limit.", NO_GOAL) == []
    found = problems("About {{n6}} is safe to spend this week, after setting aside {{n10}} first.", NO_GOAL)
    assert any("no savings goal is set aside" in p for p in found), found


def test_equal_limits_may_name_either_side():
    equal = view(binding="balance", goal=0.0, safe=100.0, balance_limit=100.0, budget_limit=100.0)
    assert problems("This week {{n6}} is safe to spend because your balance sets the limit.", equal) == []
    assert problems("This week {{n6}} is safe to spend because your monthly budget sets the limit.", equal) == []


def test_a_draft_that_does_not_answer_with_safe_to_spend_is_not_checked():
    assert problems("In August 2026 you spent {{n3}}.") == []
    assert safe_to_spend_problems("For the next seven days, you have {{n6}}.", []) == []


def test_draft_problems_runs_the_check_with_the_views():
    draft = "For the next seven days, you have {{n6}} that is safe to spend."
    assert any("savings goal" in p for p in draft_problems(draft, {}, has_data=True, views=[SANNA]))
    assert not any("savings goal" in p for p in draft_problems(draft, {}, has_data=True))
