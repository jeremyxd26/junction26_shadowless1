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

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator


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


class OpenHostScreenAction(Model):
    """Open a screen of the host app (contract 0.3.1, #267; `contact_bank` since 0.3.3, #420). The app sends
    the host message `sentti.openHostScreen` with `{target}` only; the target list is closed."""
    type: Literal["open_host_screen"]
    label: str
    target: Literal["monthly_saving", "bonus_to_fund", "contact_bank"]


Action = Annotated[Union[OpenEvidenceAction, AskAction, OpenWhatifAction, OpenHostScreenAction],
                   Field(discriminator="type")]


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


# The review card (contract 0.2.0 section 3, #68): the coach asks about one spending spike.
AnswerBasket = Literal["unexpected_necessities", "everyday_spending"]
BasketKey = Literal["regular_essentials", "unexpected_necessities", "everyday_spending"]


class Bilingual(Model):
    en: str
    fi: str


class MerchantAlias(Model):
    alias: str
    label: str


class BasketRef(Model):
    key: Literal["regular_essentials", "unexpected_necessities", "everyday_spending", "unclassified"]
    label: str


class ReviewOption(Model):
    basket: AnswerBasket
    label: Bilingual
    effect: Bilingual


class ReviewCard(CardBase):
    type: Literal["review"]
    tx_ref: str
    date: date
    category: str
    merchant: MerchantAlias | None
    amount: Number
    current_basket: BasketRef
    question: Bilingual
    options: list[ReviewOption] = Field(min_length=2, max_length=2)
    why: str


class SaveReasonCategory(Model):
    key: str
    label: str


class SaveReason(Model):
    kind: Literal["essentials_exceed_income", "largest_everyday_category"]
    category: SaveReasonCategory | None
    amount: Number
    text: str


class SafeToSaveCard(CardBase):
    """The overview's `safe_to_save` card (section 3; metrics.md section 3.1), from get_safe_to_save (#165)."""
    type: Literal["safe_to_save"]
    monthly: Number
    weekly: Number      # #417: monthly x 7 / 30.4375
    daily: Number       # #417: monthly / 30.4375
    monthly_components: list[Component]
    stock: Number
    stock_explanation: str
    stock_components: list[Component]
    reason: SaveReason | None


# ---- errors (section 4) -----------------------------------------------------------------------------

class ErrorBody(Model):
    code: Literal["invalid_request", "customer_not_found", "evidence_not_found", "evidence_forbidden",
                  "invalid_scenario", "tx_ref_not_found", "basket_not_allowed", "rate_limited",
                  "data_unavailable", "llm_unavailable", "internal",
                  "not_found",  # not_found: contract addition (#79), an unknown route
                  "invalid_bill"]  # the bill explanation (#242); its body adds `reason` (BillErrorBody)
    message: str
    retryable: bool


class ErrorResponse(Model):
    error: ErrorBody


BillRefusalReason = Literal["one_of_barcode_or_fields", "payee_with_fields", "barcode_length", "barcode_version",
                            "barcode_chars", "barcode_check", "due_date", "amount_missing", "due_date_missing",
                            "amount_too_large"]


class BillErrorBody(ErrorBody):
    """A 422 invalid_bill: the envelope plus `reason`; `message` is that reason's sentence (section 11.1)."""

    code: Literal["invalid_bill"]
    reason: BillRefusalReason


class BillErrorResponse(Model):
    error: BillErrorBody


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
    hero: MetricCard | None  # safe to spend in the next 7 days (#79); null on a known tool failure
    safe_to_save: SafeToSaveCard | None  # what a typical month leaves (#165); null on a known tool failure
    cards: list[Card]
    reviews: list[ReviewCard] = Field(max_length=1)  # the pending spike review, if any (#68)
    insights: list[Insight]
    suggested_questions: list[str]


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
# ---- POST /api/baskets/label (section 10, #68) ------------------------------------------------------

class LabelRequest(Model):
    model_config = ConfigDict(extra="forbid")  # an unknown field is a 400, not silently dropped

    customer_id: str = Field(pattern=r"^CUST[0-9]{5}$")
    tx_ref: str = Field(max_length=64)
    # Required and nullable: null undoes the label. A value that is not a basket key is a 400; a basket
    # key that is not one of the review's two options is a 422 basket_not_allowed (checked later).
    basket: BasketKey | None
    language: Language = "en"


class LabelState(Model):
    basket: AnswerBasket
    label: str
    labelled_at: str  # ISO 8601 with offset (section 1)


class LabelMessage(Model):
    text: str
    text_rendered: str
    numbers: dict[str, NumberWithId]


class Change(Model):
    key: str
    label: str
    before: Number
    after: Number


class EffectItem(Model):
    key: str  # safe_to_spend, safe_to_save, irregular_reserve, or the basket the purchase moved into
    label: str
    before: NumberWithId
    after: NumberWithId


class LabelEffect(Model):
    """#382: the headline numbers before and after the answer, and the text built from their difference."""
    items: list[EffectItem]
    text: str
    text_rendered: str
    numbers: dict[str, NumberWithId]


class LabelResponse(Model):
    customer_id: str
    as_of: date
    language: Language
    tx_ref: str
    label: LabelState | None
    review_state: Literal["answered", "pending", "closed"]
    changed: bool
    message: LabelMessage
    changes: list[Change]
    effect: LabelEffect | None = None  # null when nothing changed (#382)
    refetch: list[str]


# ---- POST /api/bill/explain (section 11, contract 0.3.0; the endpoint comes with #242) ----------------

BILL_AMOUNT = r"^[0-9]{1,6}(\.[0-9]{1,2})?$"   # euros with at most two decimals, ASCII digits only
BILL_AMOUNT_MAX = Decimal("100000.00")
ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _iso_date(value: object) -> object:
    """Only `YYYY-MM-DD` (then a real date, checked by pydantic): the lax date type would take 0 as
    1970-01-01 or accept a timestamp."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not ISO_DATE.fullmatch(value):
        raise ValueError("a date must be written YYYY-MM-DD")
    return value


IsoDate = Annotated[date, BeforeValidator(_iso_date)]


class BillFieldsRequest(Model):
    model_config = ConfigDict(extra="forbid")

    payee: str = Field(min_length=1, max_length=70)
    iban: str = Field(min_length=1, max_length=42)
    reference: str = Field(min_length=1, max_length=35)
    amount: str = Field(pattern=BILL_AMOUNT)   # a decimal string: more than 0, at most 100000.00
    due_date: IsoDate

    @field_validator("amount")
    @classmethod
    def _amount_in_range(cls, value: str) -> str:
        if not Decimal(0) < Decimal(value) <= BILL_AMOUNT_MAX:
            raise ValueError("amount must be more than 0 and at most 100000.00")
        return value


class BillExplainRequest(Model):
    model_config = ConfigDict(extra="forbid")  # an unknown field is a 400, not silently dropped

    customer_id: str = Field(pattern=r"^CUST[0-9]{5}$")
    language: Language = "en"
    # Exactly one of `barcode` and `fields`. Both or neither, or `payee` beside `fields`, is a 422
    # invalid_bill that the endpoint checks: a validation error here would be a 400.
    barcode: str | None = Field(default=None, max_length=80)
    payee: str | None = Field(default=None, min_length=1, max_length=70)  # only beside a barcode
    fields: BillFieldsRequest | None = None


class BillRead(Model):
    source: Literal["barcode", "fields"]
    payee: str | None
    iban: str        # formatted for display
    reference: str   # formatted for display
    amount: Number   # bill_barcode@1 or user_input@1, no evidence ref
    due_date: date


class BillChecks(Model):
    iban: Literal["pass", "fail"]
    reference: Literal["pass", "fail"]
    due_date: Literal["pass", "past"]


class BillMatch(Model):
    status: Literal["matched", "not_matched", "no_payee"]
    bill_id: str | None
    label: str | None
    text: str


class BillBasket(Model):
    key: BasketKey
    label: str
    text: str


class BillSafeToSpend(Model):
    """The bill applied to the balance side like a bill due before payday, and the hero's own computation
    run again: free until payday and safe to spend, each before and after (null after payday)."""

    effect: Literal["after_payday", "excess_only", "full"]
    next_payday: date
    reserved: Number | None                # excess_only: the matched bill's due_until_payday
    counted: Number | None                 # what the bill adds to the bills due before payday
    free_until_payday_before: Number       # the hero's "Free until payday"
    free_until_payday_after: Number | None
    before: Number                         # the hero's primary
    after: Number | None                   # recomputed by the hero's function, never by subtraction
    text: str


class BillSignal(Model):
    code: Literal["iban_check_failed", "reference_check_failed", "new_payee", "amount_above_usual", "short_term"]
    text: str
    numbers: list[Number]   # the Numbers whose display the text cites, in order


class GlossaryEntry(Model):
    term: Literal["reference_number", "due_date", "virtual_barcode", "late_payment_interest"]
    label: str
    text: str


class PaymentDraft(Model):
    payee: str | None
    iban: str        # normalised, no spaces
    reference: str   # normalised, no spaces
    amount: Number
    due_date: date


class AddToPaymentsAction(Model):
    type: Literal["add_to_payments"]
    label: str
    draft: PaymentDraft


class BillExplainResponse(Model):
    customer_id: str
    as_of: date
    language: Language
    bill: BillRead
    checks: BillChecks
    match: BillMatch
    comparison: Comparison | None
    basket: BillBasket
    safe_to_spend: BillSafeToSpend | None  # null when safe to spend cannot be computed (as the hero)
    glossary: list[GlossaryEntry]
    # The payment draft when the checks pass; the way to the bank (contact_bank) when there are warning signs.
    actions: list[Annotated[Union[AddToPaymentsAction, OpenHostScreenAction], Field(discriminator="type")]] = (
        Field(max_length=2))
    warnings: list[str]
    signals: list[BillSignal]   # warning signs, never a verdict (#242, decision 10)
