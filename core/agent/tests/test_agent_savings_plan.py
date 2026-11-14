"""The savings plan in the answer pipeline (#369): the save-more question plans it, and its takeaway passes the
real validator in two sentences and at most three numbers, in English and Finnish."""

from __future__ import annotations

import re
from datetime import date

import pytest

from core.agent import template
from core.agent.model import PlanInput
from core.agent.rules import RuleModel
from core.agent.validator import allowed_from, validate
from core.tools import savings_plan as sp
from core.tools.context import ToolContext
from core.tools.tests.test_tools_savings_plan_pure import SANNA, fake, what_if  # noqa: F401 (fixture)

AS_OF = date(2026, 9, 30)
BASE = ["get_spending", "get_basket_breakdown", "get_recurring_bills", "get_safe_to_spend", "get_safe_to_save",
        "run_what_if", "get_spender_profile", "get_peer_benchmark", "get_bonus_estimate"]


def plan(question, tools, language="en"):
    request = PlanInput(question=question, language=language, as_of=AS_OF.isoformat(),
                        tools=[{"name": t, "description": "", "parameters_json_schema": {}} for t in tools])
    return RuleModel().plan(request)


@pytest.mark.parametrize("question,lang", [("How could I save more?", "en"), ("Miten voisin säästää enemmän?", "fi"),
                                           ("Miten voisin saastaa enemman?", "fi")])
def test_the_save_more_question_plans_the_savings_plan(question, lang):
    result = plan(question, BASE + ["get_savings_plan"], lang)
    assert result.recognised and [c.name for c in result.calls] == ["get_savings_plan", "finish"]


def test_without_the_plan_tool_the_earlier_answer():
    assert [c.name for c in plan("How could I save more?", BASE).calls] == [
        "get_safe_to_save", "get_basket_breakdown", "finish"]


def rendered(language="en"):
    ctx = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=None, language=language)
    result = sp.get_savings_plan(ctx, {})
    view = result.model_view
    numbers = ctx.numbers.all()
    draft = template.template_draft([view], [], language, None, "How could I save more?")
    _, errors = validate(draft, language=language, numbers=numbers, allowed=allowed_from(numbers.values(), [view], AS_OF))
    assert errors == [], (draft["text"], errors)
    text = re.sub(r"\{\{(n\d+)\}\}", lambda m: numbers[m.group(1)].display, draft["text"])
    return text, draft["cited"]


def test_the_plan_in_english(fake):  # noqa: F811
    text, cited = rendered()
    assert text == ("You could already set aside about €184.61 a month; these changes could add about €63.17 a month. "
                    "That is about €758.04 a year, from eating out a fifth less and spending a tenth less on lifestyle.")
    assert len(cited) == 3


def test_the_plan_in_finnish(fake, monkeypatch):  # noqa: F811
    from core.tools.tests.test_tools_savings_plan_pure import num
    from types import SimpleNamespace

    fi_save = num("184.61", "ev_save", "safe_to_spend.safe_to_save_monthly_eur@1")
    fi_save = fi_save.model_copy(update={"display": "184,61 € / kk"})   # the fixture's numbers are English
    monkeypatch.setattr(sp, "get_safe_to_save", lambda ctx, args: SimpleNamespace(data=SimpleNamespace(monthly=fi_save)))
    text, cited = rendered("fi")
    assert text == ("Voisit jo nyt säästää noin 184,61 € / kk; nämä muutokset voisivat lisätä noin 63,17 € / kk. "
                    "Se tekee noin 758,04 € / v: ulkona syöminen viidenneksen vähemmän ja luokassa Ostokset ja "
                    "vapaa-aika kymmenyksen vähemmän.")
    assert len(cited) == 3


def test_one_lever_only(fake):  # noqa: F811
    for c in ("Entertainment", "Lifestyle", "Travel"):
        fake.what_ifs[c] = what_if("20.00", "2.00", ref=f"ev_{c[:3]}")
    text, _ = rendered()
    assert text.endswith("That is about €550.92 a year, from eating out a fifth less.")


def test_no_lever_says_so_plainly_and_keeps_safe_to_save(fake):  # noqa: F811
    fake.what_ifs = {c: what_if("20.00", "2.00", ref=f"ev_{c[:3]}") for c in SANNA}
    text, cited = rendered()
    assert text == "None of the usual cuts would add much here; you could already set aside about €184.61 a month."
    assert len(cited) == 1


@pytest.mark.parametrize("language", ["en", "fi"])
def test_the_text_never_quotes_safe_to_spend_or_repeats_a_unit(fake, language):  # noqa: F811
    text, _ = rendered(language)
    assert "spend" not in text.replace("spending", "") and "turvallisesti käytettävissä" not in text
    assert "a month a month" not in text and "/ kk kuukaudessa" not in text and "a year a year" not in text
    assert text.count(". ") + 1 == 2 or text.count(". ") == 1     # two sentences
