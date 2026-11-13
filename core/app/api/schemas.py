"""Response models that mirror contracts/api.md (version on `main`).

`core/tests/test_api_contract.py` validates every JSON example of the contract against these models
and fails on a field the model does not have or a field the example does not show, so the code
cannot drift from the contract silently.

Fields the service sends that the contract does not define are dropped (`extra="ignore"`): tool
cards carry extra data for the model (for example number ids and a bill's typical day).

Contract 0.2.0 adds `reviews` (#68) and `safe_to_save` (#53/#55) to the overview, and the label
endpoint's error codes (#68); see the EXTENSION POINT markers below and in overview.py, and PENDING
in core/tests/test_api_contract.py.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


Language = Literal["en", "fi"]
UnitName = Literal["eur", "eur_per_day", "eur_per_week", "eur_per_month", "eur_per_year", "percent",
                   "percentile", "count", "days", "months"]


# ---- shared objects (section 2) --------------------------------------------------------------------

class Period(Model):
    start: date
    end: date
    label: str


class Number(Model):
    value: int | float
    unit: UnitName
    period: Period
    method: str
    evidence_ref: str | None
    label: str
    display: str


class NumberWithId(Number):
    id: str


class Comparison(Model):
    baseline: Number
    change: Number
    change_pct: Number | None
    tone: Literal["better", "worse", "neutral"]
    label: str


# ---- cards (section 3) ------------------------------------------------------------------------------

class Estimate(Model):
    label: str
    text: str


class OpenEvidenceAction(Model):
    type: Literal["open_evidence"]
    label: str
    evidence_ref: str


class AskAction(Model):
    type: Literal["ask"]
    label: str
    prompt: str


class OpenWhatifAction(Model):
    type: Literal["open_whatif"]
    label: str
    scenario: dict


Action = Annotated[Union[OpenEvidenceAction, AskAction, OpenWhatifAction], Field(discriminator="type")]


class CardBase(Model):
    card_id: str
    title: str
    subtitle: str | None
    evidence_ref: str | None
    estimate: Estimate | None
    actions: list[Action] = Field(max_length=2)


class Component(Model):
    key: str
    label: str
    operation: Literal["add", "subtract"]
    amount: Number


class MetricCard(CardBase):
    type: Literal["metric"]
    status: Literal["ok", "below_usual", "nothing_free"] | None
    primary: Number
    secondary: list[Number]
    comparison: Comparison | None
    components: list[Component]


class BreakdownItem(Model):
    key: str  # a category, basket (also `unclassified`), MCC group or month, or `other`
    label: str
    amount: Number
    share: Number | None
    change: Number | None
    flags: list[Literal["one_off", "habit"]]


class BreakdownCard(CardBase):
    type: Literal["breakdown"]
    display_hint: Literal["list", "stacked_bar", "time_series"]
    total: Number
    comparison: Comparison | None
    items: list[BreakdownItem]


class BillItem(Model):
    bill_id: str
    label: str
    category: str
    cadence: Literal["monthly"]
    status: Literal["spread", "done_this_month", "upcoming", "late", "skipped_this_month"]
    status_label: str
    typical_month: Number
    last_paid: date
    next_expected: date | None
    due_until_payday: Number
    evidence_ref: str | None


class BillsCard(CardBase):
    type: Literal["bills"]
    total: Number
    items: list[BillItem]


# The overview uses these three card types. The other card types of section 3 (peer, stores, profile,
# whatif) join the union when an endpoint returns them.
Card = Annotated[Union[MetricCard, BreakdownCard, BillsCard], Field(discriminator="type")]


# ---- errors (section 4) -----------------------------------------------------------------------------

class ErrorBody(Model):
    code: Literal["invalid_request", "customer_not_found", "evidence_not_found", "evidence_forbidden",
                  "invalid_scenario", "rate_limited", "data_unavailable", "llm_unavailable", "internal",
                  "not_found"]  # not_found: contract addition (#79), an unknown route
    message: str
    retryable: bool


class ErrorResponse(Model):
    error: ErrorBody


# ---- GET /api/personas (section 5) -----------------------------------------------------------------

class PostalArea(Model):
    code: str
    label: str


class ProfileRef(Model):
    key: Literal["not_enough_income_data", "stretched", "big_ticket", "everyday_heavy", "saver", "steady"]
    label: str


class Persona(Model):
    customer_id: str
    display_name: str
    age_band: Literal["18-24", "25-34", "35-44", "45-54", "55-64", "65-74", "75+"]
    postal_area: PostalArea
    profile: ProfileRef
    tagline: str
    default_language: Language


class PersonasResponse(Model):
    as_of: date
    language: Language
    personas: list[Persona]


# ---- GET /api/overview/{customer_id} (section 6) ---------------------------------------------------

class Insight(Model):
    insight_id: str
    kind: Literal["habit_trend", "one_off", "bill_change", "store_saving", "peer_gap", "low_safe_to_spend"]
    title: str
    text: str
    text_rendered: str
    numbers: dict[str, NumberWithId]
    estimate: Estimate | None
    action: Action | None


class OverviewResponse(Model):
    customer_id: str
    as_of: date
    language: Language
    greeting: str
    ai_disclosure: str
    hero: MetricCard  # safe to spend in the next 7 days, from overview.HERO_TOOL (#79)
    cards: list[Card]
    # Always [] until the spike review exists: #68 narrows the item to its review card model.
    reviews: list[dict[str, Any]]
    insights: list[Insight]
    suggested_questions: list[str]
    # EXTENSION POINT (contract 0.2.0): `safe_to_save: SafeToSaveCard` (#53/#55) is added here.


# ---- GET /api/evidence/{ref} (section 9) -----------------------------------------------------------

class MethodBlock(Model):
    id: str
    name: str
    summary: str
    doc: str


class Query(Model):
    categories: list[str]
    baskets: list[str]
    mcc_groups: list[str]
    merchant_id: str | None
    period: Period


class Merchant(Model):
    id: str
    label: str


class EvidenceRow(Model):
    tx_id: str
    date: date
    time: str
    category: str
    merchant: Merchant | None
    mcc: str | None
    amount: str  # decimal string with the bank sign (section 9)
    currency: Literal["EUR"]
    # Contract addition (#79, Renat): the amount formatted like a Number's display, in the request
    # language, so the client never formats a number. `amount` stays the exact decimal string.
    display: str


class Part(Model):
    role: str
    number: Number


class EvidenceResponse(Model):
    evidence_ref: str
    # "metric" (#55): a number re-run from a metric SQL file. Not in contract 0.1.2; its text lands with #34.
    kind: Literal["transactions", "composite", "peer_aggregate", "store_index", "metric"]
    language: Language
    title: str
    number: Number
    method: MethodBlock
    query: Query | None
    rows: list[EvidenceRow]
    row_count: Number | None
    reconciles: bool | None
    parts: list[Part]
    next_cursor: str | None
    privacy_note: str


# ---- POST /api/whatif (section 8) ----------------------------------------------------------------

SelectionKind = Literal["category", "basket", "mcc", "merchant"]


class WhatIfSelection(Model):
    kind: SelectionKind
    value: str = Field(min_length=1, max_length=100)


class WhatIfScenarioRequest(Model):
    selection: WhatIfSelection
    cut_pct: int = Field(ge=1, le=100, strict=True)  # a whole number; "20" or 20.5 is a 400


class WhatIfRequest(Model):
    customer_id: str = Field(pattern=r"^CUST[0-9]{5}$")
    scenario: WhatIfScenarioRequest
    language: Language = "en"


class WhatIfScenario(Model):
    selection: WhatIfSelection  # for a merchant, the merchant id the app sent
    cut_pct: Number
    label: str


class WhatIfResponse(Model):
    customer_id: str
    as_of: date
    language: Language
    scenario: WhatIfScenario
    status: Literal["estimate", "estimate_with_caveat", "not_offered"]
    baseline_per_month: Number
    saving_per_month: Number
    saving_per_week: Number
    saving_per_year: Number
    one_off_excluded: Number
    regular_excluded: Number
    assumptions: list[str]
    caveats: list[str]
    estimate: Estimate
    evidence_ref: str
