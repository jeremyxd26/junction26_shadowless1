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
    # #161: days and months round half up to a whole number (not truncated) and group thousands
    ("2.4", Unit.DAYS, None, "2 days", "2 pv"),
    ("2.5", Unit.DAYS, None, "3 days", "3 pv"),
    ("2.6", Unit.DAYS, None, "3 days", "3 pv"),
    ("1.4", Unit.DAYS, None, "1 day", "1 pv"),        # rounds to 1: singular
    ("0.6", Unit.MONTHS, None, "1 month", "1 kk"),
    ("5.5", Unit.MONTHS, None, "6 months", "6 kk"),
    ("1234", Unit.DAYS, None, "1,234 days", "1 234 pv"),
    ("1234.5", Unit.MONTHS, None, "1,235 months", "1 235 kk"),
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
    if n <= 100:   # a percentile above 100 is refused (test_a_percentile_outside_0_to_100_is_refused)
        assert display(Decimal(n), Unit.PERCENTILE) == f"{text} percentile"


@pytest.mark.parametrize("value, unit, method, en, fi", [
    # rounds to zero: no minus (and no sign on a positive near-zero either)
    ("-0.001", Unit.EUR, None, "€0.00", "0,00 €"),
    ("0.004", Unit.EUR, None, "€0.00", "0,00 €"),
    ("-0.0", Unit.EUR, None, "€0.00", "0,00 €"),
    ("-0.004", Unit.EUR_PER_MONTH, None, "€0.00 a month", "0,00 € / kk"),
    ("-0.04", Unit.PERCENT, None, "0.0%", "0,0 %"),
    ("0.004", Unit.PERCENT, None, "0.0%", "0,0 %"),
    ("-0.0", Unit.PERCENT, None, "0.0%", "0,0 %"),
    ("-0.0", Unit.PERCENT, USER_INPUT, "0%", "0 %"),
    ("-0.04", Unit.COUNT, None, "0.0", "0,0"),
    ("-0.4", Unit.PERCENTILE, None, "0th percentile", "0. persentiili"),
    ("-0.4", Unit.DAYS, None, "0 days", "0 pv"),
    # the smallest non-zero negative of each unit keeps its minus
    ("-0.005", Unit.EUR, None, "-€0.01", "-0,01 €"),
    ("-0.005", Unit.EUR_PER_MONTH, None, "-€0.01 a month", "-0,01 € / kk"),
    ("-0.05", Unit.PERCENT, None, "-0.1%", "-0,1 %"),
    ("-0.05", Unit.COUNT, None, "-0.1", "-0,1"),
    ("-1", Unit.DAYS, None, "-1 day", "-1 pv"),
    ("-1", Unit.MONTHS, None, "-1 month", "-1 kk"),
])
def test_no_negative_zero(value, unit, method, en, fi):
    """#93: a value that rounds to zero never shows a minus; one that does not round to zero keeps it."""
    assert display(Decimal(value), unit, "en", method) == en
    assert display(Decimal(value), unit, "fi", method) == fi


@pytest.mark.parametrize("value", ["-0.5", "-1", "100.5", "101", "250"])
def test_a_percentile_outside_0_to_100_is_refused(value):
    with pytest.raises(ValueError, match="between 0 and 100"):
        display(Decimal(value), Unit.PERCENTILE)


def test_edges_of_the_percentile_range():
    assert display(Decimal("0"), Unit.PERCENTILE) == "0th percentile"
    assert display(Decimal("100.4"), Unit.PERCENTILE) == "100th percentile"
    assert display(Decimal("-0.49"), Unit.PERCENTILE, "fi") == "0. persentiili"


@pytest.mark.parametrize("value, unit, en", [
    (2.675, Unit.EUR, "€2.68"),          # Decimal(2.675) would be 2.67499… and show €2.67
    (1.005, Unit.EUR, "€1.01"),
    (18.95, Unit.PERCENT, "19.0%"),
    (14, Unit.COUNT, "14"),
    (0.1 + 0.2, Unit.EUR, "€0.30"),
])
def test_a_float_goes_through_its_text(value, unit, en):
    assert display(value, unit) == en


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
# Every way of setting a `display` in the service code (core/tools and core/app) must use a call of
# core.tools.formatting.display: a `display=` keyword, a `"display":` dict entry, `x.display = …`,
# `x["display"] = …`, an annotated assignment and `setattr(x, "display", …)`. An augmented assignment
# (`x.display += …`) is always hand-built. Only the formatter itself counts, as imported in that file;
# any other function or attribute named `display` does not. The tools build their Numbers through
# NumberBuilder.number, which always calls it.

ROOT = Path(__file__).resolve().parents[2]
SOURCES = sorted(p for d in ("tools", "app") for p in (ROOT / d).rglob("*.py") if "tests" not in p.parts)
FORMATTER = "core.tools.formatting"


def _formatter_names(tree: ast.AST) -> tuple[set[str], set[str]]:
    """The names this file binds to core.tools.formatting.display, and to the module itself."""
    functions, modules = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == FORMATTER or (node.level and module == "formatting"):
                functions |= {a.asname or a.name for a in node.names if a.name == "display"}
            elif module == "core.tools" or (node.level and not module):
                modules |= {a.asname or a.name for a in node.names if a.name == "formatting"}
        elif isinstance(node, ast.Import):
            modules |= {a.asname for a in node.names if a.name == FORMATTER and a.asname}
    return functions, modules


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def _is_formatter_call(node: ast.AST | None, functions: set[str], modules: set[str]) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if isinstance(f, ast.Name):
        return f.id in functions
    if isinstance(f, ast.Attribute) and f.attr == "display":
        return _dotted(f.value) in modules or _dotted(f.value) == FORMATTER
    return False


def _is_display_target(target: ast.AST) -> bool:
    if isinstance(target, ast.Attribute):
        return target.attr == "display"
    if isinstance(target, ast.Subscript):
        return isinstance(target.slice, ast.Constant) and target.slice.value == "display"
    return False


def hand_built_displays(source: str, name: str) -> list[str]:
    tree = ast.parse(source)
    functions, modules = _formatter_names(tree)
    out = []
    for node in ast.walk(tree):
        values: list[ast.AST] = []
        if isinstance(node, ast.Call):
            values += [k.value for k in node.keywords if k.arg == "display"]
            if (isinstance(node.func, ast.Name) and node.func.id == "setattr" and len(node.args) == 3
                    and isinstance(node.args[1], ast.Constant) and node.args[1].value == "display"):
                values.append(node.args[2])
        elif isinstance(node, ast.Dict):
            values += [v for k, v in zip(node.keys, node.values)
                       if isinstance(k, ast.Constant) and k.value == "display"]
        elif isinstance(node, ast.Assign):
            if any(_is_display_target(t) for t in node.targets):
                values.append(node.value)
        elif isinstance(node, ast.AnnAssign):
            if _is_display_target(node.target) and node.value is not None:
                values.append(node.value)
        elif isinstance(node, ast.AugAssign):
            if _is_display_target(node.target):
                out.append(f"{name}:{node.lineno}")   # always hand-built
        out += [f"{name}:{v.lineno}" for v in values if not _is_formatter_call(v, functions, modules)]
    return out


def test_no_display_is_built_by_hand():
    assert len(SOURCES) > 10
    found = [x for p in SOURCES for x in hand_built_displays(p.read_text(encoding="utf-8"), p.relative_to(ROOT).as_posix())]
    assert found == [], f"build these displays with core.tools.formatting.display(value, unit, language, method): {found}"


BAD = """\
from core.tools.formatting import display
from other import render
Number(value=20, display=f"{pct}%")
x = {"display": "20%"}
n.display = str(v)
row["display"] = f"{amount} €"
n.display: str = "€" + text
n.display += " a month"
setattr(n, "display", "20%")
Number(value=20, display=render.display(v))
Number(value=20, display=other_display(v))
"""
GOOD = """\
from core.tools.formatting import display
from core.tools import formatting
from core.tools.formatting import display as fmt
Number(value=20, display=display(v, Unit.PERCENT, lang, method))
x = {"display": formatting.display(v, u)}
row["display"] = fmt(v, Unit.EUR, lang)
n.display: str = display(v, u)
setattr(n, "display", formatting.display(v, u))
"""


def test_the_check_finds_every_form_of_a_hand_built_display():
    found = sorted(hand_built_displays(BAD, "bad.py"), key=lambda s: int(s.split(":")[1]))
    assert found == [f"bad.py:{n}" for n in range(3, 12)]
    assert hand_built_displays(GOOD, "good.py") == []


def test_a_display_function_not_from_the_formatter_does_not_count():
    """A file that defines or imports some other `display` does not pass by its name alone."""
    source = "def display(v):\n    return str(v)\nNumber(value=1, display=display(v))\n"
    assert hand_built_displays(source, "x.py") == ["x.py:3"]
