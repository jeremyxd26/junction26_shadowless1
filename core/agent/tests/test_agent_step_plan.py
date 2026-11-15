"""Steps or a plan to save (#822): an explicit request gets three numbered steps from the tools the save-more
route already runs (the savings goal, the plan's largest what-if cut, the small purchases a month), one number
each, in English and Finnish; a step whose tool gave no figure is left out. Plain "help me save" questions, the
demo's "How could I save more?" and real spending questions keep their routes. No model, no database."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pytest
from agent_fakes import audit_records, registry, run
from test_agent_safe_to_spend_why_warning import RulesPlanning

from core import answer_text
from core.agent import template
from core.agent.model import PlanInput
from core.agent.registry import ToolSpec
from core.agent.rules import RuleModel, claim
from core.agent.validator import allowed_from, validate
from core.tools import savings_plan as sp
from core.tools.context import ToolContext
from core.tools.formatting import display
from core.tools.models import Args, Number, Period, ToolResult, Unit
from core.tools.numbers import model_number
from core.tools.tests.test_tools_savings_plan_pure import SANNA, fake, num  # noqa: F401 (fixture)

AS_OF = date(2026, 9, 30)
TOOLS = ["get_spending", "get_basket_breakdown", "get_recurring_bills", "get_safe_to_spend", "get_safe_to_save",
         "run_what_if", "get_spender_profile", "get_peer_benchmark", "get_bonus_estimate", "get_savings_plan",
         "get_small_purchases"]


def request(question, language="en", tools=TOOLS):
    return PlanInput(question=question, language=language, as_of=AS_OF.isoformat(),
                     tools=[{"name": t, "description": "", "parameters_json_schema": {}} for t in tools])


STEP_QUESTIONS = [
    ("What should I do step by step to save money?", "en"),
    ("Can you give me a plan to save money?", "en"),
    ("What should I do to save?", "en"),
    ("What are the steps to save more?", "en"),
    ("Voitko selkeästi selittää… mitä mun pitää tehdä askeleilla… säästää rahaa?", "fi"),
    ("Voitko selkeästi selittää, mitä mun pitää tehdä askeleilla, jotta voin säästää rahaa?", "fi"),
    ("Miten voisin säästää askel askeleelta?", "fi"),
    ("Mitä mun pitää tehdä, että säästän enemmän?", "fi"),
    ("Tee minulle suunnitelma säästämiseen", "fi"),
]


@pytest.mark.parametrize("question,lang", STEP_QUESTIONS)
def test_a_step_request_plans_the_steps_and_the_template_writes(question, lang):
    found = claim(request(question, lang))
    assert found.rule == "step_plan", (question, found)
    assert [c.name for c in found.calls] == ["get_savings_plan", "get_small_purchases", "finish"]
    result = RuleModel().plan(request(question, lang))
    assert result.recognised and result.template_answer


@pytest.mark.parametrize("question,lang,rule", [
    ("How could I save more?", "en", "save_more"),          # the demo question
    ("Miten voisin säästää enemmän?", "fi", "save_more"),
    ("help me save", "en", "save_more"),
    ("How can I save money?", "en", "save_more"),
    ("What can I do to save more?", "en", "save_more"),   # no step or plan asked

    ("What if I cut restaurants by 20%?", "en", "what_if"),
    ("How much did I spend on restaurants last month?", "en", "spending"),
    ("What does my phone plan cost me?", "en", "recurring_bills"),
])
def test_plain_save_and_spending_questions_keep_their_routes(question, lang, rule):
    assert claim(request(question, lang)).rule == rule, question


def test_voitko_auttaa_mua_keeps_todays_route():
    found = claim(request("voitko auttaa mua säästää rahaa?", "fi"))
    assert found.rule is None and found.reason == "other_person", found


@pytest.mark.parametrize("question,lang", [
    ("What should I do step by step to save on restaurants?", "en"),   # a named category: the what-if route
    ("Give me a plan to save 20% on takeaway", "en"),
    ("Give me a step by step plan to invest my savings", "en"),        # never product advice
    ("Should I take a loan? Give me a plan to save for it", "en"),     # never borrowing
    ("Tee suunnitelma, miten sijoitan säästöni", "fi"),
    ("How many steps did I save last month?", "en"),                   # the past is no plan
    ("What is my payment plan?", "en"),                                # no save word
    ("Mikä on maksusuunnitelmani?", "fi"),
])
def test_no_steps_beyond_the_request(question, lang):
    assert claim(request(question, lang)).rule != "step_plan", question


def test_without_the_plan_tool_no_steps():
    tools = [t for t in TOOLS if t != "get_savings_plan"]
    assert claim(request("What should I do step by step to save money?", "en", tools)).rule != "step_plan"


def views(language="en", small_kind="summary", per_month="9.58"):
    ctx = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=None, language=language)
    plan = sp.get_savings_plan(ctx, {}).model_view
    month = ctx.numbers.register(num(per_month, "ev_small", "small_purchases.month_avg_eur@1", Unit.EUR_PER_MONTH))
    small = {"tool": "get_small_purchases", "period_preset": "last_3_months", "per_month": model_number(month),
             "takeaway": {"kind": small_kind}}
    return ctx, [plan, small]


def rendered(ctx, vs, language, question):
    numbers = ctx.numbers.all()
    draft = template.template_draft(vs, [], language, None, question)
    _, errors = validate(draft, language=language, numbers=numbers, allowed=allowed_from(numbers.values(), vs, AS_OF))
    assert errors == [], (draft["text"], errors)
    text = re.sub(r"\{\{(n\d+)\}\}", lambda m: numbers[m.group(1)].display, draft["text"])
    return text, draft


def test_the_steps_in_english(fake):  # noqa: F811
    ctx, vs = views()
    text, draft = rendered(ctx, vs, "en", "What should I do step by step to save money?")
    assert text == ("First, set aside your savings goal: €360.00 a month. Second, eat out a fifth less, which could "
                    "save about €45.91 a month. Third, check your small purchases: they add up to about €9.58 a month.")
    assert len(draft["cited"]) == 3
    # the list's own template budget: one sentence per step, within the ordinary answer's words and numbers
    assert answer_text.length_problems(draft["text"], len(draft["cited"]), kind="ordinary") == []
    assert answer_text.borrowing_suggestion(text) is None and answer_text.amount_beside_bank_product(text) is None


def test_the_steps_in_finnish(fake):  # noqa: F811
    ctx, vs = views("fi")
    text, draft = rendered(ctx, vs, "fi", "Voitko selkeästi selittää… mitä mun pitää tehdä askeleilla… säästää rahaa?")
    # the fixture's numbers display in English; the words are Finnish
    assert text.startswith("Ensiksi laita säästötavoitteesi sivuun: ")
    assert " Toiseksi syö ulkona viidenneksen vähemmän, jolloin säästäisit noin " in text
    assert " Kolmanneksi tarkista pienet ostoksesi: niitä kertyy noin " in text
    assert len(draft["cited"]) == 3
    assert answer_text.length_problems(draft["text"], len(draft["cited"]), kind="ordinary") == []


def test_a_step_without_a_figure_is_left_out(fake):  # noqa: F811
    ctx, vs = views(small_kind="none")
    text, draft = rendered(ctx, vs, "en", "What should I do step by step to save money?")
    assert text == ("First, set aside your savings goal: €360.00 a month. Second, eat out a fifth less, which could "
                    "save about €45.91 a month.")
    assert len(draft["cited"]) == 2


def test_one_step_only_is_the_per_tool_answer(fake):  # noqa: F811
    ctx, vs = views(small_kind="none")
    plan = {**vs[0], "kind": "none", "levers": []}
    text, _ = rendered(ctx, [plan, vs[1]], "en", "What should I do step by step to save money?")
    assert not text.startswith("First,"), text


def test_the_save_more_answer_is_unchanged(fake):  # noqa: F811
    ctx, vs = views()
    text, _ = rendered(ctx, vs[:1], "en", "How could I save more?")
    assert text == ("These changes could add about €63.17 a month, about €758.04 a year: eating out a fifth less and "
                    "spending a tenth less on lifestyle. That is on top of the about €360.00 a month you set aside first.")


# ---- through the pipeline: the rule planner's template answer, also as a second turn -------------------------------

class SmallArgs(Args):
    pass


def fake_small_purchases(ctx, args: SmallArgs) -> ToolResult:
    """The small purchases a month over the last three complete months (no database)."""
    window = Period(start=date(2026, 7, 1), end=date(2026, 9, 30), label="1 Jul – 30 Sep 2026")
    month = ctx.numbers.register(Number(value=9.58, unit=Unit.EUR_PER_MONTH, period=window,
                                        method="small_purchases.month_avg_eur@1", evidence_ref="ev_small_month",
                                        label="Small purchases a month",
                                        display=display(Decimal("9.58"), Unit.EUR_PER_MONTH, ctx.language)))
    view = {"tool": "get_small_purchases", "period": window.label, "period_preset": "last_3_months",
            "per_month": model_number(month), "takeaway": {"kind": "summary"}, "notes": []}
    return ToolResult(tool="get_small_purchases", data={}, card=None, evidence=[month.evidence_ref], model_view=view)


SMALL = ToolSpec("get_small_purchases", "Small purchases.", SmallArgs, fake_small_purchases, ("Looking", "Katson"))


def step_pipeline(make_pipeline):
    from core.agent.toolset import default_registry

    model = RulesPlanning()   # the model is on; its composer must never be asked
    return model, make_pipeline(model, registry(default_registry().tools["get_savings_plan"], SMALL))


def check_steps(model, pipe, done):
    assert done["outcome"] == "answered" and model.composed == [] and "llm_unavailable" not in done["warnings"]
    record = audit_records(pipe)[-1]
    assert record["planner_turns"][-1]["designed"] == "rule_template"
    assert len(done["cited"]) == 3
    return record


def test_the_pipeline_writes_the_steps(make_pipeline, fake):  # noqa: F811
    model, pipe = step_pipeline(make_pipeline)
    done = dict(run(pipe, "What should I do step by step to save money?", language="en"))["done"]
    check_steps(model, pipe, done)
    assert done["text_rendered"] == ("First, set aside your savings goal: €360.00 a month. Second, eat out a fifth "
                                     "less, which could save about €45.91 a month. Third, check your small purchases: "
                                     "they add up to about €9.58 a month.")


def test_the_steps_as_a_second_turn_after_the_save_more_answer(make_pipeline, fake):  # noqa: F811
    model, pipe = step_pipeline(make_pipeline)
    first = run(pipe, "voitko auttaa mua säästää rahaa?", language="fi")
    conversation = dict(first)["meta"]["conversation_id"]
    events = run(pipe, "Voitko selkeästi selittää… mitä mun pitää tehdä askeleilla… säästää rahaa?", language="fi",
                 conversation_id=conversation)
    done = dict(events)["done"]
    check_steps(model, pipe, done)
    assert done["text"].startswith("Ensiksi laita säästötavoitteesi sivuun: ") and " Kolmanneksi " in done["text"]
