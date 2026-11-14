"""The rule answers read like a person wrote them (#342): every template answer of the tools that
core/agent/answer_sentences.py writes, in English and Finnish, passes the validator, and fails this test
on a repeated label, a "label: number; label: number" chain, more than two sentences, more than 35 words
(a number token counts as one word), more than three numbers, a number written in words, a judgement
word or an exclamation mark (Renat's length rule on #342).

The views are built here like the tools build them (Number objects from the one formatter, the tools'
own period labels), with Sanna's values of 2026-09-30, so no database is needed.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pytest

from core.agent import template
from core.agent.validator import allowed_from, render, validate
from core.tools import config
from core.tools.formatting import display
from core.tools.models import Number, Period, Unit
from core.tools.periods import period_label

AS_OF = date(2026, 9, 30)
AUG = (date(2026, 8, 1), date(2026, 8, 31))
SEP = (date(2026, 9, 1), date(2026, 9, 30))
JUL = (date(2026, 7, 1), date(2026, 7, 31))
WINDOW = (date(2026, 4, 1), date(2026, 9, 30))
WEEK = (date(2026, 9, 21), date(2026, 9, 27))
PAYDAY = (date(2026, 10, 1), date(2026, 10, 15))


class Views:
    """Numbers of one answer: ids n1, n2, ... and the Number objects the validator checks against."""

    def __init__(self, language: str) -> None:
        self.language = language
        self.numbers: dict[str, Number] = {}

    def n(self, value, unit: str, span: tuple[date, date], method: str, label: str) -> dict:
        nid = f"n{len(self.numbers) + 1}"
        u = Unit(unit)
        self.numbers[nid] = Number(id=nid, value=value, unit=u, method=method, evidence_ref=f"ev_{nid:0>12}",
                                   period=Period(start=span[0], end=span[1], label=self.label(*span)),
                                   label=label, display=display(Decimal(str(value)), u, self.language, method))
        return {"id": nid, "value": value, "unit": unit, "label": label}

    def label(self, start: date, end: date) -> str:
        return period_label(start, end, self.language)


def fi(lang: str, en: str, fi_: str) -> str:
    return fi_ if lang == "fi" else en


# ---- the answers -----------------------------------------------------------------------------------------

def baskets(v: Views, lang: str, save_more: bool = False) -> list[dict]:
    rows = [("regular_essentials", "Regular essentials", "Säännölliset välttämättömät", 62.7),
            ("unexpected_necessities", "Unexpected necessities", "Odottamattomat välttämättömät", 17.3),
            ("everyday_spending", "Everyday spending", "Arjen kulutus", 19.9)]
    views = []
    if save_more:
        views.append({"tool": "get_safe_to_save", "reason": None,
                      "monthly": v.n(184.61, "eur_per_month", WINDOW, "safe_to_spend.safe_to_save_monthly_eur@1",
                                     fi(lang, "Typically left each month", "Tavallisesti jää kuukaudessa")),
                      "stock": v.n(12272.28, "eur", PAYDAY, "safe_to_spend.safe_to_save_eur@1",
                                   fi(lang, "In your account beyond what you need", "Tililläsi yli tarpeen"))})
    views.append({
        "tool": "get_basket_breakdown", "period": v.label(*WINDOW), "monthly_average": True,
        "total": v.n(3010.59, "eur_per_month", WINDOW, "spender_profile.spend_month_eur@1",
                     fi(lang, "Total spending", "Kulutus yhteensä")),
        "baskets": [{"key": k, "label": fi(lang, en, f_),
                     "share": v.n(s, "percent", WINDOW, "baskets.share_pct@1", fi(lang, "Share of spending",
                                                                                 "Osuus kulutuksesta")),
                     "categories": [{"key": "Restaurants", "label": fi(lang, "Restaurants", "Ravintolat"),
                                     "amount": v.n(224.0, "eur_per_month", WINDOW, "baskets.month_avg_eur@1",
                                                   fi(lang, "Restaurants", "Ravintolat"))}]
                     if k == "everyday_spending" else []}
                    for k, en, f_, s in rows]})
    return views


def spending(v: Views, lang: str, *, label=None, count=46, total=4175.17, span=AUG, compare=None, groups=None,
             direction="out") -> list[dict]:
    label = label or fi(lang, "Spending", "Kulutus")
    view = {"tool": "get_spending", "period": v.label(*span), "direction": direction,
            "total": v.n(total, "eur", span, "spending.total@1", label),
            "tx_count": v.n(count, "count", span, "spending.n_tx@1", fi(lang, "Transactions", "Tapahtumat")),
            "comparison": None, "groups": [], "notes": []}
    if compare:
        base_span, base, change, pct = compare
        b_label = v.label(*base_span)
        change_label = fi(lang, f"Change vs {b_label}", f"Muutos verrattuna: {b_label}")
        view["comparison"] = {
            "label": fi(lang, f"vs {b_label}", f"verrattuna: {b_label}"),
            "baseline": v.n(base, "eur", base_span, "spending.total@1", b_label),
            "change": v.n(change, "eur", span, "spending.change@1", change_label),
            "change_pct": v.n(pct, "percent", span, "spending.change_pct@1", change_label) if pct is not None else None,
            "tone": "worse" if change > 0 else "better"}
    if groups:
        view["groups"] = [{"key": k, "label": lab, "amount": v.n(a, "eur", s, "spending.total@1", lab),
                           "share": None, "change": None, "flags": []} for k, lab, a, s in groups]
    if count == 0:
        view["notes"] = [fi(lang, "No transactions in this period.", "Ei tapahtumia tällä jaksolla.")]
    return [view]


def bills(v: Views, lang: str, notes: bool = False, second_income: bool = False) -> list[dict]:
    view = {
        "tool": "get_recurring_bills", "window": v.label(*WINDOW), "next_payday": "2026-10-15",
        "upcoming_total": v.n(928.5, "eur", PAYDAY, "safe_to_spend.bills_due_eur@1",
                              fi(lang, "Bills before payday", "Laskut ennen palkkapäivää")),
        "bills": [
            {"bill_id": "bill_housing_payment", "label": fi(lang, "Housing", "Asuminen"), "next_expected": "2026-10-03",
             "typical_month": v.n(836.65, "eur_per_month", WINDOW, "recurring.typical_month_eur@1",
                                  fi(lang, "Usual amount", "Tavallinen summa")),
             "due_until_payday": v.n(836.65, "eur", PAYDAY, "safe_to_spend.bill_due_eur@1",
                                     fi(lang, "Due before payday", "Erääntyy ennen palkkapäivää"))},
            {"bill_id": "bill_utilities_payment", "label": fi(lang, "Utilities", "Kodin laskut"), "next_expected": None,
             "typical_month": v.n(186.4, "eur_per_month", WINDOW, "recurring.typical_month_eur@1",
                                  fi(lang, "Usual amount", "Tavallinen summa")),
             "due_until_payday": v.n(91.86, "eur", PAYDAY, "safe_to_spend.bill_due_eur@1",
                                     fi(lang, "Due before payday, pro rata", "Erääntyy ennen palkkapäivää"))}],
        "income": [{"key": "salary", "label": fi(lang, "Salary", "Palkka"), "next_expected": "2026-10-15",
                    "typical_month": v.n(3187.25, "eur_per_month", WINDOW, "recurring.typical_month_eur@1",
                                         fi(lang, "Usual amount", "Tavallinen summa"))}],
        "notes": []}
    if notes:   # the tool's own notes stay on the card: the answer is still two sentences (review of #365)
        view["notes"] = [config.label(config.BILLS_TEXT[k], lang) for k in ("note_sweep", "note_after_payday")]
    if second_income:
        view["income"].append({"key": "other_income", "label": fi(lang, "Other income", "Muut tulot"),
                               "next_expected": None,
                               "typical_month": v.n(412.0, "eur_per_month", WINDOW, "recurring.typical_month_eur@1",
                                                    fi(lang, "Usual amount", "Tavallinen summa"))})
    return [view]


def what_if(v: Views, lang: str, status: str = "estimate") -> list[dict]:
    caveats = [fi(lang, "This is an estimate, not a promise. Prices and habits change.",
                  "Tämä on arvio, ei lupaus. Hinnat ja tottumukset muuttuvat.")]
    if status == "estimate_with_caveat":
        caveats.append(fi(lang, "Part of this is unexpected necessities: needed costs that can only sometimes be "
                                "reduced.", "Osa tästä on odottamattomia välttämättömiä menoja, joita voi vain "
                                            "joskus vähentää."))
    if status == "not_offered":
        caveats.append(fi(lang, "Regular essentials are not cut in a what-if, so there is nothing to cut in this "
                                "selection.", "Säännöllisiä välttämättömiä menoja ei leikata, joten tässä valinnassa ei "
                                              "ole leikattavaa."))
    zero = status == "not_offered"
    return [{"tool": "run_what_if", "selection": {"kind": "category", "value": "Restaurants"}, "status": status,
             "cut_pct": v.n(20, "percent", WINDOW, "user_input@1", fi(lang, "Cut you chose", "Valitsemasi leikkaus")),
             "baseline_per_month": v.n(0.0 if zero else 229.56, "eur_per_month", WINDOW, "what_if.baseline_per_month@1",
                                       fi(lang, "Restaurants in a typical month", "Ravintolat tavallisena kuukautena")),
             "saving_per_month": v.n(0.0 if zero else 45.91, "eur_per_month", WINDOW, "what_if.saving_per_month@1",
                                     fi(lang, "You would save", "Säästäisit")),
             "saving_per_year": v.n(0.0 if zero else 550.95, "eur_per_year", WINDOW, "what_if.saving_per_year@1",
                                    fi(lang, "Per year", "Vuodessa")),
             "caveats": caveats}]


def safe_to_save_zero(v: Views, lang: str) -> list[dict]:
    return [{"tool": "get_safe_to_save",
             "monthly": v.n(0.0, "eur_per_month", WINDOW, "safe_to_spend.safe_to_save_monthly_eur@1",
                            fi(lang, "Typically left each month", "Tavallisesti jää kuukaudessa")),
             "stock": v.n(0.0, "eur", PAYDAY, "safe_to_spend.safe_to_save_eur@1", fi(lang, "Stock", "Varanto")),
             "reason": {"kind": "essentials_exceed_income",
                        "text": fi(lang, "Nothing is left in a typical month: your bills and essentials come to more "
                                         "than your income.", "Tavallisesta kuukaudesta ei jää mitään: laskut ja "
                                                              "välttämättömät menot ylittävät tulosi.")}}]


CASES = {
    "baskets": ("Where did my money go?", lambda v, lang: baskets(v, lang)),
    "save_more": ("How could I save more?", lambda v, lang: baskets(v, lang, save_more=True)),
    "period": ("How much did I spend last month?", lambda v, lang: spending(v, lang)),
    "category": ("How much did I spend on restaurants last month?",
                 lambda v, lang: spending(v, lang, label=fi(lang, "Restaurants", "Ravintolat"), count=10, total=138.94)),
    "compare_up": ("How much did I spend on restaurants in September compared to August?",
                   lambda v, lang: spending(v, lang, label=fi(lang, "Restaurants", "Ravintolat"), total=224.21,
                                            span=SEP, compare=(AUG, 138.94, 85.27, 61.4))),
    "compare_down": ("Did I spend more in September than in August?",
                     lambda v, lang: spending(v, lang, total=2932.54, span=SEP, compare=(AUG, 4175.17, -1242.63, -29.8))),
    "compare_no_pct": ("Restaurants in August compared to July?",
                       lambda v, lang: spending(v, lang, total=10.0, compare=(JUL, 0.0, 10.0, None))),
    "by_category": ("How much did I spend by category last month?",
                    lambda v, lang: spending(v, lang, groups=[
                        ("Housing", fi(lang, "Housing", "Asuminen"), 836.65, AUG),
                        ("Groceries", fi(lang, "Groceries", "Ruokaostokset"), 612.3, AUG),
                        ("other", fi(lang, "Everything else", "Kaikki muu"), 2726.22, AUG)])),
    "by_month": ("How much did I spend each month?",
                 lambda v, lang: spending(v, lang, span=(date(2026, 7, 1), date(2026, 8, 31)), groups=[
                     ("2026-07", v.label(*JUL), 3500.0, JUL), ("2026-08", v.label(*AUG), 4175.17, AUG)])),
    "empty": ("How much did I spend on travel last week?",
              lambda v, lang: spending(v, lang, label=fi(lang, "Travel", "Matkailu"), count=0, total=0.0, span=WEEK)),
    "income": ("How much income did I get last month?",
               lambda v, lang: spending(v, lang, label=fi(lang, "Income", "Tulot"), count=2, total=3187.25,
                                        direction="in")),
    "bills_due": ("Which bills are due before payday?", bills),
    "bills_due_notes": ("Which bills are due before payday?", lambda v, lang: bills(v, lang, notes=True)),
    "payday_two_incomes": ("When is my next payday?", lambda v, lang: bills(v, lang, second_income=True)),
    "count_one": ("How much did I spend on taxis last month?",
                  lambda v, lang: spending(v, lang, label=fi(lang, "Taxi", "Taksi"), count=1, total=52.84)),
    "income_one": ("How much income did I get last month?",
                   lambda v, lang: spending(v, lang, label=fi(lang, "Income", "Tulot"), count=1, total=3187.25,
                                            direction="in")),
    "bills_regular": ("What are my regular monthly bills?", bills),
    "payday": ("When is my next payday?", bills),
    "what_if": ("What if I cut restaurants by 20%?", what_if),
    "what_if_caveat": ("What if I cut unexpected necessities by 20%?",
                       lambda v, lang: what_if(v, lang, "estimate_with_caveat")),
    "what_if_not_offered": ("What if I cut my housing by 20%?", lambda v, lang: what_if(v, lang, "not_offered")),
    "save_more_zero": ("How could I save more?", safe_to_save_zero),
}
FI_QUESTIONS = {"baskets": "Mihin rahani menivät?", "save_more": "Miten voisin säästää enemmän?",
                "save_more_zero": "Miten voisin säästää enemmän?", "bills_due": "Mitä laskuja on tulossa ennen palkkapäivää?",
                "bills_due_notes": "Mitä laskuja on tulossa ennen palkkapäivää?",
                "payday_two_incomes": "Milloin on seuraava palkkapäiväni?",
                "bills_regular": "Mitkä ovat säännölliset kuukausittaiset laskuni?",
                "payday": "Milloin on seuraava palkkapäiväni?"}

# Cardinals, ordinals and fractions, English and Finnish in their case forms (review of #365).
NUMBER_WORDS = re.compile(
    r"\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|hundred|thousand|million|"
    r"first|second|third|fourth|fifth|half|halves|quarter|twice|"
    r"yksi|yhde\w*|yhtä|kaksi|kahde\w*|kahta|kahte\w*|kolm\w*|nelj\w*|viisi|viide\w*|viitt\w*|viite\w*|kuusi|kuude\w*|"
    r"kuutt\w*|seitsem\w*|kahdeks\w*|yhdeks\w*|kymmen\w*|sata\w*|sado\w*|tuha\w*|miljoon\w*|ensimmäi\w*|toinen|"
    r"toise\w*|puol\w*|neljännes\w*)\b", re.I)
JUDGEMENT = re.compile(r"too much|too many|\bbad\b|\bwaste|overspend|liikaa|huono|tuhla", re.I)
CHAIN = re.compile(r"[^.;:!?]+: \{\{n\d+\}\}\s*;")      # "label: {{n1}};"
LABEL_BEFORE_TOKEN = re.compile(r"([A-ZÄÖÅa-zäöå][^.;:!?]*?): \{\{n\d+\}\}")
SENTENCE_END = re.compile(r"[.?](?=\s+[A-ZÄÖÅ]|\s*$)")


def answer(key: str, lang: str):
    question, build = CASES[key]
    question = FI_QUESTIONS.get(key, question) if lang == "fi" else question
    v = Views(lang)
    views = build(v, lang)
    draft = template.template_draft(views, [], lang, None, question)
    return draft, v, views, question


@pytest.mark.parametrize("lang", ["en", "fi"])
@pytest.mark.parametrize("key", sorted(CASES))
def test_every_rule_answer_reads_like_a_person_and_passes_the_validator(key, lang):
    draft, v, views, _ = answer(key, lang)
    text = draft["text"]
    _, errors = validate(draft, language=lang, numbers=v.numbers,
                         allowed=allowed_from(v.numbers.values(), views, AS_OF))
    assert errors == [], (text, errors)
    tokens = re.findall(r"\{\{(n\d+)\}\}", text)
    sentences = [s for s in SENTENCE_END.split(text) if s.strip()]
    labels = [m.strip().lower() for m in LABEL_BEFORE_TOKEN.findall(text)]
    assert not CHAIN.search(text), text                                  # no "label: number; label: number"
    assert len(labels) == len(set(labels)), text                         # no label twice
    assert len(set(sentences)) == len(sentences), text                    # no sentence twice
    assert "!" not in text and not NUMBER_WORDS.search(text) and not JUDGEMENT.search(text), text
    assert 1 <= len(sentences) <= 2, text                                 # the whole answer
    assert len(re.sub(r"\{\{n\d+\}\}", "N", text).split()) <= 35, text      # a token is one word
    assert len(tokens) <= 3 and len(set(tokens)) == len(tokens), text
    assert "; " not in render(text, v.numbers).replace("(", "").replace(")", ""), text   # no semicolon lists


def test_a_change_is_said_in_words_with_the_old_number_once():
    up, v, _, _ = answer("compare_up", "en")
    assert render(up["text"], v.numbers) == ("You spent €224.21 on restaurants in September 2026, up from €138.94 "
                                             "in August 2026 (61.4%).")
    down, v, _, _ = answer("compare_down", "en")
    assert render(down["text"], v.numbers) == ("You spent €2,932.54 in September 2026, down from €4,175.17 in "
                                               "August 2026 (-29.8%).")
    down_fi, v, _, _ = answer("compare_down", "fi")
    assert render(down_fi["text"], v.numbers) == ("Syyskuussa 2026 käytit 2 932,54 €, vähemmän kuin elokuussa 2026 "
                                                  "(4 175,17 €, muutos -29,8 %).")
    no_pct, v, _, _ = answer("compare_no_pct", "en")
    assert render(no_pct["text"], v.numbers) == "You spent €10.00 in August 2026, up from €0.00 in July 2026."


def test_a_count_of_one_is_singular_and_notes_stay_on_the_card():
    one, v, _, _ = answer("count_one", "en")
    assert render(one["text"], v.numbers) == "You spent €52.84 on taxi in August 2026, in 1 transaction."
    one_fi, v, _, _ = answer("count_one", "fi")
    assert render(one_fi["text"], v.numbers) == "Elokuussa 2026 käytit 52,84 € luokassa Taksi ja tapahtumien määrä oli 1."
    pay, v, _, _ = answer("income_one", "en")
    assert render(pay["text"], v.numbers).endswith(", in 1 payment.")
    with_notes, v, _, _ = answer("bills_due_notes", "en")
    assert render(with_notes["text"], v.numbers) == ("Bills of €928.50 are due before your payday, including €836.65 "
                                                     "for housing and €91.86 for utilities.")
    two, v, _, _ = answer("payday_two_incomes", "fi")
    assert render(two["text"], v.numbers) == "Palkkasi on tavallisesti 3 187,25 € / kk, ja seuraava palkkapäiväsi on 15.10.2026."


def test_the_takeaway_comes_first():
    for key, start in [("baskets", "Most of your spending"), ("what_if", "That cut would save you"),
                       ("bills_due", "Bills of"), ("payday", "Your salary is usually"), ("period", "You spent")]:
        draft, *_ = answer(key, "en")
        assert draft["text"].startswith(start), (key, draft["text"])


def test_an_empty_period_states_its_zeros_once_and_no_repeated_note():
    draft, v, _, _ = answer("empty", "en")
    assert render(draft["text"], v.numbers) == "There were 0 transactions for travel during 21–27 Sep 2026, so you spent €0.00."
    draft, v, _, _ = answer("empty", "fi")
    assert render(draft["text"], v.numbers) == ("Jaksolla 21.–27.9.2026 luokassa Matkailu oli 0 tapahtumaa, joten "
                                                "käytit 0,00 €.")


def test_lead_persona_texts():
    """The texts the PR table shows for CUST00860, rendered."""
    expected = {
        ("baskets", "en"): "Most of your spending, 62.7%, went to regular essentials. Everyday spending took 19.9% and "
                           "unexpected necessities 17.3%.",
        ("compare_down", "en"): "You spent €2,932.54 in September 2026, down from €4,175.17 in August 2026 (-29.8%).",
        ("bills_due", "en"): "Bills of €928.50 are due before your payday, including €836.65 for housing and €91.86 for "
                             "utilities.",
        ("payday", "en"): "Your salary is usually €3,187.25 a month, and your next payday is 15 October 2026.",
        ("save_more", "en"): "You can typically put aside €184.61 a month. Tell me how much you would cut restaurants by, "
                             "and I'll show what you'd save.",
        ("save_more_zero", "fi"): "Tavallisesta kuukaudesta ei jää mitään: laskut ja välttämättömät menot ylittävät "
                                  "tulosi.",
        ("what_if_caveat", "en"): "That cut would save you €45.91 a month, or €550.95 a year. Part of this is unexpected "
                                  "necessities: needed costs that can only sometimes be reduced.",
        ("what_if", "fi"): "Tämä leikkaus säästäisi sinulle 45,91 € / kk eli 550,95 € / v. "
                           "Nyt käytät 229,56 € / kk luokassa Ravintolat.",
        ("payday", "fi"): "Palkkasi on tavallisesti 3 187,25 € / kk, ja seuraava palkkapäiväsi on 15.10.2026.",
    }
    for (key, lang), text in expected.items():
        draft, v, _, _ = answer(key, lang)
        assert render(draft["text"], v.numbers) == text
