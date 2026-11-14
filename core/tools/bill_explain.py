"""explain_bill: a bill the customer shows, explained with their own data (#242, contracts/api.md section 11).

No model is called and nothing is stored: a read-only computation, like the what-if calculator. Every
number of the answer is one of these:
- the bill's amount, read from its virtual barcode and checked by code (`bill_barcode@1`) or typed or
  confirmed by the user (`user_input@1`). It is not the customer's data, so it has no evidence ref;
- one of the customer's numbers, taken from the tool that builds it (the hero of get_safe_to_spend, the
  bills card of get_recurring_bills), so it carries the same evidence ref as there;
- computed: the comparison with the typical amount and what the bill adds to the bills due before payday
  are composites whose bill part is stored inline (evidence.composite_spec); free until payday and safe to
  spend after the bill are recomputed by 03_safe_to_spend.sql itself, with the bill as
  app.extra_bill_due_eur, never by subtracting from safe to spend (rules in docs/design/metrics.md 3.3).

The texts the customer sent (payee, IBAN, reference) are data only: they are returned, never interpreted,
never used in a query, and the payee as sent is never put into a sentence. Only the amount goes into an
evidence spec.
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from core.bills import parse as bill_parse
from core.tools import config, evidence, metric_sql, periods
from core.tools.bills import BillItem, get_recurring_bills
from core.tools.context import ToolContext
from core.tools.formatting import display, money
from core.tools.models import Number, Period, Unit
from core.tools.numbers import NumberBuilder, json_value
from core.tools.safe_to_spend import BillsDueMismatch, NoTransactions, get_safe_to_spend, settings_for

TOOL = "explain_bill"
BARCODE_METHOD = "bill_barcode@1"
VS_TYPICAL_EUR = "bill.vs_typical_eur@1"
VS_TYPICAL_PCT = "bill.vs_typical_pct@1"
COUNTED = "bill.counted_eur@1"
FREE_AFTER = "bill.free_until_payday_after_eur@1"
AFTER = "bill.safe_to_spend_after_eur@1"
BALANCE_LIMIT = "safe_to_spend.balance_limit_7d_eur@1"
EXTRA_SETTING = "extra_bill_due_eur"   # 03_safe_to_spend.sql; typed and bounded in metric_sql.TYPED_SETTINGS
# Safe to spend cannot be computed for these known reasons: then `safe_to_spend` is null (as the hero).
HERO_KNOWN_FAILURES = (BillsDueMismatch, NoTransactions)
# The parser's codes (#241) as the reasons of a 422 invalid_bill: a failed check inside a barcode is one
# reason, barcode_check, since the parser never returns its fields.
PARSER_REASONS = {"barcode_length": "barcode_length", "barcode_version": "barcode_version",
                  "barcode_chars": "barcode_chars", "iban_check": "barcode_check",
                  "reference_check": "barcode_check", "due_date": "due_date"}
GLOSSARY_TERMS = ("reference_number", "due_date", "virtual_barcode", "late_payment_interest")
log = logging.getLogger(__name__)


class BillRefused(ValueError):
    """The bill cannot be explained: a 422 invalid_bill with this reason (contracts/api.md section 11.1)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class BillInput:
    """The bill as read: from a barcode (every field checked by the parser) or typed (checked here)."""

    source: Literal["barcode", "fields"]
    payee: str | None
    iban: str               # normalised (no spaces) when it could be; else as sent, spaces collapsed
    reference: str
    iban_display: str
    reference_display: str
    amount: Decimal         # euros, cents
    due_date: date
    iban_ok: bool
    reference_ok: bool

    @property
    def method(self) -> str:
        return BARCODE_METHOD if self.source == "barcode" else config.USER_INPUT_METHOD


def _t(key: str, language: str, **kw: Any) -> str:
    return config.label(config.BILL_TEXT[key], language).format(**kw)


def _clean(text: str | None) -> str | None:
    """A text the customer sent, with its whitespace collapsed; data only."""
    return None if text is None else " ".join(text.split())


def canonical_reference(reference: str) -> str:
    """One form of a normalised reference, for the response and the draft. An RF reference loses the zeros
    after its check digits: a typed one keeps them (RF0400009991) while the parser reads the same reference
    from a barcode without them (RF049991). The value, and so its mod-97 check, is the same. A national
    reference already has no leading zeros (#241)."""
    if reference.startswith("RF") and len(reference) > 4:
        return reference[:4] + (reference[4:].lstrip("0") or "0")
    return reference


# ---- reading the bill -------------------------------------------------------------------------------------

def read_barcode(barcode: str, payee: str | None) -> BillInput:
    """A bill from its virtual barcode. BillRefused when it cannot be used: the parser's format codes, a
    failed check inside it (barcode_check), no amount, no due date, or an amount over the bound."""
    try:
        parsed = bill_parse.parse_virtual_barcode(barcode)
    except bill_parse.BillFormatError as exc:
        raise BillRefused(PARSER_REASONS.get(exc.code, "barcode_length")) from None
    if parsed.amount is None:
        raise BillRefused("amount_missing")
    if parsed.due_date is None:
        raise BillRefused("due_date_missing")
    amount = money(parsed.amount)
    if amount > config.BILL_AMOUNT_MAX:
        raise BillRefused("amount_too_large")
    reference = canonical_reference(parsed.reference)
    return BillInput("barcode", _clean(payee), parsed.iban, reference,
                     bill_parse.format_iban(parsed.iban), bill_parse.format_reference(reference),
                     amount, parsed.due_date, True, True)


def _normalised(normalise, fmt, text: str, canonical=lambda v: v) -> tuple[str, str]:
    """(value, display) of a typed IBAN or reference: normalised (and made canonical) and formatted when
    the parser accepts its characters, else the text as sent with its whitespace collapsed (data only)."""
    try:
        value = canonical(normalise(text))
        return value, fmt(value)
    except bill_parse.BillFormatError:
        cleaned = _clean(text) or ""
        return cleaned, cleaned


def read_fields(payee: str, iban: str, reference: str, amount: str, due_date: date) -> BillInput:
    """A bill as the customer typed or confirmed it. The amount is already validated by the request model
    (a decimal string, more than 0, at most 100000.00); a failed IBAN or reference check is not an error,
    it is reported in `checks`."""
    iban_value, iban_display = _normalised(bill_parse.normalise_iban, bill_parse.format_iban, iban)
    ref_value, ref_display = _normalised(bill_parse.normalise_reference, bill_parse.format_reference, reference,
                                         canonical_reference)
    return BillInput("fields", _clean(payee), iban_value, ref_value, iban_display, ref_display,
                     money(Decimal(amount)), due_date, bill_parse.valid_iban(iban), bill_parse.valid_reference(reference))


# ---- the rules (pure) ----------------------------------------------------------------------------------

def normalise_name(text: str) -> str:
    """A payee name for the exact match: Unicode-normalised, case folded, only letters and digits kept."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in folded if ch.isalnum())


def series_key(item: BillItem) -> str | None:
    """The recurring series of a bills-card item named by its id (`bill_<tx_type>`), else None."""
    key = item.bill_id.removeprefix("bill_")
    return key if key in config.SERIES_LABELS or key in config.PAYEE_ALIASES else None


def known_names(item: BillItem) -> set[str]:
    """Every name that matches this bill, normalised: its label in the request language, its series
    labels in both languages and the known payee names of its series (config.PAYEE_ALIASES)."""
    names = {item.label}
    key = series_key(item)
    if key is not None:
        names |= set(config.SERIES_LABELS.get(key, ()))
        names |= set(config.PAYEE_ALIASES.get(key, ()))
    return {normalise_name(n) for n in names} - {""}


def regular_bills(items: list[BillItem]) -> list[BillItem]:
    """The bills a bill can be one of: spending only (an investment deposit is a saving, not a bill)."""
    return [i for i in items if i.category in config.SPEND_CATEGORIES]


def match_bill(payee: str | None, items: list[BillItem]) -> tuple[str, BillItem | None]:
    """(status, item): `no_payee`, `not_matched`, or `matched` with the first regular bill whose label or
    known payee name equals the payee after normalisation. No fuzzy matching."""
    if payee is None:
        return "no_payee", None
    name = normalise_name(payee)
    for item in regular_bills(items):
        if name and name in known_names(item):
            return "matched", item
    return "not_matched", None


def bill_effect(due: date, next_payday: date, amount: Decimal, reserved: Decimal | None) -> tuple[str, Decimal | None]:
    """(effect, counted): what the bill adds to the bills due before payday (docs/design/metrics.md 3.3).
    - due after the next payday: `after_payday`, nothing;
    - due on or before it, and the matched bill already counted there (`reserved` > 0): `excess_only`,
      only the excess over the amount already counted;
    - due on or before it, otherwise: `full`, the whole amount."""
    if due > next_payday:
        return "after_payday", None
    if reserved is not None and reserved > 0:
        return "excess_only", money(max(amount - reserved, Decimal(0)))
    return "full", money(amount)


def signal_codes(bill: BillInput, match_status: str, typical: Decimal | None, largest: Decimal | None,
                 as_of: date) -> list[str]:
    """The warning signs of decision 10 (#242), in a fixed order; never a verdict."""
    codes = []
    if not bill.iban_ok:
        codes.append("iban_check_failed")
    if not bill.reference_ok:
        codes.append("reference_check_failed")
    if match_status != "matched":
        codes.append("new_payee")
    if match_status == "matched":
        if typical is not None and typical > 0 and bill.amount >= typical * config.BILL_ABOVE_USUAL_RATIO:
            codes.append("amount_above_usual")
    elif largest is not None and bill.amount > largest * config.BILL_ABOVE_LARGEST_RATIO:
        codes.append("amount_above_usual")
    if 0 <= (bill.due_date - as_of).days < config.BILL_SHORT_TERM_DAYS:
        codes.append("short_term")
    return codes


def draft_allowed(bill: BillInput) -> bool:
    """The payment draft is offered when the IBAN and the reference pass their checks; a past due date or
    another warning sign does not remove it."""
    return bill.iban_ok and bill.reference_ok


# ---- the explanation -------------------------------------------------------------------------------------

def _value(n: Number) -> Decimal:
    return Decimal(str(n.value))


def _dump(n: Number | None) -> dict[str, Any] | None:
    return None if n is None else n.model_dump(mode="json", exclude={"id"})


def _day(d: date, language: str) -> str:
    return periods.period_label(d, d, language)


def explain_bill(ctx: ToolContext, bill: BillInput) -> dict[str, Any]:
    """The response of POST /api/bill/explain without customer_id, as_of and language."""
    lang = ctx.language
    reg = ctx.numbers.register
    due = bill.due_date
    due_period = Period(start=due, end=due, label=_day(due, lang))
    amount_n = reg(Number(value=json_value(bill.amount, Unit.EUR), unit=Unit.EUR, period=due_period,
                          method=bill.method, evidence_ref=None, label=_t("amount", lang),
                          display=display(bill.amount, Unit.EUR, lang, bill.method)))
    nb = NumberBuilder(ctx, [])

    items = get_recurring_bills(ctx, {"include_income": False}).data.bills
    status, item = match_bill(bill.payee, items)
    if status == "matched":
        match_text = _t("match_matched", lang, label=item.label)
    else:
        match_text = _t(f"match_{status}", lang)
    match = {"status": status, "bill_id": item.bill_id if item else None, "label": item.label if item else None,
             "text": match_text}

    comparison = None
    if item is not None:
        typical, typical_v = item.typical_month, _value(item.typical_month)
        parts = {"current": (amount_n, bill.amount), "baseline": (typical, typical_v)}
        # Each composite of the bill records its period: its first part can be the inline bill amount, which
        # has no ref for the evidence view to take a period from.
        on_due = {"period": evidence.period_param(due_period)}
        change, change_v = nb.composite(VS_TYPICAL_EUR, "difference", parts, Unit.EUR, due_period, _t("change", lang),
                                        params=on_due)
        change_pct = None
        if typical_v != 0:
            change_pct = reg(nb.composite(VS_TYPICAL_PCT, "pct_change", parts, Unit.PERCENT, due_period,
                                          _t("change", lang), params=on_due)[0])
        comparison = {"baseline": _dump(typical), "change": _dump(reg(change)), "change_pct": _dump(change_pct),
                      "tone": "worse" if change_v > 0 else "better" if change_v < 0 else "neutral",
                      "label": _t("comparison", lang, label=item.label)}
        basket = {"key": "regular_essentials", "label": config.label(config.BASKET_LABELS["regular_essentials"], lang),
                  "text": _t("basket_regular", lang, label=item.label)}
    else:
        basket = {"key": "unexpected_necessities",
                  "label": config.label(config.BASKET_LABELS["unexpected_necessities"], lang),
                  "text": _t("basket_other", lang)}

    try:
        hero = get_safe_to_spend(ctx, {}).data
    except HERO_KNOWN_FAILURES as exc:
        log.warning("safe to spend unavailable for a bill (%s)", type(exc).__name__)
        hero = None
    safe_to_spend = _safe_to_spend(ctx, nb, bill, item, amount_n, hero) if hero is not None else None

    regular = regular_bills(items)
    largest = max(regular, key=lambda i: _value(i.typical_month)).typical_month if regular else None
    codes = signal_codes(bill, status, _value(item.typical_month) if item else None,
                         _value(largest) if largest else None, ctx.as_of)
    signals = [_signal(code, lang, amount_n, item, largest) for code in codes]

    # a small note that never repeats a signal: a failed check is a signal, a past due date a warning
    warnings = [_t("warn_past", lang)] if due < ctx.as_of else []

    actions = []
    if draft_allowed(bill):
        actions.append({"type": "add_to_payments", "label": _t("action", lang),
                        "draft": {"payee": bill.payee, "iban": bill.iban, "reference": bill.reference,
                                  "amount": _dump(amount_n), "due_date": due.isoformat()}})

    evidence.write(ctx.conn, nb.specs)
    return {
        "bill": {"source": bill.source, "payee": bill.payee, "iban": bill.iban_display,
                 "reference": bill.reference_display, "amount": _dump(amount_n), "due_date": due.isoformat()},
        "checks": {"iban": "pass" if bill.iban_ok else "fail", "reference": "pass" if bill.reference_ok else "fail",
                   "due_date": "past" if due < ctx.as_of else "pass"},
        "match": match,
        "comparison": comparison,
        "basket": basket,
        "safe_to_spend": safe_to_spend,
        "glossary": [{"term": term, "label": config.label(config.BILL_GLOSSARY[term][0], lang),
                      "text": config.label(config.BILL_GLOSSARY[term][1], lang)} for term in GLOSSARY_TERMS],
        "actions": actions,
        "warnings": warnings,
        "signals": signals,
    }


def _signal(code: str, lang: str, amount_n: Number, item: BillItem | None, largest: Number | None) -> dict[str, Any]:
    if code == "amount_above_usual" and item is not None:
        return {"code": code, "text": _t("sig_above_usual", lang, amount=amount_n.display,
                                         typical=item.typical_month.display),
                "numbers": [_dump(amount_n), _dump(item.typical_month)]}
    if code == "amount_above_usual":
        return {"code": code, "text": _t("sig_above_largest", lang, amount=amount_n.display, largest=largest.display),
                "numbers": [_dump(amount_n), _dump(largest)]}
    return {"code": code, "text": _t(f"sig_{code}", lang), "numbers": []}


def _safe_to_spend(ctx: ToolContext, nb: NumberBuilder, bill: BillInput, item: BillItem | None, amount_n: Number,
                   hero: Any) -> dict[str, Any]:
    """The bill applied to the balance side like a bill due before payday, and the hero's own computation
    (03) run again with it: free until payday and safe to spend, each before and after."""
    lang = ctx.language
    reg = ctx.numbers.register
    before, free_before, budget = hero.safe_to_spend, hero.free_until_payday, hero.budget_limit
    week, until_payday = hero.period, free_before.period
    reserved = item.due_until_payday if item is not None else None
    effect, counted_v = bill_effect(bill.due_date, hero.next_payday, bill.amount,
                                    _value(reserved) if reserved is not None else None)
    payday = _day(hero.next_payday, lang)
    out = {"effect": effect, "next_payday": hero.next_payday.isoformat(), "reserved": None, "counted": None,
           "free_until_payday_before": _dump(free_before), "free_until_payday_after": None,
           "before": _dump(before), "after": None}
    if effect == "after_payday":
        out["text"] = _t("effect_after_payday", lang, due=_day(bill.due_date, lang), payday=payday)
        return out

    on_payday = {"period": evidence.period_param(until_payday)}   # see on_due in explain_bill
    if effect == "excess_only":
        counted, _ = nb.composite(COUNTED, "excess", {"amount": (amount_n, bill.amount),
                                                       "reserved": (reserved, _value(reserved))},
                                  Unit.EUR, until_payday, _t("counted", lang), params=on_payday)
        out["reserved"] = _dump(reserved)
    else:
        counted, _ = nb.composite(COUNTED, "sum", {"amount": (amount_n, bill.amount)}, Unit.EUR, until_payday,
                                  _t("counted", lang), params=on_payday)
    free_after, free_after_v = nb.composite(FREE_AFTER, "difference",
                                            {"current": (free_before, _value(free_before)),
                                             "baseline": (counted, counted_v)},
                                            Unit.EUR, until_payday, _t("free_after", lang), params=on_payday)

    if counted_v > 0:
        # 03 itself, with the bill on top of the bills due: its own balance limit, never a subtraction
        settings = {**settings_for(ctx), EXTRA_SETTING: f"{counted_v:.2f}"}
        row = metric_sql.run_one(ctx.conn, config.SAFE_TO_SPEND_FILE, ctx.customer_id, ctx.as_of, settings)
        if row is None:
            raise NoTransactions("no transactions up to as_of for this customer")
        if metric_sql.decimal(row["free_until_payday_eur"]) != free_after_v:
            log.warning("free until payday of 03 with a bill differs from the bill's composite")
        balance_v = metric_sql.decimal(row["balance_limit_7d_eur"])
        spec = evidence.metric_spec(ctx.customer_id, ctx.as_of, BALANCE_LIMIT, config.SAFE_TO_SPEND_FILE,
                                    "balance_limit_7d_eur", settings, balance_v, evidence.period_param(week))
        balance = nb.number(balance_v, Unit.EUR, week, BALANCE_LIMIT, spec, _t("balance_after", lang))
    else:
        balance, balance_v = hero.balance_limit, _value(hero.balance_limit)
    budget_v = _value(budget)
    after, after_v = nb.composite(AFTER, "minimum", {"a": (balance, balance_v), "b": (budget, budget_v)},
                                  Unit.EUR, week, _t("after", lang), params={"period": evidence.period_param(week)})
    counted, free_after, after = reg(counted), reg(free_after), reg(after)
    out.update(counted=_dump(counted), free_until_payday_after=_dump(free_after), after=_dump(after))

    label = item.label if item is not None else ""
    if effect == "excess_only" and counted_v == 0:
        texts = [_t("effect_covered", lang, payday=payday, reserved=reserved.display, label=label)]
    elif effect == "excess_only":
        texts = [_t("effect_excess", lang, payday=payday, reserved=reserved.display, label=label,
                    counted=counted.display, free_before=free_before.display, free_after=free_after.display)]
    else:
        texts = [_t("effect_full", lang, payday=payday, free_before=free_before.display,
                    free_after=free_after.display)]
    # At most one more sentence, on the weekly number (contracts/api.md 11.2: at most two sentences in all).
    before_v = _value(before)
    if free_after_v < 0:
        texts.append(_t("sts_negative", lang, after=after.display))
    elif counted_v > 0 and after_v != before_v:
        texts.append(_t("sts_moves", lang, before=before.display, after=after.display))
    elif counted_v > 0 and budget_v <= balance_v:
        texts.append(_t("sts_budget", lang, before=before.display))
    out["text"] = " ".join(texts)
    return out
