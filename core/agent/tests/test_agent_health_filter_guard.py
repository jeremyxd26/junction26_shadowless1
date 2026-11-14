"""#598: "How much did I spend on the gym last month and what can I safely spend this week?" was answered on the stand
with a Health card and "Your health spending is declined before I write.": the model mapped the gym to Health, and
its draft echoed a composer line.

- A Health total the model plans (the Health category, the health MCC group or a health merchant's alias) never runs:
  it is dropped before anything runs. Beside another question, the other question is still answered and the template
  says the thing can't be seen on its own; alone, the call becomes the category breakdown of the same period, the
  rule path's answer for an unknown thing. The composer never writes such an answer.
- A model draft about its own rules or process is rejected and retried, then the template writes.
No database, no key."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from agent_fakes import AUG, FakeArgs, fake_spending, registry, run

from core.agent import template, validator
from core.agent.model import FunctionCall, ScriptedModel
from core.agent.registry import ToolSpec
from core.tools.formatting import display
from core.tools.models import Card, Number, Period, ToolResult, Unit

WEEK = Period(start=date(2026, 10, 1), end=date(2026, 10, 7), label="Next 7 days")
HEALTH_FILTER = {"categories": ["Health"]}
LEAK = "Your health spending is declined before I write."
ACCEPTANCE = "How much did I spend on the gym last month and what can I safely spend this week?"
SAFE_FI = "ja paljonko voin turvallisesti käyttää tällä viikolla?"


class PeriodArgs(FakeArgs):
    period: dict | None = None
    filter: dict | None = None


def _number(ctx, value, unit, period, method, label, ref):
    return ctx.numbers.register(Number(value=value, unit=unit, period=period, method=method,
                                       evidence_ref=f"ev_bbbbbbbbbbb{ref}", label=label,
                                       display=display(Decimal(str(value)), unit, ctx.language)))


def _specs(ran: list[tuple[str, dict]]):
    def spending(ctx, args):
        ran.append(("get_spending", dict(args.filter or {})))
        result = fake_spending(ctx, args)
        if (args.filter or {}).get("categories") == ["Health"]:
            total = _number(ctx, 185.3, Unit.EUR, AUG, "spending.total@1", "Health", 1)
            card = Card(card_id="card_health001", type="metric", title="Health", subtitle=AUG.label,
                        evidence_ref=total.evidence_ref, primary=total)
            view = {"tool": "get_spending", "period": AUG.label,
                    "total": {"id": total.id, "value": total.value, "unit": "eur", "label": "Health"},
                    "filter_labels": ["Health"], "notes": []}
            return ToolResult(tool="get_spending", data={}, card=card, evidence=[total.evidence_ref], model_view=view)
        return result

    def baskets(ctx, args):
        ran.append(("get_basket_breakdown", {}))
        card = Card(card_id="card_baskets001", type="breakdown", title="Where your money went",
                    subtitle="August 2026", evidence_ref="ev_aaaaaaaaaaa3")
        view = {"tool": "get_basket_breakdown", "period": "August 2026", "baskets": [
            {"key": "food", "label": "Food", "categories": [
                {"key": "Restaurants", "label": "Restaurants", "amount": {"value": 147.64}},
                {"key": "Groceries", "label": "Groceries", "amount": {"value": 320.1}}]},
            {"key": "health", "label": "Health", "categories": [
                {"key": "Health", "label": "Health", "amount": {"value": 999.0}}]}]}
        return ToolResult(tool="get_basket_breakdown", data={}, card=card, evidence=[], model_view=view)

    def safe(ctx, args):
        ran.append(("get_safe_to_spend", {}))
        s = _number(ctx, 212.4, Unit.EUR, WEEK, "safe_to_spend.safe_to_spend_7d_eur@1", "Safe to spend", 2)
        bal = _number(ctx, 950.0, Unit.EUR, WEEK, "safe_to_spend.balance_limit_eur@1", "Balance limit", 3)
        bud = _number(ctx, 212.4, Unit.EUR, WEEK, "safe_to_spend.budget_limit_eur@1", "Budget limit", 4)
        card = Card(card_id="card_safe0001", type="metric", title="Safe to spend", subtitle=WEEK.label,
                    evidence_ref=s.evidence_ref, primary=s)
        view = {"tool": "get_safe_to_spend", "binding_limit": "budget",
                **{k: {"id": n.id, "value": n.value, "unit": "eur", "label": n.label}
                   for k, n in (("safe_to_spend", s), ("balance_limit", bal), ("budget_limit", bud))}}
        return ToolResult(tool="get_safe_to_spend", data={}, card=card, evidence=[s.evidence_ref], model_view=view)

    return (ToolSpec("get_spending", "Spending.", PeriodArgs, spending, ("Looking", "Katson")),
            ToolSpec("get_basket_breakdown", "Baskets.", PeriodArgs, baskets, ("Looking", "Katson")),
            ToolSpec("get_safe_to_spend", "Safe to spend.", PeriodArgs, safe, ("Looking", "Katson")))


def _ask(make_pipeline, question, plan, drafts=(), language="en"):
    ran: list[tuple[str, dict]] = []
    model = ScriptedModel(plans=[plan], drafts=list(drafts))
    events = run(make_pipeline(model, registry(*_specs(ran))), question, language=language)
    cards = [p["card"] for e, p in events if e == "card"]
    return dict(events)["done"], ran, model, cards


def _with_safe(flt=None):
    return [FunctionCall("get_spending", {"period": {"preset": "last_month"}, "filter": flt or HEALTH_FILTER}),
            FunctionCall("get_safe_to_spend", {}), FunctionCall("finish")]


def _alone(flt=None):
    return [FunctionCall("get_spending", {"period": {"preset": "last_month"}, "filter": flt or HEALTH_FILTER}),
            FunctionCall("finish")]


def test_the_stand_question_answers_safe_to_spend_and_says_the_gym_is_not_seen_on_its_own(make_pipeline):
    done, ran, model, cards = _ask(make_pipeline, ACCEPTANCE, _with_safe(), drafts=[LEAK, LEAK])
    assert ran == [("get_safe_to_spend", {})]                      # the Health total never ran
    assert model.compose_inputs == []                               # the template wrote it, not the model
    assert [c["card_id"] for c in cards] == ["card_safe0001"]       # no Health card
    text = done["text"]
    assert done["outcome"] == "answered"
    assert text.startswith("I can't see “gym” on its own in your transactions")
    assert "Safe to spend in the coming week" in text
    assert validator.meta_text(text) is None and "declined" not in text and "health" not in text.lower()
    assert "llm_unavailable" not in done["warnings"]                # the template by design, not a failure


NEIGHBOURS = [
    ("How much did I spend on the gym last month", "en", "gym"),
    ("How much did I spend on yoga last month", "en", "yoga"),
    ("How much did I spend on massage last month", "en", "massage"),
    ("How much did I spend on vitamins from the supermarket last month", "en", "vitamins"),
    ("Paljonko käytin kuntosaliin viime kuussa", "fi", "kuntosaliin"),
    ("Paljonko käytin joogaan viime kuussa", "fi", "joogaan"),
    ("Paljonko käytin hierontaan viime kuussa", "fi", "hierontaan"),
    ("Paljonko käytin vitamiineihin marketista viime kuussa", "fi", None),
]


@pytest.mark.parametrize("question, language, word", NEIGHBOURS)
def test_no_neighbour_gets_a_health_card_beside_a_second_question(make_pipeline, question, language, word):
    two = f"{question} {SAFE_FI}" if language == "fi" else f"{question} and what can I safely spend this week?"
    done, ran, model, cards = _ask(make_pipeline, two, _with_safe(), drafts=[LEAK, LEAK], language=language)
    assert ran == [("get_safe_to_spend", {})] and model.compose_inputs == []
    assert [c["card_id"] for c in cards] == ["card_safe0001"]
    safe = "Safe to spend in the coming week" if language == "en" else "Turvallisesti käytettävissä"
    assert safe in done["text"] and validator.meta_text(done["text"]) is None
    assert "health" not in done["text"].lower() and "tervey" not in done["text"].lower()
    if word:
        assert done["text"].startswith(template.unknown_lead(word, language))


@pytest.mark.parametrize("question, language, word", NEIGHBOURS)
def test_no_neighbour_gets_a_health_card_alone(make_pipeline, question, language, word):
    done, ran, model, cards = _ask(make_pipeline, f"{question}?", _alone(), drafts=[LEAK, LEAK], language=language)
    assert ran == [("get_basket_breakdown", {})] and model.compose_inputs == []
    assert [c["card_id"] for c in cards] == ["card_baskets001"]
    assert "declined" not in done["text"] and validator.meta_text(done["text"]) is None
    if word:
        assert word in done["text"]


@pytest.mark.parametrize("flt", [{"mcc_groups": ["health"]}, {"merchant": "Health service A"},
                                 {"merchant": "Terveyspalvelu B"}])
def test_the_health_mcc_group_and_a_health_merchant_alias_are_dropped_too(make_pipeline, flt):
    done, ran, model, _ = _ask(make_pipeline, ACCEPTANCE, _with_safe(flt), drafts=[LEAK, LEAK])
    assert ran == [("get_safe_to_spend", {})] and "“gym”" in done["text"] and model.compose_inputs == []


@pytest.mark.parametrize("question, language", [
    ("How much did I spend at the pharmacy last month and what can I safely spend this week?", "en"),
    ("Paljonko käytin apteekkiin viime kuussa ja paljonko voin turvallisesti käyttää tällä viikolla?", "fi"),
])
def test_a_planned_health_total_never_runs_even_when_the_question_names_health(make_pipeline, question, language):
    # health stays declined as on dev: the model's Health total is dropped whatever the question says
    done, ran, model, cards = _ask(make_pipeline, question, _with_safe(), drafts=[LEAK, LEAK], language=language)
    assert ran == [("get_safe_to_spend", {})] and model.compose_inputs == []
    assert "card_health001" not in [c["card_id"] for c in cards]
    assert validator.meta_text(done["text"]) is None and "{{" not in done["text_rendered"]


@pytest.mark.parametrize("source", ["rules", "fallback"])
def test_only_the_models_plan_is_guarded(make_pipeline, source):
    from core.agent.orchestrator import _Answer
    pipeline, a = make_pipeline(ScriptedModel(), registry(*_specs([]))), _Answer(started=0.0)
    calls = _with_safe()
    assert pipeline._health_filter_guard(ACCEPTANCE, calls, source, a) is calls and a.health_dropped is None
    assert pipeline._health_filter_guard(ACCEPTANCE, calls, "model", a) is not calls and a.health_dropped == "gym"


# ---- the draft check for meta text ---------------------------------------------------------------------------

N1 = Number(id="n1", value=147.64, unit=Unit.EUR, period=AUG, method="spending.total@1",
            evidence_ref="ev_aaaaaaaaaaa1", label="Restaurants", display="€147.64")


@pytest.mark.parametrize("text", [
    LEAK,
    "Your Health spending is declined, so here is your safe to spend: {{n1}}.",
    "That question gets declined by my system. You spent {{n1}}.",
    "Rule: health is declined. You spent {{n1}}.",
    "I am not allowed to comment on that, but you spent {{n1}}.",
    "I'm not allowed to say more. You spent {{n1}}.",
    "My instructions say I can only give totals: {{n1}}.",
    "My rules do not let me say more. You spent {{n1}}.",
    "Per my guidelines, you spent {{n1}}.",
    "I was told not to comment. You spent {{n1}}.",
    "I have been instructed to give totals only: {{n1}}.",
    "I am not able to answer that because of how I was set up. You spent {{n1}}.",
    "Before I write the answer: you spent {{n1}}.",
    "Terveyskulusi hylätään ennen kuin kirjoitan. Käytit {{n1}}.",
    "En saa kommentoida sitä, mutta käytit {{n1}}.",
    "Ohjeeni kieltävät sen. Käytit {{n1}}.",
    "Minulla on ohjeet, jotka estävät vastaamasta. Käytit {{n1}}.",
])
def test_a_draft_about_its_own_rules_or_process_is_rejected(text):
    problems = validator.draft_problems(text, {"n1": N1}, has_data=True)
    assert any("your own rules, instructions or process" in p for p in problems), (text, problems)


@pytest.mark.parametrize("text", [
    "Your card payment was declined at Prisma on 3 August 2026.",
    "The payment was declined, so no money left your account.",
    "Maksu hylättiin Prismassa 3.8.2026.",
    "In August 2026 you spent {{n1}} on restaurants.",
])
def test_a_declined_payment_is_data_not_meta_text(text):
    assert validator.meta_text(text) is None


def test_a_leaked_draft_is_retried_then_the_template_writes(make_pipeline):
    plan = [FunctionCall("get_spending", {"period": {"preset": "last_month"}}), FunctionCall("finish")]
    leak = {"language": "en", "text": "Your spending is declined before I write: {{n1}}.", "cited": ["n1"],
            "lesson_key": None}
    done, ran, model, _ = _ask(make_pipeline, "How much did I spend last month?", plan, drafts=[leak, leak])
    assert len(model.compose_inputs) == 2                           # the call and one retry with the reason
    assert any("your own rules" in e for e in model.compose_inputs[1].validation_errors)
    assert "declined" not in done["text"] and done["outcome"] == "answered"


def _texts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _texts(v)
    elif isinstance(value, (tuple, list)):
        for v in value:
            yield from _texts(v)


def test_the_fixed_refusal_and_unknown_texts_are_not_meta_text():
    # refusals never pass through the draft check; this shows the check would not break them if they did
    fixed = [*_texts(template.REFUSAL), *_texts(template.UNKNOWN_PLAIN), *_texts(template.UNKNOWN_NO_WORD),
             *_texts(template.UNKNOWN), *_texts(template.NOTHING)]
    assert fixed and [t for t in fixed if validator.meta_text(t)] == []
    for lang in ("en", "fi"):
        assert validator.meta_text(template.unknown_lead("gym", lang)) is None
        assert template.unknown_lead("", lang) == template.pick(template.UNKNOWN_NO_WORD, lang)
        for word in ("x2", "a" * 41):
            assert template.unknown_lead(word, lang) == template.pick(template.UNKNOWN_NO_WORD, lang)
