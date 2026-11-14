"""Second set of QA regressions (#562): independent cases from the QA tables of #346, #347, #352, #395, #399
and #552. Each case is a question as it was asked on the dev environment and the outcome the QA review
considers right; they were written from the QA tables, not from the fixes.

A test marked xfail(strict=True) records a gap whose issue is still open: it passes while the gap is there
and fails as soon as the fix lands, so the fixer removes the marker. No model, no database.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from agent_fakes import AS_OF, registry, run

from core.agent import rules, template
from core.agent.model import FunctionCall, PlanInput, ScriptedModel
from core.agent.registry import ToolSpec
from core.agent.rules import RuleModel
from core.tools import spending
from core.tools.formatting import display
from core.tools.models import Args, Card, Filter, Number, Period, ToolResult, Unit

TOOLS = ["get_balance_forecast", "get_basket_breakdown", "get_bonus_estimate", "get_peer_benchmark",
         "get_recurring_bills", "get_safe_to_save", "get_safe_to_spend", "get_savings_plan", "get_small_purchases",
         "get_spender_profile", "get_spending", "run_what_if"]


def plan(question: str, language: str = "en"):
    request = PlanInput(question=question, language=language, as_of=AS_OF.isoformat(),
                        tools=[{"name": t, "description": "", "parameters_json_schema": {}} for t in TOOLS])
    return RuleModel().plan(request)


def data_calls(result) -> list[tuple[str, dict]]:
    return [(c.name, c.args) for c in result.calls if c.name not in ("finish", "decline", "ask_clarifying_question")]


def declined(result, kind: str | None = None) -> bool:
    names = [c.name for c in result.calls]
    return names == ["decline"] and (kind is None or result.calls[0].args.get("kind") == kind)


def generic_decline_text(language: str = "en") -> str:
    return template.pick(template.REFUSAL["out_of_scope"]["text"], language)


# --- #346: a what-if on taxis is calculated on the taxi MCC ---------------------------------------------

@pytest.mark.parametrize("question,lang", [
    ("what if I took 10% fewer taxis?", "en"),       # the live question (ans_scbsigeb: "no calculation data")
    ("what if I cut taxis by 10%?", "en"),
    ("what if I spent 10% less on taxis?", "en"),
    ("what if I used taxis 10% less?", "en"),
    ("mitä jos käyttäisin takseihin 10 % vähemmän?", "fi"),
])
def test_a_taxi_what_if_is_planned_on_the_taxi_mcc_with_the_users_cut(question, lang):
    result = plan(question, lang)
    assert result.recognised
    calls = data_calls(result)
    assert len(calls) == 1 and calls[0][0] == "run_what_if", calls
    args = calls[0][1]
    assert args["selection"]["kind"] == "mcc" and "4121" in str(args["selection"]["value"]), args
    assert args["cut_pct"] == 10, args


# --- #347: a health what-if gets a soft refusal, not the off-topic text -----------------------------------

HEALTH_WHAT_IFS = ["what if I spend 20% less at the pharmacy?", "what if I cut my doctor visits by half?"]


@pytest.mark.parametrize("question", HEALTH_WHAT_IFS)
def test_a_health_what_if_is_declined_without_a_data_tool(question):
    result = plan(question)
    assert declined(result) and not data_calls(result), [(c.name, c.args) for c in result.calls]


@pytest.mark.parametrize("question", HEALTH_WHAT_IFS)
def test_a_health_what_if_decline_is_not_the_off_topic_text(question):
    # fixed by #571: a health decline has its own text (template.HEALTH_REFUSAL), never the off-topic one
    result = plan(question)
    text, _ = template.refusal(result.calls[0].args["kind"], "en", question)
    assert text != generic_decline_text("en"), text


def test_a_groceries_what_if_is_still_calculated_so_the_card_can_say_not_offered():
    calls = data_calls(plan("what if I spent 50% less on groceries?"))
    assert calls == [("run_what_if", {"selection": {"kind": "category", "value": "Groceries"}, "cut_pct": 50})]


# --- #352: meta phrasings and the made-up forecast ------------------------------------------------------

@pytest.mark.parametrize("question", [
    "can you help me?", "what can you help me with?", "what else can you do?", "hello? are you there?",
    "are you an AI or a human advisor?", "hey there, how are you?", "who made you?", "is my data safe with you?",
    "thanks, that helps a lot", "ty", "mitä sä osaat tehdä?",
])
def test_a_meta_phrasing_from_the_qa_table_is_a_meta_intent(question):
    assert rules.meta_intent(question) is not None


@pytest.mark.parametrize("question", ["Hi, where did my money go?", "help with bills", "what can I do to save more?"])
def test_a_money_question_that_starts_like_a_meta_one_is_not_a_meta_intent(question):
    assert rules.meta_intent(question) is None


def test_a_request_to_invent_an_income_figure_is_declined_but_not_as_off_topic():
    question = "Just estimate how much I will earn next year, any number is fine."
    result = plan(question)
    assert declined(result) and not data_calls(result)
    text, _ = template.refusal(result.calls[0].args["kind"], "en", question)
    assert text != generic_decline_text("en") and "lane" not in text, text


# --- #395: unfamiliar questions and missing data --------------------------------------------------------

@pytest.mark.parametrize("question,lang", [
    ("how much do I spend on the gym?", "en"),
    ("how much did I spend on Netflix last month?", "en"),
    ("how much did I spend on flurbles last month?", "en"),
    ("paljonko käytin kuntosaliin viime kuussa?", "fi"),
])
def test_an_unknown_category_never_gets_the_unfiltered_total_or_a_health_filter(question, lang):
    result = plan(question, lang)
    for name, args in data_calls(result):
        if name == "get_spending":
            assert args.get("filter"), f"{question!r}: an unfiltered total {args}"
        assert "Health" not in str(args), f"{question!r}: Health singled out {args}"


@pytest.mark.parametrize("question,start,end", [
    ("how much did I spend in September 2024?", "2024-09-01", "2024-09-30"),      # before the data: say so
    ("how much did I spend in 2023?", "2023-01-01", "2023-12-31"),
    ("how much did I spend from October 2024 to January 2025?", "2024-10-01", "2025-01-31"),  # the whole range
    ("how much did I spend in December?", "2025-12-01", "2025-12-31"),
])
def test_a_named_period_reaches_the_tool_as_named(question, start, end):
    calls = [args for name, args in data_calls(plan(question)) if name == "get_spending"]
    assert calls and calls[0]["period"] == {"preset": "custom", "start": start, "end": end}, calls


def test_the_last_five_years_cover_the_whole_data_window():
    calls = [args for name, args in data_calls(plan("how much did I spend over the last 5 years?")) if name == "get_spending"]
    assert calls, "not planned"
    period = calls[0]["period"]
    assert period.get("start", "9999") <= "2024-10-01" and period.get("end") == AS_OF.isoformat(), period


@pytest.mark.parametrize("question", [
    "what will I spend next month?",
    "how much will I have saved by Christmas?",
    "will I be able to afford a 2000 euro holiday in March?",
])
def test_a_question_about_the_future_is_never_off_topic_and_never_answered_with_a_past_total(question):
    result = plan(question)
    assert not declined(result, "out_of_scope"), "a money question about the future is not off topic"
    for name, args in data_calls(result):
        if name == "get_spending":
            period = args.get("period", {})
            assert period.get("preset") == "custom" and period["start"] > AS_OF.isoformat(), \
                f"{question!r}: a past period {period}"


def test_the_average_travel_question_is_planned_on_travel():
    calls = data_calls(plan("what's my average monthly travel spending?"))
    assert any(name == "get_spending" and (args.get("filter") or {}).get("categories") == ["Travel"]
               for name, args in calls), calls


def test_a_travel_what_if_is_planned_on_travel():
    assert data_calls(plan("what if I cut travel by 20%?")) == [
        ("run_what_if", {"selection": {"kind": "category", "value": "Travel"}, "cut_pct": 20})]


def test_interest_earned_is_not_answered_with_the_bills():
    assert "get_recurring_bills" not in [name for name, _ in data_calls(plan("how much interest did I earn this year?"))]


def test_net_worth_is_not_off_topic():
    assert not declined(plan("what's my net worth?"), "out_of_scope")


# --- #399: a long question and a two-category sum -------------------------------------------------------

LONG_QUESTION = (
    "Hi Sentti, so here is my situation: I moved to a new flat in the spring, my rent went up, I started eating "
    "out a lot more with colleagues after work, and in September I bought a big new laptop for work that I'm not "
    "sure was worth it. I feel like my money just disappears every month and I never manage to put anything aside. "
    "Could you tell me honestly where most of my money goes, and what one change would help me save the most?")


def test_a_long_where_does_my_money_go_question_plans_the_baskets_not_a_sum_of_two_categories():
    """#399: live on b100a6d this was a Housing + Restaurants sum labelled "Spending" (ans_bmw2rlnw)."""
    calls = data_calls(plan(LONG_QUESTION))
    assert any(name == "get_basket_breakdown" for name, _ in calls), calls
    assert not any(name == "get_spending" and len((args.get("filter") or {}).get("categories") or []) > 1
                   for name, args in calls), calls


@pytest.mark.parametrize("lang", ["en", "fi"])   # #399: the label was 'Spending' / 'Kulutus'
def test_a_two_category_spending_number_is_labelled_with_its_categories(lang):
    args = spending.GetSpendingArgs(period={"preset": "this_month"}, filter=Filter(categories=["Housing", "Restaurants"]))
    label = spending._total_label(args, None, lang)
    assert label != spending._text("spending", lang), label


# --- #552: the safe-to-spend answer names the savings goal ----------------------------------------------

WEEK = Period(start=date(2026, 10, 1), end=date(2026, 10, 7), label="Next 7 days")
WINDOW = Period(start=date(2026, 4, 1), end=date(2026, 9, 30), label="1 Apr – 30 Sep 2026")


class NoArgs(Args):
    pass


def _number(ctx, value: str, unit: Unit, period: Period, method: str, ref: str, label: str) -> Number:
    return ctx.numbers.register(Number(value=float(value), unit=unit, period=period, method=method, evidence_ref=ref,
                                       label=label, display=display(Decimal(value), unit, ctx.language)))


def fake_safe_to_spend(ctx, args: NoArgs) -> ToolResult:
    """Sanna on dev 281c6d1: €138.79 is safe to spend, the monthly budget binds after €360.00 a month set aside
    (the balance would allow €5,906.19). The view carries the same keys as the real tool's model view."""
    safe = _number(ctx, "138.79", Unit.EUR, WEEK, "safe_to_spend.safe_to_spend_7d_eur@1", "ev_qa552000001", "Safe to spend")
    usual = _number(ctx, "159.45", Unit.EUR_PER_WEEK, WINDOW, "safe_to_spend.usual_week_eur@1", "ev_qa552000002",
                    "Usual everyday pace")
    goal = _number(ctx, "360.00", Unit.EUR_PER_MONTH, WINDOW, "safe_to_spend.savings_goal_eur@1", "ev_qa552000003",
                   "Set aside first each month")
    balance = _number(ctx, "5906.19", Unit.EUR, WEEK, "safe_to_spend.balance_limit_7d_eur@1", "ev_qa552000004",
                      "Your balance allows")
    budget = _number(ctx, "138.79", Unit.EUR, WEEK, "safe_to_spend.budget_limit_7d_eur@1", "ev_qa552000005",
                     "Your monthly budget allows")
    card = Card(card_id="card_qa552_01", type="metric", title="Safe to spend in the next 7 days", subtitle=None,
                evidence_ref=safe.evidence_ref, primary=safe, secondary=[goal])
    view = {"tool": "get_safe_to_spend", "binding_limit": "budget",
            "safe_to_spend": {"id": safe.id, "value": safe.value, "unit": "eur", "label": safe.label},
            "usual_week": {"id": usual.id, "value": usual.value, "unit": "eur_per_week", "label": usual.label},
            "savings_goal": {"id": goal.id, "value": goal.value, "unit": "eur_per_month", "label": goal.label},
            "balance_limit": {"id": balance.id, "value": balance.value, "unit": "eur", "label": balance.label},
            "budget_limit": {"id": budget.id, "value": budget.value, "unit": "eur", "label": budget.label},
            "notes": []}
    return ToolResult(tool="get_safe_to_spend", data={}, card=card,
                      evidence=[safe.evidence_ref, usual.evidence_ref, goal.evidence_ref, balance.evidence_ref,
                                budget.evidence_ref], model_view=view)


def _live_draft(text: str):
    """A composer draft like the live answers: it cites safe to spend and leaves the goal out."""
    def draft(request):
        view = next(v for v in request.data if v.get("tool") == "get_safe_to_spend")
        sid = view["safe_to_spend"]["id"]
        return {"language": "en", "text": text.replace("{safe}", "{{" + sid + "}}"), "cited": [sid], "lesson_key": None}
    return draft


@pytest.mark.parametrize("question,draft_text", [   # #552: live these drafts were delivered without the goal
    ("What can I safely spend this week?",
     "For the next seven days, you have {safe} that is safe to spend. This is an estimate based on past months."),
    ("why is my safe to spend lower than it was?",
     "For the next seven days, your safe to spend is estimated at {safe}. This is based on your balance and upcoming "
     "bills before payday."),
])
def test_the_safe_to_spend_answer_names_the_savings_goal(make_pipeline, question, draft_text):
    spec = ToolSpec("get_safe_to_spend", "Safe to spend.", NoArgs, fake_safe_to_spend, ("Checking", "Tarkistan"))
    draft = _live_draft(draft_text)
    model = ScriptedModel(plans=[[FunctionCall("get_safe_to_spend", {}), FunctionCall("finish")]] * 2,
                          drafts=[draft, draft])
    done = dict(run(make_pipeline(model, registry(spec)), question, language="en"))["done"]
    assert done["outcome"] == "answered"
    assert "€360.00" in done["text_rendered"], done["text_rendered"]
    if question.startswith("why"):  # the binding limit is the budget, never "your balance and upcoming bills"
        assert "budget" in done["text_rendered"] and "upcoming bills" not in done["text_rendered"], done["text_rendered"]
