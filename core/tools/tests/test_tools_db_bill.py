"""explain_bill on the shared database (#242), for the lead persona CUST00860 only. Skipped without
DATABASE_URL. Read only, except the evidence specs that every tool writes; SPIKE_REVIEWS is off (conftest),
so no label is read. The bills are r-w1's sample bills 2 and 3 (#249): a utilities bill clearly higher than
usual, due before payday, and a bill from a payee that is not a regular bill, due in two days."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from core.app.api.schemas import BillExplainResponse
from core.tools import bill_explain as be
from core.tools import evidence
from core.tools.bills import get_recurring_bills
from core.tools.context import ToolContext
from core.tools.safe_to_spend import get_safe_to_spend

AS_OF = date(2026, 9, 30)
LEAD = "CUST00860"


def context(conn, lang: str = "en") -> ToolContext:
    return ToolContext(customer_id=LEAD, as_of=AS_OF, conn=conn, language=lang)


def explain(conn, bill, lang: str = "en") -> dict:
    out = be.explain_bill(context(conn, lang), bill)
    BillExplainResponse.model_validate({"customer_id": LEAD, "as_of": AS_OF, "language": lang, **out})
    return out


def d(number: dict) -> Decimal:
    return Decimal(str(number["value"]))


def reconciles(conn, ref: str) -> evidence.Resolution:
    res = evidence.resolve(conn, ref, LEAD)
    assert res.reconciles is True, ref
    return res


def numbers(obj):
    if isinstance(obj, dict):
        if {"value", "unit", "method", "display", "evidence_ref"} <= set(obj):
            yield obj
        for v in obj.values():
            yield from numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from numbers(v)


def every_number_opens(conn, out: dict, lang: str) -> int:
    """Each Number with a ref opens through the evidence endpoint's builder, with its own value and display."""
    from core.app.api import evidence as evidence_api

    opened = 0
    for n in numbers(out):
        if n["evidence_ref"] is None:
            continue
        view = evidence_api.build(conn, evidence.resolve(conn, n["evidence_ref"], LEAD), LEAD, lang)
        assert (view.number.value, view.number.display) == (n["value"], n["display"]), n["method"]
        opened += 1
    return opened


@pytest.mark.parametrize("lang", ["en", "fi"])
def test_a_matching_bill_higher_than_usual_due_before_payday(conn, lang):
    utilities = next(i for i in get_recurring_bills(context(conn), {"include_income": False}).data.bills
                     if i.bill_id == "bill_utilities_payment")
    bill = be.read_fields("Esimerkki Energia Oy", "FI21 1234 5600 0007 85", "1232", "312.70", date(2026, 10, 13))
    out = explain(conn, bill, lang)
    sts, cmp = out["safe_to_spend"], out["comparison"]
    assert out["match"]["status"] == "matched" and out["match"]["bill_id"] == "bill_utilities_payment"
    assert cmp["baseline"]["evidence_ref"] == utilities.typical_month.evidence_ref
    assert d(cmp["change"]) == Decimal("312.70") - Decimal(str(utilities.typical_month.value))
    reserved = Decimal(str(utilities.due_until_payday.value))
    assert sts["effect"] == "excess_only" and d(sts["reserved"]) == reserved > 0
    assert d(sts["counted"]) == Decimal("312.70") - reserved
    assert d(sts["free_until_payday_after"]) == d(sts["free_until_payday_before"]) - d(sts["counted"])

    hero = get_safe_to_spend(context(conn, lang), {}).data              # the same refs as the hero's
    assert sts["before"]["evidence_ref"] == hero.safe_to_spend.evidence_ref
    assert sts["free_until_payday_before"]["evidence_ref"] == hero.free_until_payday.evidence_ref
    assert hero.binding_limit == "budget" and d(sts["after"]) == d(sts["before"])   # the budget limit binds
    assert [s["code"] for s in out["signals"]] == ["amount_above_usual"]
    assert out["actions"] and out["warnings"] == []

    # "How?": every computed number reconciles; the balance limit with the bill re-runs 03 with the setting
    for key in ("counted", "free_until_payday_after"):
        reconciles(conn, sts[key]["evidence_ref"])
    reconciles(conn, cmp["change"]["evidence_ref"])
    after = reconciles(conn, sts["after"]["evidence_ref"])
    balance = reconciles(conn, after.parts[0]["ref"])
    assert balance.kind == "metric" and balance.spec["source"]["settings"]["extra_bill_due_eur"] == f"{d(sts['counted']):.2f}"
    assert after.parts[1]["ref"] == hero.budget_limit.evidence_ref
    assert every_number_opens(conn, out, lang) >= 9


def test_the_bill_setting_never_leaks_into_the_next_run_of_03_in_one_transaction(conn):
    from core.tools import metric_sql

    def free(settings):
        return metric_sql.run_one(conn, "03_safe_to_spend.sql", LEAD, AS_OF, settings)["free_until_payday_eur"]

    base = {"cushion_eur": "100"}
    alone = free(base)
    with conn.transaction(force_rollback=True):
        with_bill = free({**base, "extra_bill_due_eur": "145.00"})
        assert with_bill == alone - Decimal("145.00")
        assert free(base) == alone                     # the hero after a bill, in the same transaction


@pytest.mark.parametrize("lang", ["en", "fi"])
def test_a_bill_from_an_unknown_payee_due_in_two_days(conn, lang):
    bill = be.read_fields("Esimerkki Remontti Oy", "FI71 1234 5600 0098 76", "12344", "486.00", date(2026, 10, 2))
    out = explain(conn, bill, lang)
    sts = out["safe_to_spend"]
    assert out["match"]["status"] == "not_matched" and out["comparison"] is None
    assert out["basket"]["key"] == "unexpected_necessities"
    assert sts["effect"] == "full" and d(sts["counted"]) == Decimal("486.00") and sts["reserved"] is None
    assert d(sts["free_until_payday_after"]) == d(sts["free_until_payday_before"]) - Decimal("486.00")
    assert [s["code"] for s in out["signals"]] == ["new_payee", "short_term"]
    reconciles(conn, sts["after"]["evidence_ref"])
    reconciles(conn, sts["counted"]["evidence_ref"])
    assert every_number_opens(conn, out, lang) >= 5
