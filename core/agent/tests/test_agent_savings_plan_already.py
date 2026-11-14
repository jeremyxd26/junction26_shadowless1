"""#560: the savings-plan answer opens with what already goes to savings, or says plainly that no regular transfer
shows in this account; either takes the goal sentence's place, within the length rule. The card is unchanged. No
database: the plan's composed tools are faked as in the tool tests."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal

import pytest

from core import answer_text
from core.agent import template
from core.agent.validator import allowed_from, validate
from core.tools import savings_plan as sp
from core.tools.context import ToolContext
from core.tools.formatting import display
from core.tools.tests.test_tools_savings_plan_pure import SANNA, fake, num, what_if  # noqa: F401 - shared fixture

AS_OF = date(2026, 9, 30)
SAVING = num("242.95", "ev_invest", "recurring.typical_month_eur@1")
SALARY = num("3171.65", "ev_salary", "recurring.typical_month_eur@1")


def answer(monkeypatch, flows, language="en"):
    """The template answer for the plan, validated as the orchestrator does, rendered; and the tool result."""
    if flows is None:
        monkeypatch.setattr(sp, "already_saving", lambda ctx: (_ for _ in ()).throw(RuntimeError("down")))
    else:   # the bills tool formats its Numbers in the answer's language
        localised = tuple([n.model_copy(update={"display": display(Decimal(str(n.value)), n.unit, language, n.method)})
                           for n in group] for group in flows)
        monkeypatch.setattr(sp, "already_saving", lambda ctx: localised)
    ctx = ToolContext(customer_id="CUST00349", as_of=AS_OF, conn=None, language=language)
    result = sp.get_savings_plan(ctx, {})
    view, numbers = result.model_view, ctx.numbers.all()
    draft = template.template_draft([view], [], language, None, "How could I save more?")
    _, errors = validate(draft, language=language, numbers=numbers, allowed=allowed_from(numbers.values(), [view], AS_OF))
    assert errors == [], (draft["text"], errors)
    text = re.sub(r"\{\{(n\d+)\}\}", lambda m: numbers[m.group(1)].display, draft["text"])
    assert answer_text.length_problems(draft["text"], len(draft["cited"])) == [], text
    return text, [numbers[i] for i in draft["cited"]], result


FLOW = ([SAVING], [SALARY])
NONE_SEEN = ([], [SALARY])


@pytest.mark.parametrize("language, expected", [
    ("en", "A regular transfer of about €242.95 a month already goes to savings (7.7% of your income). These changes "
           "could add about €63.17 a month: eating out a fifth less and spending a tenth less on lifestyle."),
    ("fi", "Säästöihin menee jo säännöllisesti noin 242,95 € / kk, mikä on 7,7 % tuloistasi. Nämä muutokset voisivat "
           "lisätä noin 63,17 € / kk: ulkona syöminen viidenneksen vähemmän ja luokassa Ostokset ja vapaa-aika "
           "kymmenyksen vähemmän."),
])
def test_with_a_regular_transfer_the_answer_opens_with_it(fake, monkeypatch, language, expected):  # noqa: F811
    text, cited, _ = answer(monkeypatch, FLOW, language)
    assert text == expected
    assert [n.method for n in cited] == ["recurring.typical_month_eur@1", "savings_plan.already_share_pct@1",
                                         "savings_plan.total_month_eur@1"]   # no year, no goal in the text
    assert cited[0].evidence_ref == "ev_invest"


@pytest.mark.parametrize("language, expected", [
    ("en", "These changes could add about €63.17 a month, about €758.04 a year: eating out a fifth less and spending "
           "a tenth less on lifestyle. In this account I don't see a regular transfer to savings yet."),
    ("fi", "Nämä muutokset voisivat lisätä noin 63,17 € / kk, noin 758,04 € / v: ulkona syöminen viidenneksen "
           "vähemmän ja luokassa Ostokset ja vapaa-aika kymmenyksen vähemmän. Tällä tilillä en vielä näe "
           "säännöllistä siirtoa säästöön."),
])
def test_without_one_the_neutral_line_takes_the_goal_sentences_place(fake, monkeypatch, language, expected):  # noqa: F811
    text, cited, _ = answer(monkeypatch, NONE_SEEN, language)
    assert text == expected
    assert [n.method for n in cited] == ["savings_plan.total_month_eur@1", "savings_plan.total_year_eur@1"]
    neutral = text.split(". ")[-1]
    assert not re.search(r"\d", neutral)                     # no amount in the neutral line (the bank-screen rule)


@pytest.mark.parametrize("flows, language, expected", [
    (FLOW, "en", "None of the usual cuts would add much here. A regular transfer of about €242.95 a month already "
                 "goes to savings (7.7% of your income)."),
    (FLOW, "fi", "Tavalliset vähennykset eivät lisäisi tässä paljon. Säästöihin menee jo säännöllisesti noin "
                 "242,95 € / kk, mikä on 7,7 % tuloistasi."),
    (NONE_SEEN, "en", "None of the usual cuts would add much here. In this account I don't see a regular transfer "
                      "to savings yet."),
    (NONE_SEEN, "fi", "Tavalliset vähennykset eivät lisäisi tässä paljon. Tällä tilillä en vielä näe säännöllistä "
                      "siirtoa säästöön."),
])
def test_with_no_lever_it_takes_the_goal_half(fake, monkeypatch, flows, language, expected):  # noqa: F811
    fake.what_ifs = {c: what_if("20.00", "2.00", ref=f"ev_{c[:3]}") for c in SANNA}
    text, cited, _ = answer(monkeypatch, flows, language)
    assert text == expected
    assert all(n.method != "safe_to_spend.savings_goal_eur@1" for n in cited)


def test_when_it_cannot_be_read_the_answer_is_as_before(fake, monkeypatch):  # noqa: F811
    text, cited, _ = answer(monkeypatch, None)
    assert text == ("These changes could add about €63.17 a month, about €758.04 a year: eating out a fifth less and "
                    "spending a tenth less on lifestyle. That is on top of the about €360.00 a month you set aside first.")


def test_the_card_is_the_same_in_every_state(fake, monkeypatch):  # noqa: F811
    cards = [json.dumps(answer(monkeypatch, flows)[2].card.model_dump(mode="json"), sort_keys=True)
             for flows in (FLOW, NONE_SEEN, None)]
    assert cards[0] == cards[1] == cards[2]
    card = json.loads(cards[0])
    assert [a["type"] for a in card["actions"]] == ["open_evidence", "open_host_screen"]   # the existing action only


def test_the_total_and_the_goal_are_the_same_numbers_in_every_state(fake, monkeypatch):  # noqa: F811
    results = [answer(monkeypatch, flows)[2].data for flows in (FLOW, NONE_SEEN, None)]
    assert {(d.total_month.value, d.total_year.value, d.savings_goal.value) for d in results} == {(63.17, 758.04, 360.0)}
