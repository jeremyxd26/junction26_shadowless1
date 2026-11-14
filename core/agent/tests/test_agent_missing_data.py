"""Missing data (#379, part A): a period outside the data is answered by the template, whoever planned.

The tool reports why it has nothing (period_before_data, period_in_future); an answer that is only that
reason takes a fixed route: outcome "answered", the template's text, chips the rules answer, no compose
request, the same with the model on or off (the coordinator's decision A). No model, no database.
"""

from __future__ import annotations

import re
from datetime import date

import pytest
from agent_fakes import AS_OF, FakeArgs, fake_spending, registry, run

from core.agent import template
from core.agent.model import FunctionCall, PlanInput, ScriptedModel
from core.agent.registry import ToolSpec
from core.agent.rules import RuleModel
from core.agent.validator import Allowed, check_text
from core.tools import config
from core.tools.missing import MissingData
from core.tools.models import Number, Period, Unit
from core.tools.periods import PeriodOutOfRange, clamp

ALL = ["get_spending", "get_basket_breakdown", "get_recurring_bills", "get_safe_to_spend", "get_safe_to_save",
       "run_what_if", "get_spender_profile", "get_peer_benchmark", "get_bonus_estimate", "get_balance_forecast"]


@pytest.mark.parametrize("start,end,reason", [
    (date(2023, 1, 1), date(2023, 12, 31), "period_before_data"),
    (date(2024, 9, 1), date(2024, 9, 30), "period_before_data"),
    (date(2026, 10, 1), date(2026, 10, 31), "period_in_future"),
    (date(2027, 3, 1), date(2027, 3, 31), "period_in_future"),
])
def test_a_period_outside_the_data_says_which_side(start, end, reason):
    with pytest.raises(PeriodOutOfRange) as exc:
        clamp(start, end, AS_OF)
    assert exc.value.reason == reason


@pytest.mark.parametrize("reason,lang", [(r, lang) for r in template.MISSING for lang in ("en", "fi")])
def test_each_reason_text_is_short_has_no_number_and_its_chips_are_questions_the_rules_answer(reason, lang):
    text, chips = template.missing_data_answer([], [{"tool": "get_spending", "error": "period_out_of_range",
                                                     "reason": reason}], lang, AS_OF)
    assert text == template.pick(template.MISSING[reason], lang).format(
        end="30.9.2026" if lang == "fi" else "30 September 2026")
    sentences = [x for x in re.split(r"[.?](?=\s+[A-ZÄÖÅ]|\s*$)", text) if x.strip()]
    assert len(text.split()) <= 35 and len(sentences) <= 2
    # The only date in the text is the last day of the data (a returned date); no other digit.
    assert check_text(text, Allowed(frozenset({AS_OF}), frozenset())) == []
    tools = [{"name": t, "description": "", "parameters_json_schema": {}} for t in ALL]
    for chip in chips:
        assert RuleModel().plan(PlanInput(question=chip, language=lang, as_of=AS_OF.isoformat(), tools=tools)).recognised, chip


def test_the_chips_name_the_first_month_of_the_data():
    _, chips = template.missing_data_answer([], [{"reason": "period_before_data"}], "en", AS_OF)
    assert chips[0] == f"How much did I spend in October {config.DATA_START.year}?"
    _, chips = template.missing_data_answer([], [{"reason": "period_before_data"}], "fi", AS_OF)
    assert chips[0] == f"Paljonko käytin lokakuussa {config.DATA_START.year}?"


@pytest.mark.parametrize("first,en,fi", [
    ("2025-01-14", "How much did I spend in January 2025?", "Paljonko käytin tammikuussa 2025?"),
    ("2023-05-01", "How much did I spend in October 2024?", "Paljonko käytin lokakuussa 2024?"),  # never before the data
    ("not a date", "How much did I spend in October 2024?", "Paljonko käytin lokakuussa 2024?"),
])
def test_the_chip_names_the_customers_own_first_month_when_the_tool_reports_it(first, en, fi):
    errors = [{"reason": "period_before_data", "details": {"first": first, "last": "2026-09-30"}}]
    assert template.missing_data_answer([], errors, "en", AS_OF)[1][0] == en
    assert template.missing_data_answer([], errors, "fi", AS_OF)[1][0] == fi


def test_a_view_with_data_or_an_error_without_a_reason_is_not_a_missing_data_answer():
    assert template.missing_data_answer([{"tool": "x"}], [{"reason": "period_in_future"}], "en", AS_OF) is None
    assert template.missing_data_answer([], [{"error": "tool_failed"}], "en", AS_OF) is None
    assert template.missing_data_answer([], [], "en", AS_OF) is None


def outside(reason: str):
    def tool(ctx, args: FakeArgs):
        raise PeriodOutOfRange("no data", reason=reason)
    return ToolSpec("fake_outside", "A period outside the data.", FakeArgs, tool, ("Looking", "Katson"))


@pytest.mark.parametrize("reason", ["period_in_future", "period_before_data"])
def test_the_pipeline_answers_a_period_outside_the_data_with_the_template_and_no_compose_request(make_pipeline, reason):
    model = ScriptedModel(plans=[[FunctionCall("fake_outside", {}), FunctionCall("finish")]])
    events = run(make_pipeline(model, registry(outside(reason))), "How much did I spend then?", language="en")
    done = dict(events)["done"]
    assert done["outcome"] == "answered" and done["cited"] == [] and done["refusal"] is None
    assert done["text"] == template.missing_data_answer([], [{"reason": reason}], "en", AS_OF)[0]
    assert done["follow_ups"] and model.compose_inputs == []          # the model wrote nothing
    assert "card" not in [e for e, _ in events]                        # nothing to show


def test_a_period_outside_the_data_next_to_real_data_is_written_by_the_composer(make_pipeline):
    draft = {"language": "en", "text": "In August 2026 you spent {{n1}}.", "cited": ["n1"], "lesson_key": None}
    model = ScriptedModel(plans=[[FunctionCall("fake_spending", {}), FunctionCall("fake_outside", {}),
                                  FunctionCall("finish")]], drafts=[draft])
    reg = registry(outside("period_in_future"))
    events = run(make_pipeline(model, reg), "How much did I spend in August and next month?", language="en")
    assert len(model.compose_inputs) == 1
    assert model.compose_inputs[0].errors[0]["reason"] == "period_in_future"   # the composer sees the reason
    assert dict(events)["done"]["outcome"] == "answered"
    assert fake_spending  # the registry's own data tool ran beside it
    # on the rule path the same message is claimed by no rule: the model plans both calls (review of #443)
    tools = [{"name": n, "description": "", "parameters_json_schema": {}} for n in ALL]
    assert not RuleModel().plan(PlanInput(question="How much did I spend in August and next month?", language="en",
                                          as_of=AS_OF.isoformat(), tools=tools)).recognised



# ---- part B: a category never used, an object no category maps, too few purchases ----------------------

TOP = [{"key": "Travel", "label": "Travel"}, {"key": "Groceries", "label": "Groceries"},
       {"key": "Restaurants", "label": "Restaurants"}, {"key": "Lifestyle", "label": "Lifestyle"}]


def test_a_category_never_used_names_it_and_offers_the_customers_largest_categories():
    text, chips = template.missing_data_answer([], [{"reason": "category_absent",
                                                     "details": {"what": "Entertainment", "top": TOP}}], "en", AS_OF)
    assert text == "I can't find any entertainment spending in your data. Your largest categories are travel, " \
                   "groceries and restaurants."
    assert chips == ["How much did I spend on travel last month?", "How much did I spend on groceries last month?",
                     "How much did I spend on restaurants last month?"]


def test_health_is_never_a_chip():
    top = [{"key": "Health", "label": "Health"}, *TOP]
    text, chips = template.missing_data_answer([], [{"reason": "category_absent",
                                                     "details": {"what": "Entertainment", "top": top}}], "en", AS_OF)
    assert "health" not in text.lower() and not any("health" in c.lower() for c in chips)


def basket_view(lang="en"):
    names = {"Restaurants": ("Restaurants", "Ravintolat"), "Health": ("Health", "Terveys"),
             "Lifestyle": ("Lifestyle", "Lifestyle"), "Travel": ("Travel", "Matkailu")}
    cats = [{"key": k, "label": names[k][lang == "fi"], "amount": {"id": f"n{i}", "value": v, "unit": "eur_per_month"}}
            for i, (k, v) in enumerate([("Health", 400.0), ("Restaurants", 224.2), ("Lifestyle", 73.6),
                                         ("Travel", 58.4)], start=1)]
    return {"tool": "get_basket_breakdown", "baskets": [{"key": "everyday_spending", "categories": cats}]}


@pytest.mark.parametrize("lang,text", [
    ("en", "I can't see \u201cgym\u201d on its own in your transactions: they are grouped into categories, and your largest "
           "are restaurants, lifestyle and travel."),
    ("fi", "En löydä tapahtumistasi erikseen sanaa \u201dkuntosaliin\u201d: kulutus on ryhmitelty luokkiin, ja suurimmat "
           "ovat Ravintolat, Lifestyle ja Matkailu."),
])
def test_an_object_no_category_maps_is_answered_with_the_customers_categories(lang, text):
    word = "gym" if lang == "en" else "kuntosaliin"
    got, chips = template.missing_data_answer([basket_view(lang)], [], lang, AS_OF, unknown=word)
    assert got == text and len(chips) == 3 and not any("health" in c.lower() or "terveys" in c.lower() for c in chips)


@pytest.mark.parametrize("label_key,lang", [(k, lang) for k in sorted(template.CHIP_CATEGORIES)
                                            for lang in ("en", "fi") if not (lang == "fi" and k in template.FI_NO_CHIP)])
def test_every_category_chip_is_a_question_the_rules_answer(label_key, lang):
    label = config.label(config.CATEGORY_LABELS[label_key], lang)
    chip = template.pick(template.CATEGORY_CHIP, lang).format(category=label.lower() if lang == "en" else label)
    tools = [{"name": t, "description": "", "parameters_json_schema": {}} for t in ALL]
    result = RuleModel().plan(PlanInput(question=chip, language=lang, as_of=AS_OF.isoformat(), tools=tools))
    assert result.recognised and result.calls[0].name == "get_spending", chip


def too_few_tool(n: int):
    def tool(ctx, args: FakeArgs):
        span = Period(start=date(2026, 4, 1), end=date(2026, 9, 30), label="1 Apr – 30 Sep 2026")
        total = ctx.numbers.register(Number(value=203.95, unit=Unit.EUR, period=span, method="spending.total@1",
                                            evidence_ref="ev_aaaaaaaaaaa1", label="Travel", display="€203.95"))
        count = ctx.numbers.register(Number(value=n, unit=Unit.COUNT, period=span, method="spending.n_tx@1",
                                            evidence_ref="ev_aaaaaaaaaaa2", label="Purchases", display=str(n)))
        raise MissingData("too_few_transactions", what="travel", period=span.label, total=total.id, count=count.id, n=n)
    return ToolSpec("fake_what_if", "A what-if on too few purchases.", FakeArgs, tool, ("Looking", "Katson"))


@pytest.mark.parametrize("n,text", [
    (1, "In 1 Apr – 30 Sep 2026 you made a single travel purchase of €203.95, so there is no monthly habit to cut."),
    (2, "In 1 Apr – 30 Sep 2026 you made 2 travel purchases, €203.95 in all: too few to show a monthly habit to cut."),
])
def test_a_what_if_on_too_few_purchases_shows_them_and_derives_no_monthly_figure(make_pipeline, n, text):
    model = ScriptedModel(plans=[[FunctionCall("fake_what_if", {}), FunctionCall("finish")]])
    events = run(make_pipeline(model, registry(too_few_tool(n))), "What if I cut travel by 20%?", language="en")
    done = dict(events)["done"]
    assert done["outcome"] == "answered" and done["text_rendered"] == text and model.compose_inputs == []
    assert len(done["cited"]) == (1 if n == 1 else 2)


def basket_tool():
    def tool(ctx, args: FakeArgs):
        from core.tools.models import ToolResult
        return ToolResult(tool="fake_baskets", data={}, card=None, evidence=[], model_view=basket_view())
    return ToolSpec("fake_baskets", "Baskets.", FakeArgs, tool, ("Looking", "Katson"))


def test_the_pipeline_answers_an_unknown_object_with_the_template_and_no_compose_request(make_pipeline):
    view = basket_view()
    view["tool"] = "get_basket_breakdown"

    def tool(ctx, args: FakeArgs):
        from core.tools.models import ToolResult
        return ToolResult(tool="get_basket_breakdown", data={}, card=None, evidence=[], model_view=view)
    spec = ToolSpec("fake_baskets", "Baskets.", FakeArgs, tool, ("Looking", "Katson"))
    model = ScriptedModel(plans=[[FunctionCall("fake_baskets", {}), FunctionCall("finish")]])
    events = run(make_pipeline(model, registry(spec)), "how much do I spend on the gym?", language="en")
    done = dict(events)["done"]
    assert done["outcome"] == "answered" and "\u201cgym\u201d" in done["text"] and model.compose_inputs == []
    assert done["follow_ups"][0] == "How much did I spend on restaurants last month?"


def test_the_future_text_names_the_last_day_the_tool_reports():
    errors = [{"reason": "period_in_future", "details": {"first": "2024-10-03", "last": "2026-09-29"}}]
    assert template.missing_data_answer([], errors, "en", AS_OF)[0].startswith("My data ends on 29 September 2026,")
    assert template.missing_data_answer([], errors, "fi", AS_OF)[0].startswith("Tietoni ulottuvat 29.9.2026 asti,")
    # never a day after the data's own last day
    errors = [{"reason": "period_in_future", "details": {"last": "2027-01-01"}}]
    assert template.missing_data_answer([], errors, "en", AS_OF)[0].startswith("My data ends on 30 September 2026,")

