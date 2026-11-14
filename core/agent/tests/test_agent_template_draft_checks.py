"""Every model-draft check passes every template answer (review of #437).

The checks that reject a model draft (orchestrator._compose: draft_problems with the borrowing, cut, count,
ranking and sum checks; the contents claim; the "not available" claim; the repeated period) never run on a
template at runtime. This test holds them to the same texts anyway, in English and Finnish, so a check that
would reject an ordinary sentence fails here before it costs a real request on the stand:
- the rule answers of test_agent_human_answers.py and its two-view answers (one with an error sentence),
- the profile, peer, S-Bonus and forecast answers of test_agent_short_profile.py,
- the small-purchases sentence for one to 31 purchases,
- safe to spend and safe to save next to a savings goal (#391), and the savings plan (#369, #411),
- the answers to the review question (#341, #398),
- the introduction, thanks, brief questions, clarifying questions and refusals.
Each text is checked with its own Number objects and the labels of its views, as the pipeline checks a draft.
No database.
"""

from __future__ import annotations

from datetime import date

import pytest
import test_agent_human_answers as human
import test_agent_review_amount as review
import test_agent_short_profile as short
import test_agent_small_purchases as small

from core.agent import template
from core.agent.orchestrator import _labels_in
from core.app.api import texts as api_texts
from core.agent.validator import contents_claim, draft_problems, repeated_period, unavailable_claim
from core.tools.models import Number, Period, Unit
from core.tools.tests.test_tools_savings_plan_pure import fake, what_if  # noqa: F401 (fixture)

LANGS = ("en", "fi")
ERROR = [{"tool": "get_safe_to_save", "error": "tool_failed"}]
REVIEW_QUESTIONS = {
    "en": ["what was that €1,080?", "what was the 1080 purchase?", "why are you asking me about 1080 euros?",
           "Why are you asking about €1,080?", "what is this question about 1080?",
           "why are you asking me about that purchase?", "why do you ask?"],
    "fi": ["mikä se 1080 euron ostos oli?", "miksi kysyt 1080 eurosta?", "miksi kysyt siitä ostoksesta?",
           "mistä tämä kysymys 1080 eurosta?"],
}


def _review_numbers(cited: list[str], lang: str) -> dict[str, Number]:
    day = Period(start=date(2026, 9, 28), end=date(2026, 9, 28), label="28 Sep 2026")
    return {i: Number(id=i, value=1080.42, unit=Unit.EUR, period=day, method="spending.total@1",
                      evidence_ref="ev_cccccccccccc", label="Home & Tech purchase",
                      display="€1,080.42" if lang == "en" else "1 080,42 €") for i in cited}


def _goal_views(v) -> dict[str, list[dict]]:
    """Safe to spend and safe to save next to a savings goal (#391), built as test_agent_template.py builds them,
    with Number objects for the checks."""
    week, month = human.WEEK, human.WINDOW

    def hero(safe, goal, binding="budget"):
        return {"tool": "get_safe_to_spend",
                "safe_to_spend": v.n(safe, "eur", week, "safe_to_spend.safe_to_spend_7d_eur@1", "Safe to spend"),
                "balance_limit": v.n(5864.86, "eur", week, "safe_to_spend.balance_limit_eur@1", "Balance limit"),
                "budget_limit": v.n(safe, "eur", week, "safe_to_spend.budget_limit_eur@1", "Budget limit"),
                "savings_goal": v.n(goal, "eur_per_month", month, "user_input@1", "Savings goal"),
                "usual_week": v.n(137.8, "eur_per_week", month, "safe_to_spend.usual_week_eur@1", "Usual week"),
                "binding_limit": binding}

    def save(monthly):
        return {"tool": "get_safe_to_save",
                "monthly": v.n(monthly, "eur_per_month", month, "safe_to_spend.safe_to_save_monthly_eur@1",
                               "Safe to save"),
                "stock": v.n(12272.28, "eur", human.PAYDAY, "safe_to_spend.safe_to_save_eur@1", "Stock"),
                "savings_goal": v.n(360.0, "eur_per_month", month, "user_input@1", "Savings goal"),
                # the hero's own 7-day amount (a plain eur figure, as core/tools/safe_to_save.py registers it)
                "safe_to_spend_week": v.n(138.79, "eur", week, "safe_to_spend.safe_to_spend_7d_eur@1",
                                          "Safe to spend")}

    return {"goal_below_usual": [hero(97.46, 360.0)], "goal_within_usual": [hero(138.79, 360.0)],
            "goal_none": [hero(180.26, 0.0)], "goal_balance_side": [hero(180.26, 360.0, "balance")],
            "save_above_goal": [save(364.31)], "save_below_goal": [save(184.61)]}


def texts():
    """(name, token text, numbers, labels, has_data, tool errors) for every template answer."""
    out = []
    for lang in LANGS:
        for key in sorted(human.CASES):
            draft, v, views, _ = human.answer(key, lang)
            out.append((f"human:{key}:{lang}", draft["text"], v.numbers, _labels_in(views), True, []))
        for key in sorted(human.TWO_VIEWS):
            draft, v, views, _, _ = human.two_views(key, lang)
            out.append((f"two_views:{key}:{lang}", draft["text"], v.numbers, _labels_in(views), True, []))
        draft, v, views, _, _ = human.two_views("spending_payday", lang, ERROR)
        out.append((f"two_views:spending_payday+error:{lang}", draft["text"], v.numbers, _labels_in(views), True,
                    ERROR))
        for key in sorted(short.CASES):
            draft, v, views = short.answer(key, lang)
            out.append((f"short:{key}:{lang}", draft["text"], v.numbers, _labels_in(views), True, []))
        # The texts that keep their reason: a hidden peer comparison and an S-Bonus that is not offered.
        v = short.Views(lang)
        views = [{**short.peer(v, lang), "shown": False, "reason": "group_too_small"}]
        draft = template.template_draft(views, [], lang, None, "How do I compare with people like me?")
        out.append((f"short:peers_hidden:{lang}", draft["text"], v.numbers, _labels_in(views), True, []))
        v = short.Views(lang)
        views = [short.bonus(v, lang, status="not_offered")]
        draft = template.template_draft(views, [], lang, None, "How much S-Bonus could I get?")
        out.append((f"short:bonus_not_offered:{lang}", draft["text"], v.numbers, _labels_in(views), True, []))
        for key in sorted(_goal_views(human.Views(lang))):
            v = human.Views(lang)
            views = _goal_views(v)[key]
            draft = template.template_draft(views, [], lang, None)
            out.append((f"goal:{key}:{lang}", draft["text"], v.numbers, _labels_in(views), True, []))
        for n in range(1, 32):
            text, cited = small.compose(small.restaurants(n), lang, labels={})   # no label store at collection
            out.append((f"small:{n}:{lang}", text, cited, ["Restaurants", "Ravintolat"], True, []))
        for question in REVIEW_QUESTIONS[lang]:
            done, _, _ = review.ask(question, lang)
            out.append((f"review:{question}", done["text"], _review_numbers(done["cited"], lang),
                        ["Home & Tech"], True, []))
        fixed = [("intro", template.meta_text("intro", lang)), ("thanks", template.meta_text("thanks", lang)),
                 ("clarify_general", template.pick(template.CLARIFY_GENERAL["question"], lang)),
                 ("clarify_period", template.pick(template.CLARIFY["question"], lang)),
                 ("ai_disclosure", template.pick(api_texts.AI_DISCLOSURE, lang))]
        fixed += [(f"brief:{i}", q) for i, q in enumerate(template.brief_questions(lang))]
        fixed += [(f"refusal:{kind}", template.pick(entry["text"], lang)) for kind, entry in template.REFUSAL.items()]
        out += [(f"fixed:{name}:{lang}", text, {}, [], False, []) for name, text in fixed]
        # Said only after the model failed, which is the case the "not available" check leaves out.
        out.append((f"fixed:not_worked_out:{lang}", template.pick(template.NOT_WORKED_OUT, lang), {}, [], False,
                    ["model_failed"]))
    return out


TEXTS = texts()


def test_the_sweep_covers_every_kind_of_template():
    kinds = {name.split(":")[0] for name, *_ in TEXTS}
    assert kinds == {"human", "two_views", "short", "goal", "small", "review", "fixed"}
    assert len(TEXTS) > 150


@pytest.mark.parametrize("name, text, numbers, labels, has_data, errors", TEXTS, ids=[t[0] for t in TEXTS])
def test_no_model_draft_check_rejects_a_template(name, text, numbers, labels, has_data, errors):
    problems = draft_problems(text, numbers, has_data=has_data, labels=labels)
    claim = None if errors else unavailable_claim(text)
    assert problems == [] and claim is None and contents_claim(text) is None \
        and repeated_period(text, numbers) is None, (text, problems, claim)


def _check(text, numbers, labels):
    problems = draft_problems(text, numbers, has_data=True, labels=labels)
    assert problems == [] and unavailable_claim(text) is None and contents_claim(text) is None \
        and repeated_period(text, numbers) is None, (text, problems)


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("levers", ["all", "one", "none"])
def test_no_model_draft_check_rejects_the_savings_plan(fake, lang, levers):  # noqa: F811
    """The savings plan's sentences (#369, #411), on the tool fixture of test_tools_savings_plan_pure.py."""
    from core.tools import savings_plan as sp
    from core.tools.context import ToolContext

    if levers != "all":
        for c in ("Entertainment", "Lifestyle", "Travel") + (("Restaurants",) if levers == "none" else ()):
            fake.what_ifs[c] = what_if("20.00", "0.00" if levers == "none" else "2.00", ref=f"ev_{c[:3]}")
    ctx = ToolContext(customer_id="CUST00860", as_of=human.AS_OF, conn=None, language=lang)
    view = sp.get_savings_plan(ctx, {}).model_view
    draft = template.template_draft([view], [], lang, None, "How could I save more?")
    assert "{{" in draft["text"], draft["text"]
    _check(draft["text"], ctx.numbers.all(), _labels_in([view]))
