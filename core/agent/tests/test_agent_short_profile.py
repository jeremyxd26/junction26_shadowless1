"""The spender profile, the peer comparison and the S-Bonus answer within Renat's length rule (#342).

The same checks as test_agent_human_answers.py: the validator passes, at most two sentences and 35 words
for the whole answer, at most three numbers, no "label: number" chain, no number word, no judgement.
"What kind of spender am I?" plans the profile and the peer comparison: one sentence each, two numbers.
"""

from __future__ import annotations

import re

import pytest
from test_agent_human_answers import (AS_OF, CHAIN, JUDGEMENT, NUMBER_WORDS, SENTENCE_END, WINDOW, Views,
                                      fi)

from core.agent import template
from core.agent.validator import allowed_from, render, validate
from core.tools.formatting import USER_INPUT_METHOD, VS_MEDIAN_METHOD

PAYDAY_SPAN = (AS_OF, AS_OF.replace(month=10, day=15))


def profile(v: Views, lang: str, key: str = "big_ticket") -> dict:
    label, feature, value = {"big_ticket": (fi(lang, "Big ticket", "Isot ostokset"), "one_off_share", 6.0),
                             "steady": (fi(lang, "Steady", "Tasainen"), "keep_rate", 9.4),
                             "everyday_heavy": (fi(lang, "Everyday heavy", "Arkipainotteinen"), "everyday_share_pct",
                                                30.1)}[key]
    features = [{"key": feature, "decides_label": True,
                 "value": v.n(value, "percent", WINDOW, f"spender_profile.{feature}@1", feature)},
                {"key": "spend", "decides_label": False,
                 "value": v.n(3010.59, "eur_per_month", WINDOW, "spender_profile.spend_month_eur@1",
                              fi(lang, "Spending a month", "Kulutus kuukaudessa"))}]
    return {"tool": "get_spender_profile", "period": v.label(*WINDOW),
            "profile": {"key": key, "label": label, "description": "A few large purchases shape your months."},
            "traits": [], "features": features, "top_everyday_category": None, "notes": []}


def peer(v: Views, lang: str, vs: float = 1.2, metric: str = "spend_total", shown: bool = True) -> dict:
    return {"tool": "get_peer_benchmark", "metric": metric,
            "metric_label": fi(lang, "Groceries", "Ruokaostokset") if metric != "spend_total" else "Total",
            "period": v.label(*WINDOW), "shown": shown, "reason": None if shown else "group_too_small",
            "you": v.n(3010.59, "eur_per_month", WINDOW, "peer_benchmark.you_month_eur@1", "You"),
            "peer_median": v.n(2975.65, "eur_per_month", WINDOW, "peer_benchmark.peer_median_month_eur@1",
                               fi(lang, "Typical for your group", "Tyypillinen ryhmässäsi")),
            "percentile": v.n(51, "percentile", WINDOW, "peer_benchmark.percentile@1", "Your position"),
            "vs_median": v.n(vs, "percent", WINDOW, VS_MEDIAN_METHOD, "Compared with the median"),
            "peer_group": {"level": "age_band+area3", "label": "35-44, 005xx",
                           "size": v.n(118, "count", WINDOW, "peer_benchmark.peer_n@1", "People in the group"),
                           "comparable": True}}


def forecast(v: Views, lang: str, status: str = "above_zero", bills: float = 928.5) -> dict:
    below = status == "below_zero"
    return {"tool": "get_balance_forecast", "kind": "estimate", "period": v.label(*PAYDAY_SPAN), "status": status,
            "lowest_balance": v.n(-120.4 if below else 641.43, "eur", PAYDAY_SPAN, "balance_forecast.lowest_eur@1",
                                  fi(lang, "Lowest point", "Alin kohta")),
            "first_below_zero": None, "day_before_payday": None,
            "balance_now": v.n(1902.64, "eur", PAYDAY_SPAN, "safe_to_spend.balance_eur@1",
                               fi(lang, "Balance today", "Saldo tänään")),
            "bills_until_payday": v.n(bills, "eur", PAYDAY_SPAN, "balance_forecast.bills_to_date_eur@1",
                                      fi(lang, "Bills before payday", "Laskut ennen palkkapäivää")),
            "daily_pace": v.n(45.2, "eur_per_day", PAYDAY_SPAN, "balance_forecast.daily_pace_eur@1",
                              fi(lang, "Spending a day", "Kulutus päivässä")),
            "today": "2026-09-30", "next_payday": "2026-10-15", "lowest_date": "2026-10-14",
            "first_below_zero_date": "2026-10-09" if below else None, "salary_status": "upcoming", "notes": []}


def bonus(v: Views, lang: str, share: float = 80, typed: bool = False, status: str = "estimate") -> dict:
    return {"tool": "get_bonus_estimate", "kind": "estimate", "status": status,
            "share": v.n(share, "percent", WINDOW, USER_INPUT_METHOD if typed else "bonus_estimate.share_pct@1",
                         fi(lang, "Share at S-Group stores", "Osuus S-ryhmän kaupoista")),
            "grocery_month": v.n(410.2, "eur_per_month", WINDOW, "bonus_estimate.grocery_month_eur@1",
                                 fi(lang, "Groceries a month", "Ruokaostokset kuukaudessa")),
            "total_month": v.n(7.86, "eur_per_month", WINDOW, "bonus_estimate.total_month_eur@1",
                               fi(lang, "Bonus a month", "Bonus kuukaudessa")),
            "total_year": v.n(94.32, "eur_per_year", WINDOW, "bonus_estimate.total_year_eur@1",
                              fi(lang, "Bonus a year", "Bonus vuodessa")),
            "reason": ("These purchases stay below the lowest Bonus level, so no Bonus would be paid."
                       if status == "not_offered" else None),
            "assumptions": ["Assumes the share at S-Group stores; it is a what-if, not a fact about where you shop."]}


CASES = {
    "spender_type": (("What kind of spender am I?", "Millainen kuluttaja olen?"),
                     lambda v, lang: [profile(v, lang), peer(v, lang)]),
    "spender_type_steady": (("What kind of spender am I?", "Millainen kuluttaja olen?"),
                            lambda v, lang: [profile(v, lang, "steady"), peer(v, lang, -14.6)]),
    "spender_type_everyday": (("What kind of spender am I?", "Millainen kuluttaja olen?"),
                              lambda v, lang: [profile(v, lang, "everyday_heavy"), peer(v, lang, 29.1)]),
    "peers": (("How do I compare with people like me?", "Miten kulutukseni vertautuu kaltaisiini?"),
              lambda v, lang: [peer(v, lang)]),
    "peers_same": (("How do I compare with people like me?", "Miten kulutukseni vertautuu kaltaisiini?"),
                   lambda v, lang: [peer(v, lang, 0.0)]),
    "peers_category": (("How do my groceries compare with people like me?", "Miten ruokaostokseni vertautuvat?"),
                       lambda v, lang: [peer(v, lang, -8.3, metric="Groceries")]),
    "peers_below": (("How do I compare with people like me?", "Miten kulutukseni vertautuu kaltaisiini?"),
                    lambda v, lang: [peer(v, lang, -40.5)]),
    "peers_within_margin": (("How do I compare with people like me?", "Miten kulutukseni vertautuu kaltaisiini?"),
                            lambda v, lang: [peer(v, lang, 0.8)]),
    "forecast": (("Will my money last until payday?", "Riittävätkö rahani palkkapäivään?"),
                 lambda v, lang: [forecast(v, lang)]),
    "forecast_below_zero": (("Will my money last until payday?", "Riittävätkö rahani palkkapäivään?"),
                            lambda v, lang: [forecast(v, lang, "below_zero")]),
    "forecast_no_bills": (("What will my balance be before payday?", "Mikä on saldoni ennen palkkapäivää?"),
                          lambda v, lang: [forecast(v, lang, "comfortable", bills=0.0)]),
    "bonus": (("How much S-Bonus could I get?", "Paljonko S-Bonusta voisin saada?"), lambda v, lang: [bonus(v, lang)]),
    "bonus_half": (("What would my Bonus be if half my groceries were S-Group?",
                    "Mikä olisi Bonukseni, jos puolet ruokaostoksista olisi S-ryhmästä?"),
                   lambda v, lang: [bonus(v, lang, 50, typed=True)]),
}


def answer(key: str, lang: str):
    questions, build = CASES[key]
    v = Views(lang)
    views = build(v, lang)
    return template.template_draft(views, [], lang, None, questions[1] if lang == "fi" else questions[0]), v, views


@pytest.mark.parametrize("lang", ["en", "fi"])
@pytest.mark.parametrize("key", sorted(CASES))
def test_the_profile_peer_and_bonus_answers_keep_the_length_rule(key, lang):
    draft, v, views = answer(key, lang)
    text = draft["text"]
    _, errors = validate(draft, language=lang, numbers=v.numbers,
                         allowed=allowed_from(v.numbers.values(), views, AS_OF))
    assert errors == [], (text, errors)
    tokens = re.findall(r"\{\{(n\d+)\}\}", text)
    sentences = [s for s in SENTENCE_END.split(text) if s.strip()]
    assert not CHAIN.search(text), text
    assert "!" not in text and not NUMBER_WORDS.search(text) and not JUDGEMENT.search(text), text
    assert 1 <= len(sentences) <= 2, text
    assert len(re.sub(r"\{\{n\d+\}\}", "N", text).split()) <= 35, text
    assert len(tokens) <= 3 and len(set(tokens)) == len(tokens), text
    if key.startswith("spender_type"):
        assert len(tokens) <= 2, text          # the coordinator's rule for the profile answer
    assert "; " not in render(text, v.numbers).replace("(", "").replace(")", ""), text


@pytest.mark.parametrize("lang,text", [
    ("en", "Your spender profile is Big ticket: occasional big purchases make up {{n1}} of your spending. "
           "You spend {{n6}} than the median of people like you, and a what-if can show what a cut would save."),
    ("fi", "Kuluttajaprofiilisi on Isot ostokset: kertaostosten osuus kulutuksestasi on {{n1}}. "
           "Kulutat {{n6}} kuin kaltaistesi mediaani, ja laskelma näyttää, mitä vähentäminen säästäisi."),
])
def test_what_kind_of_spender_names_the_profile_the_deciding_feature_and_the_difference(lang, text):
    draft, _, _ = answer("spender_type", lang)
    assert draft["text"] == text and draft["cited"] == ["n1", "n6"]


@pytest.mark.parametrize("lang,text", [
    ("en", "If {{n1}} of your groceries came from S Group stores, your S-Bonus would be about {{n3}}, or {{n4}}."),
    ("fi", "Jos {{n1}} ruokaostoksistasi tulisi S-ryhmän kaupoista, S-Bonuksesi olisi noin {{n3}} eli {{n4}}."),
])
def test_the_bonus_answer_is_one_sentence_with_its_share(lang, text):
    draft, _, _ = answer("bonus", lang)
    assert draft["text"] == text and draft["cited"] == ["n1", "n3", "n4"]


def test_the_rendered_answers_read_as_sentences():
    draft, v, _ = answer("spender_type", "en")
    assert render(draft["text"], v.numbers) == ("Your spender profile is Big ticket: occasional big purchases make up 6.0% "
                                                "of your spending. You spend 1.2% more than the median of people "
                                                "like you, and a what-if can show what a cut would save.")
    draft, v, _ = answer("peers_same", "en")
    assert render(draft["text"], v.numbers) == "You spend about the same as the median of people like you."
    draft, v, _ = answer("bonus", "en")
    assert render(draft["text"], v.numbers) == ("If 80% of your groceries came from S Group stores, your S-Bonus "
                                                "would be about €7.86 a month, or €94.32 a year.")


def test_a_hidden_peer_comparison_and_an_unoffered_bonus_keep_their_reason():
    v = Views("en")
    hidden = {**peer(v, "en"), "shown": False, "reason": "group_too_small"}
    draft = template.template_draft([hidden], [], "en", None, "How do I compare with people like me?")
    assert draft["cited"] == [] and "too few people like you" in draft["text"]
    v = Views("en")
    draft = template.template_draft([bonus(v, "en", status="not_offered")], [], "en", None, "How much S-Bonus?")
    assert draft["cited"] == [] and "below the lowest Bonus level" in draft["text"]


@pytest.mark.parametrize("key,lang,text", [
    # #418: above the median by more than the margin, a what-if is offered; at it, "about the same", no
    # number; below it, "that is already your saving", no invitation to change
    ("peers", "en", "You spend 1.2% more than the median of people like you, and a what-if can show what a cut "
                    "would save."),
    ("peers_within_margin", "en", "You spend about the same as the median of people like you."),
    ("peers_same", "en", "You spend about the same as the median of people like you."),
    ("peers_below", "en", "You spend 40.5% less than the median of people like you: that is already your saving."),
    ("peers_below", "fi", "Kulutat 40,5 % vähemmän kuin kaltaistesi mediaani: se on jo säästösi."),
    ("peers", "fi", "Kulutat 1,2 % enemmän kuin kaltaistesi mediaani, ja laskelma näyttää, mitä vähentäminen "
                    "säästäisi."),
])
def test_the_peer_sentence_invites_a_change_only_above_the_median(key, lang, text):
    draft, v, _ = answer(key, lang)
    assert render(draft["text"], v.numbers) == text
    assert not re.search(r"\b(rank|ranking|top|bottom|best|worst|better|worse|winner)\b", text, re.I)


@pytest.mark.parametrize("key,lang,text", [
    ("forecast", "en", "Your balance is forecast to dip to €641.43 on 14 October 2026, before your next payday. "
                       "Bills of €928.50 are due before then."),
    ("forecast", "fi", "Saldosi ennustetaan laskevan 14.10.2026 tasolle 641,43 € ennen seuraavaa palkkapäivää. "
                       "Sitä ennen erääntyy laskuja 928,50 € edestä."),
    ("forecast_below_zero", "en", "Your balance is forecast to turn negative on 9 October 2026 and reach -€120.40 "
                                  "before your next payday. Bills of €928.50 are due before then."),
    ("forecast_no_bills", "en", "Your balance is forecast to dip to €641.43 on 14 October 2026, before your next "
                                "payday. Your balance today is €1,902.64."),
])
def test_the_forecast_says_the_low_point_and_its_date_first(key, lang, text):
    draft, v, _ = answer(key, lang)
    assert render(draft["text"], v.numbers) == text
