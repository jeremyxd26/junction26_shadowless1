"""Renat: other periods come up in the conversation. After a data answer one chip asks about another period, in words
the rules answer at once; never after a comparison, never the period just asked, and none after a meta reply."""

from __future__ import annotations

import pytest

from core.agent import template
from core.agent.model import PlanInput
from core.agent.rules import claim
from core.agent.toolset import default_registry

DATA = [{"tool": "get_basket_breakdown"}]


@pytest.mark.parametrize("question, lang, chip", [
    ("Where did my money go?", "en", "What did I spend last month?"),
    ("Mihin rahani menivät?", "fi", "Paljonko käytin viime kuussa?"),
    ("What did I spend this month?", "en", "What did I spend last month?"),
    ("What did I spend last month?", "en", "How did this month compare with last month?"),
    ("Paljonko käytin viime kuussa?", "fi", "Miten tämä kuu vertautuu viime kuuhun?"),
])
def test_a_data_answer_offers_another_period_first(question, lang, chip):
    assert template.follow_ups(question, lang, views=DATA)[0] == chip


def test_no_period_chip_after_a_comparison_or_a_meta_reply():
    after_compare = template.follow_ups("How did this month compare with last month?", "en", views=DATA)
    assert not set(after_compare) & {c[0] for c in template.PERIOD_CHIPS.values()}
    assert not set(template.follow_ups("Hi", "en")) & {c[0] for c in template.PERIOD_CHIPS.values()}


@pytest.mark.parametrize("key", sorted(template.PERIOD_CHIPS))
@pytest.mark.parametrize("i, lang", [(0, "en"), (1, "fi")])
def test_every_period_chip_is_a_question_the_rules_answer(key, i, lang):
    chip = template.PERIOD_CHIPS[key][i]
    found = claim(PlanInput(question=chip, language=lang, as_of="2026-09-30", tools=default_registry().schemas()))
    assert found.rule == "spending" and found.calls[0].name == "get_spending", (chip, found)
