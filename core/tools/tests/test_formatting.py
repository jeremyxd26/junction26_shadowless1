"""The formatter is the one source of every display string (issue #111, closes #93)."""

from __future__ import annotations

import ast
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from core.tools.formatting import display, ordinal_en
from core.tools.models import Unit

VS_MEDIAN = "peer_benchmark.vs_median_pct@1"
TX_MONTH = "spender_profile.everyday_tx_month@1"
USER_INPUT = "user_input@1"


# value, unit, method, English, Finnish: one row per form of the issue's table, plus what stays as it was
FORMS = [
    # unchanged: money, rates, percentages with one decimal
    ("1234.5", Unit.EUR, None, "€1,234.50", "1 234,50 €"),
    ("1180.21", Unit.EUR_PER_MONTH, None, "€1,180.21 a month", "1 180,21 € / kk"),
    ("-24.5", Unit.EUR, None, "-€24.50", "-24,50 €"),
    ("18.95", Unit.PERCENT, None, "19.0%", "19,0 %"),
    ("-3.25", Unit.PERCENT, "spending.change_pct@1", "-3.3%", "-3,3 %"),
    # percentile: rounded to a whole number, an ordinal
    ("72", Unit.PERCENTILE, "peer_benchmark.percentile@1", "72nd percentile", "72. persentiili"),
    ("50.5", Unit.PERCENTILE, None, "51st percentile", "51. persentiili"),
    # the peer comparison: the magnitude with a direction word, no minus; exactly zero is 0.0%
    ("32.3", Unit.PERCENT, VS_MEDIAN, "32.3% more", "32,3 % enemmän"),
    ("-31", Unit.PERCENT, VS_MEDIAN, "31.0% less", "31,0 % vähemmän"),
    ("0", Unit.PERCENT, VS_MEDIAN, "0.0%", "0,0 %"),
    ("-0.04", Unit.PERCENT, VS_MEDIAN, "0.0%", "0,0 %"),
    # counts: whole as an integer, a fraction with one decimal (half up)
    ("118", Unit.COUNT, None, "118", "118"),
    ("4120", Unit.COUNT, "store_price_index.n_visits@1", "4,120", "4 120"),   # grouped, as card.stores shows
    ("1234.56", Unit.COUNT, None, "1,234.6", "1 234,6"),
    ("15.25", Unit.COUNT, None, "15.3", "15,3"),
    ("15.2", Unit.COUNT, "spending.n_tx@1", "15.2", "15,2"),
    # everyday purchases a month
    ("14.2", Unit.COUNT, TX_MONTH, "14.2 a month", "14,2 / kk"),
    ("14", Unit.COUNT, TX_MONTH, "14 a month", "14 / kk"),
    # days and months: singular in English for 1
    ("1", Unit.DAYS, None, "1 day", "1 pv"),
    ("12", Unit.DAYS, None, "12 days", "12 pv"),
    ("1", Unit.MONTHS, None, "1 month", "1 kk"),
    ("3", Unit.MONTHS, None, "3 months", "3 kk"),
    # a percentage the user typed, whole: no decimal; any other percentage keeps its decimal
    ("20", Unit.PERCENT, USER_INPUT, "20%", "20 %"),
    ("20.5", Unit.PERCENT, USER_INPUT, "20.5%", "20,5 %"),
    ("20", Unit.PERCENT, None, "20.0%", "20,0 %"),
]


@pytest.mark.parametrize("value, unit, method, en, fi", FORMS)
def test_every_form_in_both_languages(value, unit, method, en, fi):
    assert display(Decimal(value), unit, "en", method) == en
    assert display(Decimal(value), unit, "fi", method) == fi


@pytest.mark.parametrize("n, text", [
    (1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (12, "12th"), (13, "13th"),
    (21, "21st"), (22, "22nd"), (23, "23rd"), (100, "100th"), (101, "101st"), (111, "111th"), (112, "112th"),
])
def test_english_ordinals(n, text):
    assert ordinal_en(n) == text
    assert display(Decimal(n), Unit.PERCENTILE) == f"{text} percentile"


@pytest.mark.parametrize("value, unit, method, en, fi", [
    ("-0.001", Unit.EUR, None, "€0.00", "0,00 €"),
    ("-0.004", Unit.EUR_PER_MONTH, None, "€0.00 a month", "0,00 € / kk"),
    ("-0.04", Unit.PERCENT, None, "0.0%", "0,0 %"),
    ("-0.0", Unit.PERCENT, USER_INPUT, "0%", "0 %"),
    ("-0.04", Unit.COUNT, None, "0.0", "0,0"),
    ("-0.4", Unit.PERCENTILE, None, "0th percentile", "0. persentiili"),
    ("-0.005", Unit.EUR, None, "-€0.01", "-0,01 €"),   # rounds away from zero: a real minus
])
def test_no_negative_zero(value, unit, method, en, fi):
    """#93: a value that rounds to zero never shows a minus."""
    assert display(Decimal(value), unit, "en", method) == en
    assert display(Decimal(value), unit, "fi", method) == fi


CONTRACT = Path(__file__).resolve().parents[3] / "contracts" / "api.md"
EXAMPLE = re.compile(r"<!-- example: ([\w.]+) -->\s*```json\n(.*?)\n```", re.S)


def _numbers(obj, path="$"):
    if isinstance(obj, dict):
        if {"value", "unit", "method", "display"} <= set(obj):
            yield path, obj
        for k, v in obj.items():
            yield from _numbers(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _numbers(v, f"{path}[{i}]")


def test_every_display_in_the_contract_examples_is_the_formatters():
    """Every Number object in contracts/api.md: its display is what the formatter writes for its value,
    unit and method, in the example's language."""
    checked, wrong = 0, []
    for name, body in EXAMPLE.findall(CONTRACT.read_text(encoding="utf-8")):
        data = json.loads(body)
        for path, n in _numbers(data):
            got = {lang: display(Decimal(str(n["value"])), Unit(n["unit"]), lang, n["method"]) for lang in ("en", "fi")}
            checked += 1
            if n["display"] not in got.values():
                wrong.append((name, path, n["display"], got))
    assert checked > 100 and wrong == []


def test_no_plus_sign_ever():
    for value, unit, method, *_ in FORMS:
        for language in ("en", "fi"):
            assert "+" not in display(abs(Decimal(value)), unit, language, method)


# ---- no display string is built by hand -----------------------------------------------------------
# Every `display=` keyword, `"display":` dict entry and `.display =` assignment in the service code
# (core/tools and core/app) must be a call of the formatter, `display(...)`. The tools build their
# Numbers through NumberBuilder.number, which always calls it.

ROOT = Path(__file__).resolve().parents[2]
SOURCES = sorted(p for d in ("tools", "app") for p in (ROOT / d).rglob("*.py") if "tests" not in p.parts)


def _is_formatter_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return (isinstance(f, ast.Name) and f.id == "display") or (isinstance(f, ast.Attribute) and f.attr == "display")


def hand_built_displays(source: str, name: str) -> list[str]:
    out = []
    for node in ast.walk(ast.parse(source)):
        values = []
        if isinstance(node, ast.Call):
            values += [k.value for k in node.keywords if k.arg == "display"]
        elif isinstance(node, ast.Dict):
            values += [v for k, v in zip(node.keys, node.values)
                       if isinstance(k, ast.Constant) and k.value == "display"]
        elif isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Attribute) and t.attr == "display" for t in node.targets):
                values.append(node.value)
        out += [f"{name}:{v.lineno}" for v in values if not _is_formatter_call(v)]
    return out


def test_no_display_is_built_by_hand():
    assert len(SOURCES) > 10
    found = [x for p in SOURCES for x in hand_built_displays(p.read_text(encoding="utf-8"), p.relative_to(ROOT).as_posix())]
    assert found == [], f"build these displays with core.tools.formatting.display(value, unit, language, method): {found}"


def test_the_check_finds_a_hand_built_display():
    bad = 'Number(value=20, display=f"{pct}%")\nx = {"display": "20%"}\nn.display = str(v)\n'
    good = 'Number(value=20, display=display(v, Unit.PERCENT, lang, method))\nx = {"display": formatting.display(v, u)}\n'
    assert sorted(hand_built_displays(bad, "bad.py")) == ["bad.py:1", "bad.py:2", "bad.py:3"]
    assert hand_built_displays(good, "good.py") == []
