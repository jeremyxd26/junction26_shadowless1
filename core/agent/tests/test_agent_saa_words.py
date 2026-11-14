"""#533: a Finnish question with a word that ends in "saa" ("maksaa", "osaa", "jaksaa", "saa") is not refused as out
of scope. The folded weather word "sää" used to match the end of "maksaa" (#370's defect, fixed in #488: the weather
word is read unfolded with a word boundary on both sides). The weather and the elections stay refused. No model,
no database: the rule planner."""

from __future__ import annotations

import pytest

from core.agent import guard
from core.agent.model import PlanInput
from core.agent.rules import RuleModel
from core.agent.toolset import default_registry

TOOLS = default_registry().schemas()


def first_call(question: str):
    plan = RuleModel().plan(PlanInput(question=guard.clean(question), language="fi", as_of="2026-09-30",
                                      tools=TOOLS, history=[]))
    return plan.calls[0] if plan.calls else None


@pytest.mark.parametrize("question", [
    # the three rows of the issue, refused as the weather on dev 281c6d1
    "Paljonko minun pitää maksaa vuokraa?",
    "Paljonko minun pitaa maksaa vuokraa?",
    "Unohdin maksaa laskun, paljonko minulla on rahaa?",
    # the sweep: other words that end in "saa", all refused on dev 281c6d1
    "Paljonko sähkö maksaa kuukaudessa?",
    "Paljonko ruoka maksaa minulle kuussa?",
    "Mitä Sentti osaa?",
    "Paljonko voin käyttää, jos jaksaa säästää?",
    "Paljonko saa käyttää tällä viikolla?",
    "Mitä vuokra maksaa vuodessa?",
    "Paljonko laskut maksaa ennen palkkapäivää?",
    "Kuinka paljon kahvi maksaa minulle kuukaudessa?",
    # a folded decline word inside an ordinary word (vaali in vaatteisiin): answered on dev too. No health row:
    # health spending is declined everywhere (#443's health rule wins)
    "Paljonko käytin vaatteisiin viime kuussa?",
])
def test_a_word_that_ends_in_saa_is_not_refused_as_the_weather(question):
    call = first_call(question)
    assert call is not None and not (call.name == "decline" and call.args.get("kind") == "out_of_scope"), question


@pytest.mark.parametrize("question", [
    "Millainen sää on huomenna?",
    "Mikä on sääennuste?",          # answered with a clarifying question on dev 281c6d1; refused since #488
    "Ketä minun pitäisi äänestää seuraavissa vaaleissa?",
])
def test_the_weather_and_the_elections_stay_refused(question):
    call = first_call(question)
    assert call is not None and call.name == "decline" and call.args == {"kind": "out_of_scope"}, question
