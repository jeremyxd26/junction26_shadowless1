"""#569: one line of national context after the peer comparison (Statistics Finland's household budget survey).
Context, never a verdict: two facts side by side, no comparison word, within the digit and length rules. No
database and no network."""

from __future__ import annotations

import re

import pytest

from core import answer_text
from core.agent import answer_sentences
from core.agent.model import PlanInput
from core.agent.rules import RuleModel
from core.tools import config
from core.tools.peer import age_band_of

ALL = ["get_spending", "get_basket_breakdown", "get_recurring_bills", "get_safe_to_spend", "get_safe_to_save",
       "run_what_if", "get_spender_profile", "get_peer_benchmark", "get_bonus_estimate"]
COMPARISON = r"\b(more|less|than|above|below|average|higher|lower|too|should|enemmän|vähemmän|kuin|keskiarvo\w*|" \
             r"yli|alle|liikaa|pitäisi)\b"


def view(language: str, vs: float = 14.2, offers_cut: bool = False, national: bool = True) -> dict:
    v = {"tool": "get_peer_benchmark", "metric": "Groceries", "shown": True, "offers_cut": offers_cut,
         "metric_label": "Groceries" if language == "en" else "Ruokaostokset",
         "vs_median": {"id": "n6", "value": vs, "unit": "percent", "label": "x"}}
    if national:
        v["national"] = {"amount": {"id": "n8", "value": 332.33, "unit": "eur_per_month", "label": "x"},
                         "survey": "1 Jan – 31 Dec 2022" if language == "en" else "1.1.–31.12.2022",
                         "source": "Statistics Finland" if language == "en" else "Tilastokeskus",
                         "what": "food and non-alcoholic drinks" if language == "en" else
                         "elintarvikkeisiin ja alkoholittomiin juomiin",
                         "what_short": "food" if language == "en" else "ruokaan", "context_only": True}
    return v


def ok(text, **kw):
    return True


@pytest.mark.parametrize("language,words", [
    ("en", "per adult-equivalent on food and non-alcoholic drinks (Statistics Finland, 1 Jan – 31 Dec 2022)."),
    ("fi", "käyttivät elintarvikkeisiin ja alkoholittomiin juomiin {{n8}} aikuista vastaavaa henkilöä kohti "
           "(Tilastokeskus, 1.1.–31.12.2022)."),
])
def test_the_line_follows_the_comparison_with_the_source_and_the_survey_period(language, words):
    sentences, ids = answer_sentences.peer(view(language), language, ok)
    assert len(sentences) == 2 and ids == ["n6", "n8"] and "{{n8}}" in sentences[1] and words in sentences[1]
    assert not re.search(COMPARISON, sentences[1], re.I), sentences[1]   # two facts, the customer compares
    assert answer_sentences.peer(view(language, national=False), language, ok) == (sentences[:1], ["n6"])


@pytest.mark.parametrize("language", ["en", "fi"])
@pytest.mark.parametrize("vs,offers_cut", [(14.2, False), (89.5, True), (-40.0, False)])
def test_the_comparison_and_the_line_keep_the_length_rule(language, vs, offers_cut):
    sentences, ids = answer_sentences.peer(view(language, vs, offers_cut), language, ok)
    assert answer_text.length_problems(" ".join(sentences), len(ids)) == []
    assert len(sentences) == 2      # the line fits next to every comparison of the kept categories


def test_the_short_category_words_when_the_long_ones_do_not_fit():
    v = view("en", 89.5, offers_cut=True)
    v["national"]["what"] = "transport without buying a vehicle"
    v["national"]["what_short"] = "transport"
    sentences, ids = answer_sentences.peer(v, "en", ok)
    assert len(sentences) == 2 and " on transport (" in sentences[1]
    assert answer_text.length_problems(" ".join(sentences), len(ids)) == []


def test_the_line_is_dropped_when_it_would_break_the_length_rule(monkeypatch):
    long = ("Households your age spent {amount} per adult-equivalent on {what} ({source}, {period}), " +
            "and so on " * 8 + "today.", "x")
    monkeypatch.setattr(answer_sentences, "NATIONAL", long)
    sentences, ids = answer_sentences.peer(view("en"), "en", ok)
    assert len(sentences) == 1 and ids == ["n6"]


def test_no_digit_in_the_line_or_the_label():
    # the digit rule (R1): only Numbers and returned dates and periods may carry digits, so the age group is in
    # words ("your age group") and the survey year is the Number's own period
    for text in [*answer_sentences.NATIONAL, *config.PEER_TEXT["national_label"]]:
        assert not re.search(r"\d", text), text


def test_the_line_needs_a_survey_period_and_a_source():
    v = view("en")
    del v["national"]["survey"]
    assert len(answer_sentences.peer(v, "en", ok)[0]) == 1


def test_the_age_band_is_the_first_word_of_the_peer_group_at_every_level_with_an_age():
    assert age_band_of("age_band+area3", "35-44 005") == "35-44"
    assert age_band_of("age_band+city", "25-34 02") == "25-34"
    assert age_band_of("age_band", "45-54") == "45-54"
    assert age_band_of("all", "all") is None


@pytest.mark.parametrize("question,lang,metric", [
    # #569: a comparison of one named category compares that category; the line sits beside it
    ("How does my grocery spending compare with people like me?", "en", "Groceries"),
    ("Miten ruokaostokseni vertautuvat kaltaisiini?", "fi", "Groceries"),
    ("Miten liikkumiseen käyttämäni rahat vertautuvat kaltaisiini?", "fi", "Transportation"),
    ("How do my restaurant costs compare with people like me?", "en", "Restaurants"),
    ("How do I compare with people like me?", "en", "spend_total"),
    ("Miten kulutukseni vertautuu kaltaisiini?", "fi", "spend_total"),
])
def test_a_peer_question_naming_one_category_compares_that_category(question, lang, metric):
    plan = RuleModel().plan(PlanInput(question=question, language=lang, as_of="2026-09-30",
                                      tools=[{"name": t, "description": "", "parameters_json_schema": {}} for t in ALL]))
    calls = [(c.name, c.args) for c in plan.calls if c.name != "finish"]
    assert calls == [("get_peer_benchmark", {"metric": metric})]


def test_a_health_comparison_is_still_declined():
    plan = RuleModel().plan(PlanInput(question="How does my health spending compare with people like me?",
                                      language="en", as_of="2026-09-30",
                                      tools=[{"name": t, "description": "", "parameters_json_schema": {}} for t in ALL]))
    assert [c.name for c in plan.calls] == ["decline"]


# ---- the model path: the template writes a peer answer with the line; the validator guards the figure anyway ----

def _numbers():
    from datetime import date

    from core.tools.models import Number, Period, Unit
    year = Period(start=date(2022, 1, 1), end=date(2022, 12, 31), label="1 Jan – 31 Dec 2022")
    month = Period(start=date(2026, 4, 1), end=date(2026, 9, 30), label="1 Apr – 30 Sep 2026")
    return {"n8": Number(id="n8", value=332.33, unit=Unit.EUR_PER_MONTH, period=year,
                         method="national_context.monthly_eur@1", evidence_ref="ev_aaaaaaaaaaa8", label="x",
                         display="€332.33 a month"),
            "n1": Number(id="n1", value=628.86, unit=Unit.EUR_PER_MONTH, period=month,
                         method="peer_benchmark.you_month_eur@1", evidence_ref="ev_aaaaaaaaaaa1", label="x",
                         display="€628.86 a month")}


@pytest.mark.parametrize("text,bad", [
    ("Households your age spent {{n8}} per adult-equivalent on food (Statistics Finland, 1 Jan – 31 Dec 2022).",
     False),
    ("You spend {{n1}}, more than households of your age at {{n8}} (Statistics Finland, 1 Jan – 31 Dec 2022).", True),
    ("Households of your age spent only {{n8}} on food (Statistics Finland, 1 Jan – 31 Dec 2022).", True),
    ("Ikäryhmäsi kotitaloudet käyttivät {{n8}} vähemmän kuin sinä (Tilastokeskus, 1.1.–31.12.2022).", True),
])
def test_the_validator_never_lets_the_figure_become_a_comparison(text, bad):
    from core.agent.validator import national_problems
    assert bool(national_problems(text, _numbers())) is bad


def test_a_peer_answer_with_the_line_is_written_by_the_template_and_no_model_draft(make_pipeline):
    from agent_fakes import FakeArgs, registry, run

    from core.agent.model import FunctionCall, ScriptedModel
    from core.agent.registry import ToolSpec
    from core.tools.models import ToolResult, Unit

    def peer_tool(ctx, args):
        nums = _numbers()
        n6 = ctx.numbers.register(nums["n1"].model_copy(update={"id": None, "value": 14.2, "unit": Unit.PERCENT,
                                                               "method": "peer_benchmark.vs_median_pct@1",
                                                               "display": "14.2% more"}))
        n8 = ctx.numbers.register(nums["n8"].model_copy(update={"id": None}))
        v = view("en")
        v["vs_median"]["id"], v["national"]["amount"]["id"] = n6.id, n8.id
        return ToolResult(tool="get_peer_benchmark", data={}, card=None, evidence=[], model_view=v)

    spec = ToolSpec("get_peer_benchmark", "Peers.", FakeArgs, peer_tool, ("Looking", "Katson"))
    comparing = {"language": "en", "text": "You spend more than households of your age.", "cited": [],
                 "lesson_key": None}
    model = ScriptedModel(plans=[[FunctionCall("get_peer_benchmark", {}), FunctionCall("finish")]],
                          drafts=[comparing, comparing])
    events = run(make_pipeline(model, registry(spec)), "How does my grocery spending compare with people like me?",
                 language="en")
    done = dict(events)["done"]
    assert model.compose_inputs == [] and done["outcome"] == "answered"
    assert "Statistics Finland" in done["text"] and "more than households" not in done["text"]
    assert "llm_unavailable" not in done["warnings"]

