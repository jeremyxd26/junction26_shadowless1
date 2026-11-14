"""#575 without a database: the why-answer's review sentence (template.why_lower_sentence with a review_effect) in
every binding and state, both languages, within the length rule; and core.agent.why_review.effect with fakes: the
pair runs in a transaction that is always rolled back, a rise gives no sentence, no review gives none."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from agent_fakes import AS_OF

from core import answer_text
from core.agent import template, why_review
from core.agent.validator import allowed_from, check_text
from core.tools import config, reviews


def node(nid, value):
    return {"id": nid, "value": value}


def view(binding="budget", goal=360.0, balance=5906.19, budget=138.79, effect=None):
    v = {"tool": "get_safe_to_spend", "safe_to_spend": node("n1", 138.79), "savings_goal": node("n2", goal),
         "balance_limit": node("n3", balance), "budget_limit": node("n4", budget), "binding_limit": binding}
    if effect is not None:
        v["review_effect"] = effect
    return v


EFFECTS = {   # (state, moved) -> the approved sentence's key
    ("pending", True): "why_review_pending_lowers", ("pending", False): "why_review_pending_same",
    ("needed", True): "why_review_needed_moved", ("needed", False): "why_review_needed_same",
}
BINDINGS = {  # first sentence key, view, ids the first sentence cites
    "why_budget_goal": (view(), ["n1", "n2"]),
    "why_budget": (view(goal=0.0), ["n1"]),
    "why_balance": (view(binding="balance", balance=120.0, budget=400.0), ["n1"]),
    "why_equal": (view(balance=138.79, budget=138.79), ["n1"]),
}


def first_sentence(key, language, v):
    tokens = {"safe": "{{n1}}", "goal": "{{n2}}", "balance": "{{n3}}", "budget": "{{n4}}"}
    text = config.label(config.SAFE_TO_SPEND_TEXT[key], language).format(**tokens)
    return text.split(". ", 1)[0] + ("" if text.split(". ", 1)[0].endswith(".") else ".") if ". " in text else text


@pytest.mark.parametrize("language", ["en", "fi"])
@pytest.mark.parametrize("binding", sorted(BINDINGS))
@pytest.mark.parametrize("state, moved", sorted(EFFECTS))
def test_the_review_sentence_takes_the_place_of_the_other_sides_figure(language, binding, state, moved):
    base, first_ids = BINDINGS[binding]
    v = {**base, "review_effect": {"state": state, "moved": moved, "amount": {"id": "n5"}}}
    text, cited = template.why_lower_sentence(v, language)
    sentence = config.label(config.SAFE_TO_SPEND_TEXT[EFFECTS[(state, moved)]], language).format(amount="{{n5}}")
    assert text == first_sentence(binding, language, v) + " " + sentence
    assert cited == first_ids + ["n5"]
    assert answer_text.length_problems(text, len(cited)) == [], text
    assert check_text(text, allowed_from([], [], AS_OF)) == [], text


@pytest.mark.parametrize("language", ["en", "fi"])
@pytest.mark.parametrize("binding", sorted(BINDINGS))
def test_without_a_review_the_574_answer_is_unchanged(language, binding):
    base, _ = BINDINGS[binding]
    tokens = {"safe": "{{n1}}", "goal": "{{n2}}", "balance": "{{n3}}", "budget": "{{n4}}"}
    assert template.why_lower_sentence(base, language)[0] == \
        config.label(config.SAFE_TO_SPEND_TEXT[binding], language).format(**tokens)


def test_an_effect_without_an_amount_number_gives_the_574_answer():
    v = view(effect={"state": "pending", "moved": True, "amount": {}})
    assert template.why_lower_sentence(v, "en") == template.why_lower_sentence(view(), "en")


# ---- core.agent.why_review.effect, with fakes ----

class FakeConn:
    def __init__(self):
        self.rollbacks = []

    @contextmanager
    def transaction(self, force_rollback=False):
        self.rollbacks.append(force_rollback)
        yield


class FakeData:
    def __init__(self):
        self.conn = FakeConn()

    @contextmanager
    def connection(self):
        yield self.conn


class FakeSteps:
    def card(self, ctx, review):
        return {"amount": {"id": "n9"}}


def ctx_with(labels):
    from core.tools.context import ToolContext
    return ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=None, language="en", _labels=labels)


def other_safe(monkeypatch, value):
    monkeypatch.setattr(why_review, "get_safe_to_spend",
                        lambda ctx, args: SimpleNamespace(data=SimpleNamespace(safe_to_spend=SimpleNamespace(value=value))))


PENDING = SimpleNamespace(tx_id=7, basket=None)
CURRENT = {"tool": "get_safe_to_spend", "safe_to_spend": node("n1", 138.79)}


@pytest.mark.parametrize("other, expected", [(97.46, {"state": "pending", "moved": True, "amount": {"id": "n9"}}),
                                             (138.79, {"state": "pending", "moved": False, "amount": {"id": "n9"}}),
                                             (150.0, None)])            # "Needed" would raise it: no text, no sentence
def test_pending_compares_with_the_purchase_answered_needed(monkeypatch, other, expected):
    other_safe(monkeypatch, other)
    data = FakeData()
    found = why_review.effect(data, FakeSteps(), ctx_with({7: reviews.UNCLASSIFIED}), PENDING, CURRENT)
    assert found == expected
    assert data.conn.rollbacks == [True]                            # always the rolled-back transaction


@pytest.mark.parametrize("other, moved", [(180.26, True), (138.79, False)])
def test_needed_compares_with_the_purchase_back_to_pending(monkeypatch, other, moved):
    other_safe(monkeypatch, other)
    answered = SimpleNamespace(tx_id=7, basket="unexpected_necessities", answered_at=None, created_at=0)
    monkeypatch.setattr(reviews, "load_reviews", lambda *a, **k: [answered])
    data = FakeData()
    found = why_review.effect(data, FakeSteps(), ctx_with({7: "unexpected_necessities"}), None, CURRENT)
    assert found == {"state": "needed", "moved": moved, "amount": {"id": "n9"}}
    assert data.conn.rollbacks == [True]


def test_not_needed_or_no_labels_gives_no_effect(monkeypatch):
    other_safe(monkeypatch, 97.46)
    answered = SimpleNamespace(tx_id=7, basket="everyday_spending", answered_at=None, created_at=0)
    monkeypatch.setattr(reviews, "load_reviews", lambda *a, **k: [answered])
    assert why_review.effect(FakeData(), FakeSteps(), ctx_with({7: "everyday_spending"}), None, CURRENT) is None
    assert why_review.effect(FakeData(), FakeSteps(), ctx_with({}), None, CURRENT) is None


def test_a_failure_drops_the_sentence_never_the_answer(monkeypatch):
    def boom(ctx, args):
        raise RuntimeError("database gone")
    monkeypatch.setattr(why_review, "get_safe_to_spend", boom)
    assert why_review.effect(FakeData(), FakeSteps(), ctx_with({7: reviews.UNCLASSIFIED}), PENDING, CURRENT) is None


def test_with_effect_copies_the_view_and_leaves_other_tools_alone(monkeypatch):
    other_safe(monkeypatch, 97.46)
    original = dict(CURRENT)
    out = why_review.with_effect(FakeData(), FakeSteps(), ctx_with({7: reviews.UNCLASSIFIED}), PENDING, original)
    assert out is not original and "review_effect" not in original and out["review_effect"]["state"] == "pending"
    other = {"tool": "get_spending", "total": node("n1", 5.0)}
    assert why_review.with_effect(FakeData(), FakeSteps(), ctx_with({7: reviews.UNCLASSIFIED}), PENDING, other) is other
