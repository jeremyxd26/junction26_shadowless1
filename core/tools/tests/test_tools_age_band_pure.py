"""#883: the customer's age band in the whole synthetic dataset beside the peer comparison of total spending. The band
mapping, the hiding of bands under 30 people, the answer's line in English and Finnish (personal figure first, then
the band's median: context, not a target) within the digit and length rules, and the evidence view's label and parts.
No database and no network."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from core import answer_text
from core.agent import answer_sentences
from core.app.api import evidence as evidence_api
from core.app.api import texts
from core.tools import config
from core.tools.peer import age_band_for, band_shown

SQL = Path(__file__).resolve().parents[2] / "metrics" / config.AGE_BAND_FILE


@pytest.mark.parametrize("age,band", [
    (18, "18-24"), (24, "18-24"), (25, "25-34"), (34, "25-34"), (35, "35-44"), (44, "35-44"), (45, "45-54"),
    (54, "45-54"), (55, "55-64"), (64, "55-64"), (65, "65+"), (74, "65+"), (75, "65+"), (99, "65+"),
])
def test_every_age_falls_in_its_band(age, band):
    assert age_band_for(age) == band


def test_no_band_without_an_age_or_under_eighteen():
    assert age_band_for(None) is None and age_band_for(17) is None


def test_the_sql_file_has_the_same_bands_as_the_module():
    values = re.findall(r"\('([0-9+-]+)', (\d+), (\d+|NULL), \d\)", SQL.read_text(encoding="utf-8"))
    assert [(b, int(f), None if t == "NULL" else int(t)) for b, f, t in values] == list(config.AGE_BANDS)


def test_a_band_under_thirty_people_is_hidden():
    assert config.AGE_BAND_MIN_N == "30"
    assert band_shown(30) and band_shown(1616)
    assert not band_shown(29) and not band_shown(0)
    assert band_shown(5, min_n=5) and not band_shown(4, min_n=5)


def test_the_sql_file_hides_small_bands_and_reads_no_transactions():
    sql = SQL.read_text(encoding="utf-8")
    assert "app.band_min_n" in sql and "'30'" in sql
    assert sql.count("CASE WHEN bs.cohort_size >= p.min_n THEN round(") == 4   # every median, none when hidden
    assert not re.search(r"\bFROM\s+transactions\b|\bJOIN\s+transactions\b", sql, re.I)   # the marts only
    assert "statement_timeout" in sql


def view(language: str, metric: str = "spend_total", band: bool = True, shown: bool = True) -> dict:
    v = {"tool": "get_peer_benchmark", "metric": metric, "shown": shown, "offers_cut": True,
         "metric_label": "Total spending" if language == "en" else "Kulutus yhteensä",
         "you": {"id": "n1", "value": 3010.59, "unit": "eur_per_month", "label": "x"},
         "vs_median": {"id": "n5", "value": 1.2, "unit": "percent", "label": "x"}}
    if band:
        v["age_band"] = {"cohort_size": {"id": "n7", "value": 1616, "unit": "count", "label": "x"},
                         "median": {"id": "n11", "value": 2776.54, "unit": "eur_per_month", "label": "x"},
                         "measure": "ordinary_spending", "period": "1 Apr – 30 Sep 2026", "dataset": "synthetic",
                         "context_only": True}
    return v


def ok(text, **kw):
    return True


@pytest.mark.parametrize("language,first,second", [
    ("en", "You spend {{n1}}.",
     "In this synthetic dataset of {{n7}} people your age, the median is {{n11}}: context, not a target."),
    ("fi", "Kulutat {{n1}}.",
     "Tässä synteettisessä aineistossa ikäryhmäsi {{n7}} ihmisen mediaani on {{n11}}: taustatietoa, ei tavoite."),
])
def test_the_personal_figure_comes_first_then_the_band_median(language, first, second):
    sentences, ids = answer_sentences.peer(view(language), language, ok)
    assert sentences == [first, second] and ids == ["n1", "n7", "n11"]
    assert answer_text.length_problems(" ".join(sentences), len(ids), kind="template") == []


@pytest.mark.parametrize("language", ["en", "fi"])
def test_without_a_band_the_answer_is_the_comparison_as_before(language):
    plain = answer_sentences.peer(view(language, band=False), language, ok)
    assert plain is not None and plain[1] == ["n5"]          # the difference from the group median, as on dev


def test_the_band_line_is_only_for_total_spending_and_a_shown_comparison():
    assert answer_sentences.peer(view("en", metric="everyday_spending"), "en", ok)[1] == ["n5"]
    assert answer_sentences.peer(view("en", shown=False), "en", ok) is None


def test_no_digit_in_the_line_or_the_number_labels():
    # the digit rule (R1): only Numbers and returned periods carry digits, so the band is "people your age"
    for pair in answer_sentences.AGE_BAND:
        for text in pair:
            assert not re.search(r"\d", text), text
    for key in ("age_band_median", "age_band_cohort", "ordinary_spending"):
        for text in config.PEER_TEXT[key]:
            assert not re.search(r"\d", text), text
    for method in (config.METHODS["age_band_median"], config.METHODS["age_band_cohort"]):
        info = texts.METHODS[method]
        assert all(not re.search(r"\d", t) for t in (*info.name, *info.summary)), method
        assert "synthetic" in info.summary[0] and "synteettisessä" in info.summary[1]


def spec(method: str, measure: str | None = "ordinary_spending") -> dict:
    params = {"period": {"start": "2026-04-01", "end": "2026-09-30"}, "band": "35-44", "cohort_size": "1616"}
    if measure:
        params["measure"] = measure
    return {"v": 1, "kind": "metric", "customer_id": "CUST00860", "as_of": "2026-09-30", "method": method,
            "source": {"file": config.AGE_BAND_FILE, "column": "median_ordinary_spending_month_eur",
                       "settings": {"band_min_n": "30"}},
            "value": "2776.54", "params": params}


@pytest.mark.parametrize("language,title", [
    ("en", "People aged 35–44 in the synthetic dataset: ordinary spending, median"),
    ("fi", "35–44-vuotiaat synteettisessä aineistossa: tavallinen kulutus, mediaani"),
])
def test_the_evidence_view_names_the_band_the_measure_and_the_period(language, title):
    number = evidence_api.number_from_spec("ev_x", spec(config.METHODS["age_band_median"]), language, lambda r: {})
    assert number["label"] == title and number["unit"] == "eur_per_month"
    assert number["period"]["start"] == date(2026, 4, 1) and number["period"]["end"] == date(2026, 9, 30)
    parts = evidence_api._age_band_parts(spec(config.METHODS["age_band_median"]), number["period"], language)
    assert [p["role"] for p in parts] == ["cohort_size"] and parts[0]["number"]["value"] == 1616
    assert parts[0]["number"]["evidence_ref"] is None and parts[0]["number"]["unit"] == "count"


def test_the_evidence_view_of_the_band_size_names_the_band():
    number = evidence_api.number_from_spec("ev_x", spec(config.METHODS["age_band_cohort"], None), "en", lambda r: {})
    assert number["label"] == "People aged 35–44 in the synthetic dataset" and number["unit"] == "count"


def test_the_age_band_file_may_be_re_run_as_evidence():
    assert config.AGE_BAND_FILE in config.METRIC_EVIDENCE_FILES
    assert evidence_api.METRIC_SECTIONS[config.AGE_BAND_FILE] == "#6-peer-benchmark"
