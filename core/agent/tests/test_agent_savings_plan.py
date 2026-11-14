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
    """The plan's total a month first (#411), then what can already be set aside."""
    text, cited = rendered()
    assert text == ("These changes could add about €63.17 a month, about €758.04 a year: eating out a fifth less and "
                    "spending a tenth less on lifestyle. That is on top of the about €360.00 a month you set aside first.")
    assert len(cited) == 3


def test_the_plan_in_finnish(fake, monkeypatch):  # noqa: F811
    from core.tools.tests.test_tools_savings_plan_pure import num
    from types import SimpleNamespace

    fi_save = num("360.00", "ev_goal", "safe_to_spend.savings_goal_eur@1")
    fi_save = fi_save.model_copy(update={"display": "360,00 € / kk"})   # the fixture's numbers are English
    monkeypatch.setattr(sp, "get_safe_to_spend", lambda ctx, args: SimpleNamespace(data=SimpleNamespace(savings_goal=fi_save)))
    text, cited = rendered("fi")
    assert text == ("Nämä muutokset voisivat lisätä noin 63,17 € / kk, noin 758,04 € / v: ulkona syöminen viidenneksen "
                    "vähemmän ja luokassa Ostokset ja vapaa-aika kymmenyksen vähemmän. Tämä on sen lisäksi, että "
                    "laitat ensin sivuun noin 360,00 € / kk.")
    assert len(cited) == 3


def test_one_lever_only(fake):  # noqa: F811
    for c in ("Entertainment", "Lifestyle", "Travel"):
        fake.what_ifs[c] = what_if("20.00", "2.00", ref=f"ev_{c[:3]}")
    text, _ = rendered()
    assert text == ("These changes could add about €45.91 a month, about €550.92 a year: eating out a fifth less. "
                    "That is on top of the about €360.00 a month you set aside first.")


@pytest.mark.parametrize("language,expected", [
    ("en", "These changes could add about €63.17 a month: eating out a fifth less and spending 15.0% less on "
           "lifestyle. That is on top of the about €360.00 a month you set aside first."),
    ("fi", "Nämä muutokset voisivat lisätä noin 63,17 € / kk: ulkona syöminen viidenneksen vähemmän ja luokassa "
           "Ostokset ja vapaa-aika 15,0 % vähemmän. Tämä on sen lisäksi, että laitat ensin sivuun noin 360,00 € / kk."),
])
def test_a_cut_share_without_words_is_cited_as_a_number(fake, monkeypatch, language, expected):  # noqa: F811
    """Review of #411: another cut share (15 %) is cited as its Number; the answer is still two sentences and
    three numbers (the year gives way), and the S-Bonus is never in the text."""
    from core.tools import config
    from core.tools.tests.test_tools_savings_plan_pure import num
    from types import SimpleNamespace

    monkeypatch.setattr(config, "SAVINGS_PLAN_OTHER_CUT_PCT", 15)
    if language == "fi":
        fi_save = num("360.00", "ev_goal", "safe_to_spend.savings_goal_eur@1")
        fi_save = fi_save.model_copy(update={"display": "360,00 € / kk"})
        monkeypatch.setattr(sp, "get_safe_to_spend", lambda ctx, args: SimpleNamespace(data=SimpleNamespace(savings_goal=fi_save)))
    text, cited = rendered(language)
    assert text == expected and len(cited) == 3
    assert "25.15" not in text and "25,15" not in text and "S-Bonus" not in text


def test_two_equal_shares_without_words_are_one_number_said_once(fake, monkeypatch):  # noqa: F811
    """Review of #411: 15 and 15 are one Number, cited once, so safe to save is not dropped needlessly."""
    from core.tools import config

    monkeypatch.setattr(config, "SAVINGS_PLAN_FIRST", ("Restaurants", 15))
    monkeypatch.setattr(config, "SAVINGS_PLAN_OTHER_CUT_PCT", 15)
    text, cited = rendered()
    assert text == ("These changes could add about €63.17 a month: eating out and spending on lifestyle, each 15.0% "
                    "less. That is on top of the about €360.00 a month you set aside first.")
    assert len(cited) == len(set(cited)) == 3


def test_two_different_shares_without_words_cite_three_numbers(fake, monkeypatch):  # noqa: F811
    from core.tools import config

    monkeypatch.setattr(config, "SAVINGS_PLAN_FIRST", ("Restaurants", 15))
    monkeypatch.setattr(config, "SAVINGS_PLAN_OTHER_CUT_PCT", 30)
    text, cited = rendered()
    assert text == "These changes could add about €63.17 a month: eating out 15.0% less and spending 30.0% less on lifestyle."
    assert len(cited) == 3


@pytest.mark.parametrize("language", ["en", "fi"])
def test_the_s_bonus_question_comes_first_and_the_bonus_rule_claims_it(fake, language):  # noqa: F811
    """Decision of #411: the S-Bonus is offered as the answer's first follow-up, and the bonus rule answers that
    exact prompt with get_bonus_estimate (its own Number and evidence)."""
    ctx = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=None, language=language)
    view = sp.get_savings_plan(ctx, {}).model_view
    question = "How could I save more?" if language == "en" else "Miten voisin säästää enemmän?"
    chips = template.follow_ups(question, language, views=[view])
    assert chips[0] == view["follow_up"] and len(chips) == 3 and len(set(chips)) == 3
    result = plan(view["follow_up"], BASE + ["get_savings_plan"], language)
    assert result.recognised and [c.name for c in result.calls] == ["get_bonus_estimate", "finish"]


@pytest.mark.parametrize("message,language,offer,chip", [
    ("How could I save more?", "en", "How does my spending compare with people like me?", "How much S-Bonus could I get?"),
    ("Miten voisin säästää enemmän?", "fi", "Miten kulutukseni vertautuu kaltaisiini?",
     "Paljonko S-Bonusta voisin saada?")])
def test_an_answer_to_save_more_offers_the_peer_comparison_then_the_s_bonus_question(
        fake, tmp_path, monkeypatch, message, language, offer, chip):  # noqa: F811
    """End to end (rule planner, no database): done.follow_ups starts with the plan's next step, the peer
    comparison (#572, the coordinator: the offer's chip first), then the S-Bonus question (#411); the answer and
    the card carry no S-Bonus amount."""
    from agent_fakes import FakeData
    from fastapi.testclient import TestClient

    from core.agent.api import Agent, AskLimits
    from core.agent.audit import AuditLog
    from core.agent.orchestrator import Pipeline
    from core.agent.registry import Registry, ToolSpec
    from core.app.main import create_app
    from core.app.settings import Settings

    for name in ("DATABASE_URL", "AUDIT_API", "ASK_RATE_LIMIT_PER_MIN", "TRUSTED_PROXIES"):
        monkeypatch.delenv(name, raising=False)
    app = create_app(Settings(_env_file=None))
    with TestClient(app) as c:
        audit, data, reg = AuditLog(tmp_path / "audit"), FakeData(), Registry()
        reg.register(ToolSpec("get_savings_plan", "The savings plan.", sp.GetSavingsPlanArgs, sp.get_savings_plan,
                              ("Planning", "Suunnittelen")))
        app.state.agent = Agent(pipeline=Pipeline(reg, RuleModel(), data, as_of=AS_OF, audit=audit), data=data,
                                audit=audit, limits=AskLimits(0, 0, 0))
        r = c.post("/api/ask", json={"customer_id": "CUST00860", "conversation_id": None, "message": message,
                                     "language": language}, headers={"Accept": "application/json"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "answered" and body["follow_ups"][:2] == [offer, chip], body
    assert "25.15" not in r.text and "25,15" not in r.text


def test_without_a_tool_question_the_follow_ups_are_the_brief_questions():
    assert template.follow_ups("How could I save more?", "en", views=[{"tool": "get_spending"}]) == \
        template.follow_ups("How could I save more?", "en")


def test_a_goal_of_zero_leaves_the_second_sentence_out(fake, monkeypatch):  # noqa: F811
    from types import SimpleNamespace

    from core.tools.tests.test_tools_savings_plan_pure import num

    monkeypatch.setattr(sp, "get_safe_to_spend", lambda ctx, args: SimpleNamespace(data=SimpleNamespace(
        savings_goal=num("0.00", "ev_goal0", "safe_to_spend.savings_goal_eur@1"))))
    text, cited = rendered()
    assert text == ("These changes could add about €63.17 a month, about €758.04 a year: eating out a fifth less and "
                    "spending a tenth less on lifestyle.")
    assert len(cited) == 2


def test_no_lever_says_so_plainly_and_keeps_the_goal(fake):  # noqa: F811
    fake.what_ifs = {c: what_if("20.00", "2.00", ref=f"ev_{c[:3]}") for c in SANNA}
    text, cited = rendered()
    assert text == "None of the usual cuts would add much here; you already set aside about €360.00 a month first."
    assert len(cited) == 1


@pytest.mark.parametrize("language", ["en", "fi"])
def test_the_text_never_quotes_safe_to_spend_or_repeats_a_unit(fake, language):  # noqa: F811
    text, _ = rendered(language)
    assert "spend" not in text.replace("spending", "") and "turvallisesti käytettävissä" not in text
    assert "a month a month" not in text and "/ kk kuukaudessa" not in text and "a year a year" not in text
    assert text.count(". ") + 1 == 2 or text.count(". ") == 1     # two sentences
