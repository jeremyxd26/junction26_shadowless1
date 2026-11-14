"""#664: "transport" and "liikenne" (the app's own label for the category) are Transportation and "ruokakulut" is
Groceries, on the spending, peer and what-if paths, as "transportation", "liikkuminen" and "ruoka" are. No database."""

from __future__ import annotations

import pytest

from core.agent.model import PlanInput
from core.agent.rules import RuleModel

ALL = ["get_spending", "get_basket_breakdown", "get_recurring_bills", "get_safe_to_spend", "get_safe_to_save",
       "run_what_if", "get_spender_profile", "get_peer_benchmark", "get_bonus_estimate"]


def calls(question, language):
    result = RuleModel().plan(PlanInput(question=question, language=language, as_of="2026-09-30",
                                        tools=[{"name": t, "description": "", "parameters_json_schema": {}}
                                               for t in ALL]))
    return [(c.name, c.args) for c in result.calls if c.name != "finish"]


@pytest.mark.parametrize("lang,question,category", [
    ("en", "How much did I spend on transport last month?", "Transportation"),
    ("en", "Show my transport costs last month", "Transportation"),
    ("fi", "Paljonko käytin liikenteeseen viime kuussa?", "Transportation"),
    ("fi", "Paljonko liikenne maksoi viime kuussa?", "Transportation"),
    ("fi", "Paljonko liikennekuluni olivat viime kuussa?", "Transportation"),
    ("fi", "Mitkä olivat liikenteen kulut viime kuussa?", "Transportation"),
    ("fi", "Paljonko ruokakuluni olivat viime kuussa?", "Groceries"),
])
def test_the_words_filter_their_category_on_the_spending_path(lang, question, category):
    # dev d0fc694 gave the breakdown or the unfiltered total
    assert calls(question, lang) == [("get_spending", {"filter": {"categories": [category]},
                                                       "period": {"preset": "last_month"}})]


@pytest.mark.parametrize("lang,question,metric", [
    ("en", "Do I spend more on transport than people like me?", "Transportation"),
    ("en", "How does my transport spending compare with people like me?", "Transportation"),
    ("fi", "Kulutanko liikenteeseen enemmän kuin muut kaltaiseni?", "Transportation"),
    ("fi", "Miten ruokakuluni vertautuvat kaltaisiini?", "Groceries"),
])
def test_the_words_reach_the_peer_metric_and_its_national_line(lang, question, metric):
    assert calls(question, lang) == [("get_peer_benchmark", {"metric": metric})]


@pytest.mark.parametrize("lang,question,category,pct", [
    ("en", "What if I cut transport by 20%?", "Transportation", 20),
    ("fi", "Mitä jos vähentäisin liikenteeseen käytettyä rahaa 20 %?", "Transportation", 20),
    ("fi", "Mitä jos vähentäisin ruokakuluja 10 %?", "Groceries", 10),
])
def test_the_words_select_their_category_on_the_what_if_path(lang, question, category, pct):
    assert calls(question, lang) == [("run_what_if", {"selection": {"kind": "category", "value": category},
                                                      "cut_pct": pct})]


@pytest.mark.parametrize("lang,question,group", [
    ("en", "How much did I spend on public transport last month?", "public_transport"),
    ("fi", "Paljonko käytin joukkoliikenteeseen viime kuussa?", "public_transport"),
])
def test_public_transport_stays_its_group(lang, question, group):
    assert calls(question, lang) == [("get_spending", {"filter": {"mcc_groups": [group]},
                                                       "period": {"preset": "last_month"}})]


@pytest.mark.parametrize("question", ["Paljonko liikennevakuutus maksoi?", "Paljonko maksoin liikennesakkoja?"])
def test_a_traffic_compound_is_no_transport_spending(question):
    assert not any(args.get("filter", {}).get("categories") == ["Transportation"] for _, args in calls(question, "fi"))


@pytest.mark.parametrize("lang,question", [
    ("en", "How much did I spend on transport insurance last month?"),
    ("en", "How much did I spend on transportation insurance last month?"),
    ("fi", "Paljonko maksoin liikenteen vakuutuksesta viime kuussa?"),
])
def test_a_transport_insurance_is_the_unknown_thing_breakdown_never_the_transportation_total(lang, question):
    # review of #672: insurance is no Transportation spending; both twins get dev's breakdown of "transport insurance"
    assert calls(question, lang) == [("get_basket_breakdown", {"period": {"preset": "last_month"}})]


@pytest.mark.parametrize("lang,question", [
    ("en", "How much did I pay in transport fines?"), ("en", "How much did I pay in transportation fines last year?"),
    ("fi", "Paljonko maksoin liikennesakkoja viime vuonna?"),
])
def test_a_transport_fine_asks_back_never_a_total(lang, question):
    # review of #672: a fine is a thing no filter maps (like "parking fines"); dev gave the Finnish one the total
    assert [name for name, _ in calls(question, lang)] == ["ask_clarifying_question"]
