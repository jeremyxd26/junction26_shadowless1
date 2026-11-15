"""The spoken script /api/tts reads aloud (#811 follow-up), on the demo answers as the stand wrote them.

The fixture holds real audit records of the lead persona's demo questions (synthetic data): `text` with
its `{{nK}}` tokens, the declared numbers (value, unit, method) and the tools' model views. No model call.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.agent.spoken import MAX_SPOKEN, spoken_number, spoken_script

FIXTURE = Path(__file__).parent / "fixtures" / "spoken_answers.json"
RECORDS = json.loads(FIXTURE.read_text(encoding="utf-8"))


def record(question: str, language: str) -> dict:
    return next(r for r in RECORDS if r["question"] == question and r["language"]["resolved"] == language)


@pytest.mark.parametrize(("question", "language", "script"), [
    ("How could I save more?", "en",
     "Cutting back on restaurants and lifestyle could save you about 63 euros a month. That comes on top of "
     "your savings goal of 360 euros a month. That's from your spending in recent months."),
    ("Moi, voitko auttaa mua säästää rahaa?", "fi",
     "Ravintoloiden ja ostosten ja vapaa-ajan vähentäminen säästäisi noin 63 euroa kuukaudessa. Se tulee "
     "säästötavoitteesi 360 euroa kuukaudessa lisäksi. Laskin tämän viime kuukausien kulutuksestasi."),
    ("Mihin rahani menivät?", "fi",
     "Käytit keskimäärin noin 3010 euroa kuukaudessa. Suurin kuluerä olivat säännölliset välttämättömät noin "
     "1890 euroa kuukaudessa. Laskin tämän kulutuksestasi huhtikuusta syyskuuhun."),
    ("What can I safely spend this week?", "en",
     "For the next seven days, you can safely spend about 139 euros, after setting aside 360 euros a month "
     "first. That's from your balance, your bills and your usual spending."),
    ("Where did my money go in September?", "en",
     "In September 2026 your total spending was about 2,930 euros a month. Your largest share was Regular "
     "essentials at about 1,340 euros a month. That's from your spending in September."),
    ("Mitä jos käyttäisin 20 % vähemmän ravintoloihin?", "fi",
     "Jos vähentäisit ravintolakuluja 20 prosenttia, säästäisit noin 46 euroa kuukaudessa. Tämä on arvio, joka "
     "perustuu menneisiin kuukausiin. Laskin tämän viime kuukausien kulutuksestasi."),
    ("Mitkä ovat säännölliset kuukausilaskuni?", "fi",
     "Seuraava palkkapäivä on 15. lokakuuta. Ennen sitä erääntyvät laskut ovat yhteensä noin 929 euroa. "
     "Laskin tämän saldostasi, laskuistasi ja tavallisesta kulutuksestasi."),
    ("What kind of spender am I?", "en",
     "Your spending profile is Big ticket, with a large one-off purchase standing out. You spend 1.2 percent "
     "more than the median of people like you, and a what-if can show what a cut would save. That's from "
     "your spending from April to September."),
])
def test_demo_answers_read_as_spoken_scripts(question, language, script):
    assert spoken_script(record(question, language)) == script


@pytest.mark.parametrize("rec", RECORDS, ids=lambda r: f"{r['language']['resolved']}:{r['question'][:30]}")
def test_no_unit_marks_links_or_tokens_and_at_most_two_numbers(rec):
    script = spoken_script(rec)
    assert script
    assert "{{" not in script and "http" not in script and "**" not in script
    if re.search(r"\{\{n\d+\}\}", rec["text"] or ""):
        assert "€" not in script and "/ kk" not in script and "/ v" not in script and " %" not in script
        spoken = re.findall(r"\b(?:euros?|euroa|prosenttia|percent|senttiä|cents)\b", script)
        assert 1 <= len(spoken) <= MAX_SPOKEN
        assert script.endswith(("spending.", "September.", "months.", "kulutuksestasi.", "syyskuuhun."))


def test_answers_without_numbers_are_read_as_written_without_links():
    kb = spoken_script(record("Miten otan yhteyttä S-Pankkiin?", "fi"))
    assert "https://" not in kb and kb.endswith("S-Pankin julkisilta ohjesivuilta.")
    assert spoken_script(record("Should I buy stocks?", "en")) == record("Should I buy stocks?", "en")["text_rendered"]


@pytest.mark.parametrize(("number", "en", "fi"), [
    ({"value": 63.17, "unit": "eur_per_month"}, "about 63 euros a month", "noin 63 euroa kuukaudessa"),
    ({"value": 360.0, "unit": "eur_per_month"}, "360 euros a month", "360 euroa kuukaudessa"),
    ({"value": 758.04, "unit": "eur_per_year"}, "about 758 euros a year", "noin 758 euroa vuodessa"),
    ({"value": 137.8, "unit": "eur_per_week"}, "about 138 euros a week", "noin 138 euroa viikossa"),
    ({"value": 12.4, "unit": "eur_per_day"}, "about 12 euros a day", "noin 12 euroa päivässä"),
    ({"value": 14276.35, "unit": "eur"}, "about 14,300 euros", "noin 14300 euroa"),
    ({"value": 1.0, "unit": "eur"}, "1 euro", "1 euro"),
    ({"value": 0.45, "unit": "eur"}, "45 cents", "45 senttiä"),
    ({"value": -20.5, "unit": "eur"}, "minus about 21 euros", "miinus noin 21 euroa"),
    ({"value": 62.7, "unit": "percent"}, "about 63 percent", "noin 63 prosenttia"),
    ({"value": 20, "unit": "percent", "method": "user_input@1"}, "20 percent", "20 prosenttia"),
    ({"value": 1.2, "unit": "percent", "method": "peer_benchmark.vs_median_pct@1"}, "1.2 percent more", "1,2 prosenttia enemmän"),
    ({"value": -31.0, "unit": "percent", "method": "peer_benchmark.vs_median_pct@1"}, "31 percent less", "31 prosenttia vähemmän"),
    ({"value": 72, "unit": "percentile"}, "72nd percentile", "72. persentiili"),
    ({"value": 14.2, "unit": "count", "method": "spender_profile.everyday_tx_month@1"}, "14.2 a month", "14,2 kuukaudessa"),
    ({"value": 12, "unit": "days"}, "12 days", "12 päivää"),
    ({"value": 1, "unit": "months"}, "1 month", "1 kuukausi"),
])
def test_spoken_number_forms(number, en, fi):
    assert spoken_number(number, "en") == en
    assert spoken_number(number, "fi") == fi


def test_a_record_it_cannot_read_falls_back_to_the_screen_text():
    base = {"language": {"resolved": "en"}, "text_rendered": "You spent €10.00.", "text": "You spent {{n1}}."}
    assert spoken_script({**base, "numbers": {}}) == "You spent €10.00."              # no Number for the token
    assert spoken_script({**base, "numbers": {"n1": {"value": "x", "unit": "eur"}}}) == "You spent €10.00."
    assert spoken_script({**base, "numbers": {"n1": {"value": 10, "unit": "eur"}}}) == (
        "You spent 10 euros. That's from your spending in recent months.")


def test_a_third_number_goes_with_its_clause_and_a_sentence_that_starts_with_it_goes_whole():
    numbers = {k: {"value": v, "unit": "eur"} for k, v in (("n1", 10), ("n2", 20), ("n3", 30), ("n4", 40))}
    rec = {"language": {"resolved": "en"}, "numbers": numbers, "text_rendered": "x",
           "text": "You spent {{n1}} on food and {{n2}} on taxis, which is {{n3}} in all. {{n4}} went to rent. Fine."}
    assert spoken_script(rec) == ("You spent 10 euros on food and 20 euros on taxis. Fine. "
                                  "That's from your spending in recent months.")
