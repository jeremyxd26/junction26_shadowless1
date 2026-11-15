"""#569: the national context file (Statistics Finland's household budget survey) parses, holds every kept category
for every age group the personas fall in, and nothing fetches it at run time. No database and no network."""

from __future__ import annotations

import ast
import socket
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from core.tools import national

ROOT = Path(__file__).resolve().parents[3]
PERSONA_BANDS = {"CUST00860": "35-44", "CUST00493": "45-54", "CUST00387": "18-24", "CUST00849": "25-34"}


def test_the_file_parses_and_says_where_it_comes_from():
    doc = yaml.safe_load((ROOT / national.CONFIG_PATH).read_text(encoding="utf-8"))
    for key in ("source", "table_id", "survey_year", "unit", "retrieved", "api", "query", "license", "attribution",
                "monthly_rule"):
        assert doc.get(key), key
    assert doc["table_id"] == "StatFin/ktutk/14q4.px" and doc["survey_year"] == 2022
    assert doc["license"] == "CC BY 4.0" and "Statistics Finland" in doc["attribution"]
    assert "consumption unit" in doc["unit"] and doc["monthly_rule"].startswith("monthly = yearly / 12")


def test_the_kept_categories_are_groceries_and_transportation_and_never_health_or_housing():
    # the check of #569 dropped Restaurants (a persona at 2.63 times the table); health and housing never compare
    assert set(national.RULES.monthly) == {"Groceries", "Transportation"}
    for category in ("Restaurants", "Health", "Housing", "Travel"):
        assert national.figure(category, "35-44") is None


@pytest.mark.parametrize("customer,band", sorted(PERSONA_BANDS.items()))
@pytest.mark.parametrize("category", ["Groceries", "Transportation"])
def test_every_kept_category_has_the_age_group_of_every_persona(customer, band, category):
    f = national.figure(category, band)
    # 18-24 lies inside the table's own 17-24 (national_context.yaml), the other bands are the table's
    assert f is not None and f.age_group == {"18-24": "17-24"}.get(band, band) and f.survey_year == 2022 and f.monthly > 0
    assert f.monthly == (Decimal(f.yearly) / 12).quantize(Decimal("0.01"))


def test_the_age_groups_are_the_tables_own_and_75_plus_gets_none():
    assert national.figure("Groceries", "18-24").age_group == "17-24"   # the line names the table's band
    assert national.figure("Groceries", "75+") is None and national.figure("Groceries", None) is None
    assert national.figure("Groceries", "35-44").monthly == Decimal("332.33")
    assert national.figure("Transportation", "35-44").monthly == Decimal("187.17")   # 3913 - 1667 a year, / 12


def test_the_evidence_params_cite_the_table_not_transactions():
    p = national.figure("Groceries", "25-34").params()
    assert p["value"] == "291.75" and p["table"] == "StatFin/ktutk/14q4.px" and p["survey_year"] == 2022
    assert p["age_group"] == "25-34" and "consumption unit" in p["unit"] and "Statistics Finland" in p["source"]
    assert p["config"] == national.CONFIG_PATH and p["rule"] == "categories.Groceries.monthly.25-34"


@pytest.mark.parametrize("change,error", [
    (lambda d: d["categories"]["Groceries"]["monthly"].update({"35-44": "333.00"}), "yearly value / 12"),
    (lambda d: d["categories"]["Groceries"]["monthly"].pop("35-44"), "lacks an age group"),
    (lambda d: d["categories"].update({"Housing": d["categories"]["Groceries"]}), "never compared"),
    (lambda d: d.pop("survey_year"), "survey_year"),
])
def test_a_malformed_file_stops_the_load(tmp_path, change, error):
    doc = yaml.safe_load((ROOT / national.CONFIG_PATH).read_text(encoding="utf-8"))
    change(doc)
    path = tmp_path / "national_context.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        national.load(path)


def test_nothing_fetches_the_table_at_run_time(monkeypatch):
    # the module imports no network library, and loading and reading it work with every socket refused
    tree = ast.parse((ROOT / "core/tools/national.py").read_text(encoding="utf-8"))
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | \
        {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not imported & {"urllib", "http", "requests", "httpx", "socket", "aiohttp", "urllib3"}

    def refuse(*args, **kwargs):
        raise AssertionError("a network connection was attempted")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert national.load().survey_year == 2022 and national.figure("Groceries", "45-54").monthly == Decimal("345.58")
    # and no module of core/ names the statistics API (the host is built from parts so this file does not)
    host = "pxdata" + ".stat.fi"
    hits = [p for p in (ROOT / "core").rglob("*.py") if host in p.read_text(encoding="utf-8")]
    assert hits == []
