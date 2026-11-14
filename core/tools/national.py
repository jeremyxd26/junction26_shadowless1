"""National context beside the peer comparison (#569): Statistics Finland's household budget survey, the monthly
spending per consumption unit of households whose reference person is in the customer's age group.

The values are in core/config/national_context.yaml, fetched once during development and read here once at
import. Nothing in this module or anywhere else fetches them at run time, in tests or in CI. A missing or malformed
file stops the import with a ValueError naming what is wrong.

The figure is context, never a verdict: it is no input of safe to spend, safe to save, the savings plan or any
other number, and it never decides a cut offer. Health and housing are never in the file (housing in the survey
holds imputed rent; health is never compared, R9)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import yaml

from core.tools.db import ROOT

CONFIG_PATH = "core/config/national_context.yaml"   # relative: the form every spec shows
CONFIG_FILE = ROOT / CONFIG_PATH
NEVER = frozenset({"Health", "Housing"})   # never a national comparison, whatever the file says


@dataclass(frozen=True)
class NationalFigure:
    """The table's monthly value for one category and one of its age groups, with what the line and the
    evidence cite."""
    category: str
    age_group: str             # the table's own band, "17-24": the line names it
    monthly: Decimal           # EUR per consumption unit a month (the yearly value / 12, rounded to cents)
    yearly: int                # EUR per consumption unit a year, as the table gives it
    survey_year: int
    table_id: str
    source: dict[str, str]     # {"en": ..., "fi": ...}
    unit: str

    def params(self) -> dict[str, Any]:
        """What the Number's evidence cites: the source, the table, the year, the unit and the age group, and the
        place of the value in the file (rule_value evidence, as the S-Bonus rules cite theirs)."""
        return {"value": str(self.monthly), "category": self.category,
                "rule": f"categories.{self.category}.monthly.{self.age_group}",
                "source": self.source["en"], "table": self.table_id, "survey_year": self.survey_year,
                "unit": self.unit, "age_group": self.age_group, "yearly": self.yearly,
                "monthly_rule": RULES.monthly_rule, "config": CONFIG_PATH, "version": RULES.version}


@dataclass(frozen=True)
class NationalRules:
    version: int
    survey_year: int
    table_id: str
    source: dict[str, str]
    unit: str
    monthly_rule: str
    attribution: str
    age_groups: dict[str, str]                    # the peer tool's band -> the table's band
    yearly: dict[str, dict[str, int]]            # category -> table band -> EUR a year
    monthly: dict[str, dict[str, Decimal]]       # category -> table band -> EUR a month


def _need(doc: dict, key: str, kind: type) -> Any:
    if not isinstance(doc.get(key), kind):
        raise ValueError(f"{CONFIG_PATH}: {key} is missing or not a {kind.__name__}")
    return doc[key]


def _money(value: Any, where: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{CONFIG_PATH}: {where} is not a number: {value!r}") from None
    if not d.is_finite() or d <= 0:
        raise ValueError(f"{CONFIG_PATH}: {where} must be a positive number: {value!r}")
    return d


def load(path=CONFIG_FILE) -> NationalRules:
    """The file, checked: every category has a yearly and a monthly value for every table band of the age map,
    and each monthly value is its yearly value / 12 rounded to cents."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{CONFIG_PATH}: not a mapping")
    source = _need(doc, "source", dict)
    if not all(isinstance(source.get(lang), str) and source[lang] for lang in ("en", "fi")):
        raise ValueError(f"{CONFIG_PATH}: source needs en and fi")
    age_groups = {str(k): str(v) for k, v in _need(doc, "age_groups", dict).items()}
    bands = set(age_groups.values())
    yearly: dict[str, dict[str, int]] = {}
    monthly: dict[str, dict[str, Decimal]] = {}
    for category, entry in _need(doc, "categories", dict).items():
        if category in NEVER:
            raise ValueError(f"{CONFIG_PATH}: {category} is never compared nationally")
        years = {str(b): v for b, v in (entry.get("yearly") or {}).items()}
        months = {str(b): _money(v, f"{category}.monthly.{b}") for b, v in (entry.get("monthly") or {}).items()}
        if not bands <= set(years) or not bands <= set(months):
            raise ValueError(f"{CONFIG_PATH}: {category} lacks an age group of age_groups")
        for band in bands:
            y = _money(years[band], f"{category}.yearly.{band}")
            if months[band] != (y / 12).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):
                raise ValueError(f"{CONFIG_PATH}: {category}.monthly.{band} is not its yearly value / 12")
        yearly[category] = {b: int(years[b]) for b in bands}
        monthly[category] = {b: months[b] for b in bands}
    return NationalRules(
        version=_need(doc, "version", int), survey_year=_need(doc, "survey_year", int),
        table_id=_need(doc, "table_id", str), source={"en": source["en"], "fi": source["fi"]},
        unit=_need(doc, "unit", str), monthly_rule=_need(doc, "monthly_rule", str),
        attribution=_need(doc, "attribution", str), age_groups=age_groups, yearly=yearly, monthly=monthly)


RULES = load()


def figure(category: str, age_band: str | None) -> NationalFigure | None:
    """The table's monthly value for the customer's age band (the peer tool's band) and a category, or None: a
    category the file does not keep (Restaurants, Health, Housing, any other), or an age band with no table band
    (75+, or none)."""
    if category in NEVER or category not in RULES.monthly or age_band not in RULES.age_groups:
        return None
    band = RULES.age_groups[age_band]
    return NationalFigure(category=category, age_group=band, monthly=RULES.monthly[category][band],
                          yearly=RULES.yearly[category][band], survey_year=RULES.survey_year,
                          table_id=RULES.table_id, source=dict(RULES.source), unit=RULES.unit)
