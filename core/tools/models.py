"""Typed shapes shared by every tool: enums, arguments, Number, Period, Card and ToolResult.

Shapes follow contracts/api.md (Number 2.1, Period 2.2, Comparison 2.3, cards 3) and
docs/design/agent-core.md section 6.1. Argument models forbid unknown fields and have no customer
field: the customer always comes from the server-bound context (R4).
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.tools import config


def _enum(name: str, values) -> type[Enum]:
    """A str Enum whose member values are exactly the given keys."""
    members = {v.upper().replace(" & ", "_AND_").replace(" ", "_").replace("-", "_"): v for v in values}
    return Enum(name, members, type=str)


Category = _enum("Category", config.CATEGORIES)
Basket = _enum("Basket", config.BASKETS)
MccGroup = _enum("MccGroup", config.MCC_GROUPS)


class PeriodPreset(str, Enum):
    THIS_WEEK = "this_week"
    LAST_WEEK = "last_week"
    THIS_MONTH = "this_month"
    LAST_MONTH = "last_month"
    LAST_3_MONTHS = "last_3_months"
    LAST_6_MONTHS = "last_6_months"
    LAST_12_MONTHS = "last_12_months"
    YEAR_TO_DATE = "year_to_date"
    CUSTOM = "custom"


class Direction(str, Enum):
    OUT = "out"
    IN = "in"


class GroupBy(str, Enum):
    NONE = "none"
    CATEGORY = "category"
    BASKET = "basket"
    MERCHANT = "merchant"
    MCC_GROUP = "mcc_group"
    MONTH = "month"
    WEEK = "week"


class CompareTo(str, Enum):
    NONE = "none"
    PREVIOUS_PERIOD = "previous_period"
    SAME_PERIOD_LAST_YEAR = "same_period_last_year"
    TYPICAL = "typical"


class Unit(str, Enum):
    EUR = "eur"
    EUR_PER_DAY = "eur_per_day"
    EUR_PER_WEEK = "eur_per_week"
    EUR_PER_MONTH = "eur_per_month"
    EUR_PER_YEAR = "eur_per_year"
    PERCENT = "percent"
    PERCENTILE = "percentile"
    COUNT = "count"
    DAYS = "days"
    MONTHS = "months"


class Tone(str, Enum):
    BETTER = "better"
    WORSE = "worse"
    NEUTRAL = "neutral"


# A merchant alias the model may use: lowercase letters only, mapped to a merchant id on the server.
MERCHANT_ALIAS_PATTERN = r"^store_[a-z]+$"


class Args(BaseModel):
    """Base of every tool's arguments: unknown fields (for example customer_id) are rejected."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class PeriodArg(Args):
    preset: PeriodPreset
    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def _custom_dates(self) -> PeriodArg:
        if self.preset is PeriodPreset.CUSTOM:
            if self.start is None or self.end is None:
                raise ValueError("custom periods need both start and end")
            if self.start > self.end:
                raise ValueError("start must not be after end")
        elif self.start is not None or self.end is not None:
            raise ValueError("start and end are only allowed with preset 'custom'")
        return self


class Filter(Args):
    categories: list[Category] | None = None
    baskets: list[Basket] | None = None
    mcc_groups: list[MccGroup] | None = None
    merchant: str | None = Field(default=None, pattern=MERCHANT_ALIAS_PATTERN)


class Period(BaseModel):
    """A resolved period, inclusive at both ends and clamped to [DATA_START, as_of] (R5)."""

    start: date
    end: date
    label: str


class Number(BaseModel):
    """contracts/api.md 2.1. `id` is set by the per-answer registry, not by the tool."""

    value: float
    unit: Unit
    period: Period
    method: str
    evidence_ref: str | None
    label: str
    display: str
    id: str | None = None


class Comparison(BaseModel):
    baseline: Number
    change: Number
    change_pct: Number | None
    tone: Tone
    label: str


class Action(BaseModel):
    type: Literal["open_evidence", "ask", "open_whatif"]
    label: str
    evidence_ref: str | None = None
    prompt: str | None = None


class Card(BaseModel):
    """Common card fields (contracts/api.md section 3). Type-specific fields are added per type."""

    model_config = ConfigDict(extra="allow")

    card_id: str
    type: Literal["metric", "breakdown", "bills", "peer", "stores", "profile", "whatif"]
    title: str
    subtitle: str | None = None
    evidence_ref: str | None = None
    estimate: dict[str, str] | None = None
    actions: list[Action] = Field(default_factory=list, max_length=2)


class ToolResult(BaseModel):
    """What every tool returns (agent-core.md section 6.1)."""

    tool: str
    data: Any
    card: Card | None = None
    notes: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)  # refs written for this result
    model_view: dict[str, Any] = Field(default_factory=dict)
