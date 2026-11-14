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


def outside(reason: str, **details):
    def tool(ctx, args: FakeArgs):
        raise PeriodOutOfRange("no data", reason=reason, **details)
    return ToolSpec("fake_outside", "A period outside the data.", FakeArgs, tool, ("Looking", "Katson"))


@pytest.mark.parametrize("first,accepted", [("2024-10-03", True), (None, False)])
def test_a_mixed_answer_may_name_the_first_day_the_tool_returned(make_pipeline, first, accepted):
    # the error's own dates are returned dates (rule 3): the composer may say where the data starts
    text = "In August 2026 you spent {{n1}}; my data starts on 3 October 2024."
    draft = {"language": "en", "text": text, "cited": ["n1"], "lesson_key": None}
    model = ScriptedModel(plans=[[FunctionCall("fake_spending", {}), FunctionCall("fake_outside", {}),
                                  FunctionCall("finish")]], drafts=[draft, draft])
    details = {"first": first, "last": "2026-09-30"} if first else {}
    events = run(make_pipeline(model, registry(outside("period_before_data", **details))),
                 "How much did I spend in August and in 2023?", language="en")
    done = dict(events)["done"]
    assert (done["text"] == text) is accepted   # without the returned day, the template writes the answer


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
    assert text == "I can't find any spending on entertainment in your data. Your largest categories are travel, " \
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
        total = Number(value=203.95, unit=Unit.EUR, period=span, method="spending.total@1",
                       evidence_ref="ev_aaaaaaaaaaa1", label="Travel", display="€203.95")
        count = Number(value=n, unit=Unit.COUNT, period=span, method="spending.n_tx@1",
                       evidence_ref="ev_aaaaaaaaaaa2", label="Purchases", display=str(n))
        raise MissingData("too_few_transactions", numbers={"total": total, "count": count}, what="travel",
                          period=span.label, span="Between 1 Apr and 30 Sep 2026", n=n)
    return ToolSpec("fake_what_if", "A what-if on too few purchases.", FakeArgs, tool, ("Looking", "Katson"))


@pytest.mark.parametrize("n,text", [
    (1, "Between 1 Apr and 30 Sep 2026 you made a single travel purchase of €203.95, so there is no monthly habit "
        "to cut."),
    (2, "Between 1 Apr and 30 Sep 2026 you made 2 travel purchases, €203.95 in all: too few to show a monthly habit "
        "to cut."),
])
@pytest.mark.parametrize("cache", ["off", "memory"])
def test_a_what_if_on_too_few_purchases_shows_them_and_derives_no_monthly_figure(make_pipeline, n, text, cache,
                                                                                  tool_cache_off, monkeypatch):
    # with the tool cache on, the call that raises keeps no numbers in the cache: the pipeline registers them
    monkeypatch.setenv("SPIKE_REVIEWS", "off")
    monkeypatch.setattr(tool_cache_off, "mode", cache)
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



# ---- review of part B, B3: the model path gets the rule path's answer for an unknown object -------------

class PeriodArgs(FakeArgs):
    period: dict | None = None


def test_a_planned_unfiltered_total_for_an_unknown_object_becomes_the_breakdown(make_pipeline):
    from core.tools.models import Card, ToolResult

    ran: list[str] = []

    def spending(ctx, args):
        ran.append("get_spending")
        return fake_spending(ctx, args)

    def baskets(ctx, args):
        ran.append("get_basket_breakdown")
        card = Card(card_id="card_baskets001", type="breakdown", title="Where your money went",
                    subtitle="1 Apr – 30 Sep 2026", evidence_ref="ev_aaaaaaaaaaa3")
        return ToolResult(tool="get_basket_breakdown", data={}, card=card, evidence=[], model_view=basket_view())

    spending_spec = ToolSpec("get_spending", "Spending.", PeriodArgs, spending, ("Looking", "Katson"))
    baskets_spec = ToolSpec("get_basket_breakdown", "Baskets.", PeriodArgs, baskets, ("Looking", "Katson"))
    # a planner that plans the unfiltered total for "the gym": the total never runs, and no card shows it
    model = ScriptedModel(plans=[[FunctionCall("get_spending", {"period": {"preset": "last_month"}}),
                                  FunctionCall("finish")]])
    events = run(make_pipeline(model, registry(spending_spec, baskets_spec)), "how much do I spend on the gym?",
                 language="en")
    done = dict(events)["done"]
    assert ran == ["get_basket_breakdown"] and model.compose_inputs == []
    assert [p["card"]["card_id"] for e, p in events if e == "card"] == ["card_baskets001"]
    assert done["outcome"] == "answered" and "\u201cgym\u201d" in done["text"] and "restaurants" in done["text"]
    assert done["follow_ups"][0] == "How much did I spend on restaurants last month?"


def test_the_guard_leaves_a_filtered_plan_and_a_question_without_an_unknown_object_alone(make_pipeline):
    from core.tools.models import ToolResult

    ran: list[str] = []

    def spending(ctx, args):
        ran.append("get_spending")
        return fake_spending(ctx, args)

    def baskets(ctx, args):
        ran.append("get_basket_breakdown")
        return ToolResult(tool="get_basket_breakdown", data={}, card=None, evidence=[], model_view=basket_view())

    draft = {"language": "en", "text": "In August 2026 you spent {{n1}}.", "cited": ["n1"], "lesson_key": None}
    specs = (ToolSpec("get_spending", "Spending.", PeriodArgs, spending, ("Looking", "Katson")),
             ToolSpec("get_basket_breakdown", "Baskets.", PeriodArgs, baskets, ("Looking", "Katson")))
    for question in ("How much did I spend last month?", "how much did I spend on the whole of 2025?"):
        ran.clear()
        model = ScriptedModel(plans=[[FunctionCall("get_spending", {"period": {"preset": "last_month"}}),
                                      FunctionCall("finish")]], drafts=[draft])
        run(make_pipeline(model, registry(*specs)), question, language="en")
        assert ran == ["get_spending"], question


@pytest.mark.parametrize("start,end,lang,text", [
    (date(2026, 4, 1), date(2026, 9, 30), "en", "Between 1 Apr and 30 Sep 2026"),
    (date(2025, 10, 1), date(2026, 3, 31), "en", "Between 1 Oct 2025 and 31 Mar 2026"),
    (date(2026, 4, 1), date(2026, 9, 30), "fi", "Jaksolla 1.4.–30.9.2026"),
])
def test_the_span_a_too_few_sentence_starts_with(start, end, lang, text):
    from core.tools.periods import span_phrase
    assert span_phrase(start, end, lang) == text


@pytest.mark.parametrize("text,ok", [
    # the Finnish label of a period across years is a returned period like the English one (review of part B)
    ("1.10.2024\u201331.1.2025: Kulutus: {{n1}}.", True),
    ("1 Oct 2024 \u2013 31 Jan 2025: Spending: {{n1}}.", True),
    ("1.10.2024\u201328.2.2025: Kulutus: {{n1}}.", False),   # not the returned period
])
def test_a_finnish_period_across_years_is_a_returned_period(text, ok):
    allowed = Allowed(frozenset({AS_OF}), frozenset({(date(2024, 10, 1), date(2025, 1, 31))}))
    assert (check_text(text, allowed) == []) is ok



def test_a_name_in_the_users_spelling_is_quoted_whole():
    text, chips = template.missing_data_answer([basket_view()], [], "en", AS_OF, unknown="Caf\u00e9 M\u00fcller")
    assert text.startswith("I can't see \u201cCaf\u00e9 M\u00fcller\u201d on its own") and len(chips) == 3
    # never more than a short name of letters
    assert template.missing_data_answer([basket_view()], [], "en", AS_OF, unknown="a" * 41) is None
