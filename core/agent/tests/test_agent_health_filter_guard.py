"""#598: a Health filter the model planned stands only when the question names health. "How much did I spend on the
gym last month and what can I safely spend this week?" was answered on the stand with a Health card and "Your health
spending is declined before I write.": the model mapped the gym to Health, and its draft echoed a composer line.

- The model's Health-filtered get_spending for a question with no health word is dropped before anything runs; the
  other question is still answered, and the template says the thing can't be seen on its own. Alone, the call becomes
  the category breakdown of the same period: the rule path's answer for an unknown thing.
- An answer with a Health-filtered total is the template, never a model draft; so is the other tool's sentence.
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


def _health_and_safe():
    return [FunctionCall("get_spending", {"period": {"preset": "last_month"}, "filter": HEALTH_FILTER}),
            FunctionCall("get_safe_to_spend", {}), FunctionCall("finish")]


def test_the_stand_question_answers_safe_to_spend_and_says_the_gym_is_not_seen_on_its_own(make_pipeline):
    done, ran, model, cards = _ask(make_pipeline, ACCEPTANCE, _health_and_safe(), drafts=[LEAK, LEAK])
    assert ran == [("get_safe_to_spend", {})]                      # the Health total never ran
    assert model.compose_inputs == []                               # the template wrote it, not the model
    assert [c["card_id"] for c in cards] == ["card_safe0001"]       # no Health card
    text = done["text"]
    assert done["outcome"] == "answered"
    assert text.startswith("I can't see “gym” on its own in your transactions")
    assert "Safe to spend in the coming week" in text
    assert validator.meta_text(text) is None and "declined" not in text and "health" not in text.lower()
    assert "llm_unavailable" not in done["warnings"]                # the template by choice, not a failure


@pytest.mark.parametrize("thing, word", [("the gym", "gym"), ("yoga", "yoga"), ("massage", "massage"),
                                         ("vitamins from the supermarket", "vitamins")])
def test_no_word_that_is_not_health_gets_a_health_card(make_pipeline, thing, word):
    two = f"How much did I spend on {thing} last month and what can I safely spend this week?"
    done, ran, model, cards = _ask(make_pipeline, two, _health_and_safe(), drafts=[LEAK, LEAK])
    assert ("get_spending", HEALTH_FILTER) not in ran and model.compose_inputs == []
    assert "card_health001" not in [c["card_id"] for c in cards]
    assert f"“{word}”" in done["text"] and validator.meta_text(done["text"]) is None
    # alone: the breakdown of the same period, the rule path's answer for an unknown thing
    alone = [FunctionCall("get_spending", {"period": {"preset": "last_month"}, "filter": HEALTH_FILTER}),
             FunctionCall("finish")]
    done, ran, model, cards = _ask(make_pipeline, f"How much did I spend on {thing} last month?", alone)
    assert ran == [("get_basket_breakdown", {})] and model.compose_inputs == []
    assert [c["card_id"] for c in cards] == ["card_baskets001"]
    assert f"“{word}”" in done["text"] and "Health" not in done["text"]


def test_the_finnish_question_gets_the_finnish_sentence(make_pipeline):
    question = "Paljonko käytin kuntosaliin viime kuussa ja paljonko voin turvallisesti käyttää tällä viikolla?"
    done, ran, _, cards = _ask(make_pipeline, question, _health_and_safe(), language="fi")
    assert ran == [("get_safe_to_spend", {})] and "card_health001" not in [c["card_id"] for c in cards]
    assert done["text"].startswith("En löydä tapahtumistasi erikseen sanaa ”kuntosaliin”")


def test_the_health_mcc_group_is_guarded_too(make_pipeline):
    plan = [FunctionCall("get_spending", {"period": {"preset": "last_month"}, "filter": {"mcc_groups": ["health"]}}),
            FunctionCall("get_safe_to_spend", {}), FunctionCall("finish")]
    done, ran, _, _ = _ask(make_pipeline, ACCEPTANCE, plan)
    assert ran == [("get_safe_to_spend", {})] and "“gym”" in done["text"]


@pytest.mark.parametrize("merchant", ["Health service A", "Terveyspalvelu B"])
def test_a_health_merchant_alias_counts_as_health(make_pipeline, merchant):
    # security review of #607: a total on a health merchant's alias is Health: dropped for a question with no health
    # word, the template's for one that has it
    plan = [FunctionCall("get_spending", {"period": {"preset": "last_month"}, "filter": {"merchant": merchant}}),
            FunctionCall("get_safe_to_spend", {}), FunctionCall("finish")]
    done, ran, model, _ = _ask(make_pipeline, ACCEPTANCE, plan, drafts=[LEAK, LEAK])
    assert ran == [("get_safe_to_spend", {})] and "“gym”" in done["text"] and model.compose_inputs == []
    plan = [FunctionCall("get_spending", {"period": {"preset": "last_month"}, "filter": {"merchant": merchant}}),
            FunctionCall("finish")]
    done, ran, model, _ = _ask(make_pipeline, "How much did I spend at the pharmacy last month?", plan,
                               drafts=[LEAK, LEAK])
    assert ran == [("get_spending", {"merchant": merchant})] and model.compose_inputs == []


@pytest.mark.parametrize("question", [
    "How much did I spend at the pharmacy last month and what can I safely spend this week?",
    "Paljonko käytin apteekkiin viime kuussa ja paljonko voin turvallisesti käyttää tällä viikolla?",
])
def test_a_question_that_names_health_keeps_the_filter_and_both_sentences_are_templates(make_pipeline, question):
    lang = "fi" if question.startswith("Paljonko") else "en"
    done, ran, model, cards = _ask(make_pipeline, question, _health_and_safe(), drafts=[LEAK, LEAK], language=lang)
    assert ("get_spending", HEALTH_FILTER) in ran and ("get_safe_to_spend", {}) in ran
    assert model.compose_inputs == []                               # a Health answer is never a model draft
    assert "card_health001" in [c["card_id"] for c in cards]
    assert validator.meta_text(done["text"]) is None and "llm_unavailable" not in done["warnings"]
    assert "{{" not in done["text_rendered"]


# ---- the draft check for meta text ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    LEAK,
    "Your Health spending is declined, so here is your safe to spend: {{n1}}.",
    "I am not allowed to comment on that, but you spent {{n1}}.",
    "I'm not allowed to say more. You spent {{n1}}.",
    "My instructions say I can only give totals: {{n1}}.",
    "Before I write the answer: you spent {{n1}}.",
    "Terveyskulusi hylätään ennen kuin kirjoitan. Käytit {{n1}}.",
    "En saa kommentoida sitä, mutta käytit {{n1}}.",
    "Ohjeeni kieltävät sen. Käytit {{n1}}.",
])
def test_a_draft_about_its_own_rules_or_process_is_rejected(text):
    n1 = Number(id="n1", value=147.64, unit=Unit.EUR, period=AUG, method="spending.total@1",
                evidence_ref="ev_aaaaaaaaaaa1", label="Restaurants", display="€147.64")
    problems = validator.draft_problems(text, {"n1": n1}, has_data=True)
    assert any("your own rules, instructions or process" in p for p in problems), (text, problems)


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
    fixed = [*_texts(template.REFUSAL), *_texts(template.HEALTH_REFUSAL), *_texts(template.UNKNOWN_PLAIN),
             *_texts(template.UNKNOWN_NO_WORD), *_texts(template.UNKNOWN), *_texts(template.NOTHING)]
    assert fixed and [t for t in fixed if validator.meta_text(t)] == []
    for lang in ("en", "fi"):
        assert validator.meta_text(template.unknown_lead("gym", lang)) is None
        assert template.unknown_lead("", lang) == template.pick(template.UNKNOWN_NO_WORD, lang)
        for word in ("x2", "a" * 41):
            assert template.unknown_lead(word, lang) == template.pick(template.UNKNOWN_NO_WORD, lang)
