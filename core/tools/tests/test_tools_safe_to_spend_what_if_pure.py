"""Pure-logic tests for get_safe_to_spend and run_what_if (no database)."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.tools import evidence, metric_sql
from core.tools.context import ToolContext
from core.tools.db import Tx
from core.tools.formatting import money
from core.tools.safe_to_spend import binding_limit, status_of
from core.tools.what_if import RunWhatIfArgs, WhatIfSelection, caveats_for, run_what_if

D = Decimal


# ---- safe to spend: which limit binds, status thresholds (03_safe_to_spend.sql) --------------------

def test_binding_limit_is_the_smaller_one_and_balance_on_a_tie():
    assert binding_limit(D("1644.29"), D("103.18")) == "budget"
    assert binding_limit(D("92.62"), D("110.31")) == "balance"
    assert binding_limit(D("50.00"), D("50.00")) == "balance"   # 03: balance_limit <= budget_limit


@pytest.mark.parametrize("safe, usual, expected", [
    ("0.00", "87.92", "nothing_free"),
    ("-5.00", "10.00", "nothing_free"),
    ("31.35", "11.47", "ok"),
    ("103.18", "91.80", "ok"),
    ("50.00", "91.80", "below_usual"),
    ("91.80", "91.80", "ok"),        # equal to the usual week is not below it
])
def test_status_thresholds(safe, usual, expected):
    assert status_of(D(safe), D(usual)) == expected


def test_minimum_formula_equals_rounding_the_smaller_limit():
    # min of two cent values is itself a cent value: min(round(a), round(b)) == round(min(a, b))
    assert evidence.compute_formula("minimum", {"a": D("1644.29"), "b": D("103.18")}) == D("103.18")
    assert evidence.compute_formula("minimum", {"a": D("0.00"), "b": D("-1.59")}) == D("-1.59")


def test_components_add_up_to_free_until_payday_within_a_cent():
    # metrics.md section 3, CUST00001: each value is rounded on its own (contracts/api.md 2.1)
    balance, bills, essentials, irregular, cushion = D("4723.58"), D("586.32"), D("312.55"), D("201.23"), D("100")
    free_until_payday = D("3523.49")
    assert abs(money(balance - bills - essentials - irregular - cushion) - free_until_payday) <= D("0.01")


def test_metric_spec_is_stable_and_records_its_source():
    spec = evidence.metric_spec("CUST00001", date(2026, 9, 30), "safe_to_spend.balance_eur@1",
                                "03_safe_to_spend.sql", "balance_eur", {"cushion_eur": "100"}, D("4723.58"))
    assert spec["kind"] == "metric" and spec["source"]["column"] == "balance_eur"
    again = evidence.metric_spec("CUST00001", date(2026, 9, 30), "safe_to_spend.balance_eur@1",
                                 "03_safe_to_spend.sql", "balance_eur", {"cushion_eur": "100"}, D("4723.58"))
    assert evidence.make_ref(spec) == evidence.make_ref(again)


def test_customer_range_holds_exactly_one_customer():
    assert metric_sql.customer_range("CUST00001") == ("CUST00001", "CUST00002")
    assert metric_sql.customer_range("CUST00099") == ("CUST00099", "CUST00100")
    with pytest.raises(ValueError):
        metric_sql.customer_range("CUST1' OR '1'='1")


def test_metric_runner_refuses_paths_outside_core_metrics():
    with pytest.raises(ValueError):
        metric_sql.run(None, "../ingest/schema.sql", "CUST00001", date(2026, 9, 30))


# ---- what-if arguments (contracts/api.md section 8.1, R9) ------------------------------------------

def test_health_category_is_rejected():
    with pytest.raises(ValidationError, match="R9"):
        WhatIfSelection(kind="category", value="Health")


def test_health_mcc_is_rejected():
    with pytest.raises(ValidationError, match="R9"):
        WhatIfSelection(kind="mcc", value="4121,5912")


@pytest.mark.parametrize("value", ["Salary", "Invest Deposit", "Salary Sweep", "Other Income", "Coffee"])
def test_only_spending_categories(value):
    with pytest.raises(ValidationError):
        WhatIfSelection(kind="category", value=value)


def test_mcc_codes_are_checked_and_normalised():
    assert WhatIfSelection(kind="mcc", value="5812, 4121,4121").value == "4121,5812"
    for bad in ("", "41", "4121;5812", "abcd"):
        with pytest.raises(ValidationError):
            WhatIfSelection(kind="mcc", value=bad)


def test_basket_and_merchant_values():
    assert WhatIfSelection(kind="basket", value="everyday_spending").value == "everyday_spending"
    with pytest.raises(ValidationError):
        WhatIfSelection(kind="basket", value="savings")
    assert WhatIfSelection(kind="merchant", value="store_b").value == "store_b"
    for bad in ("MRC-GRO-0032", "store_1", "Store_A"):
        with pytest.raises(ValidationError):
            WhatIfSelection(kind="merchant", value=bad)


@pytest.mark.parametrize("cut", [0, 101, -5])
def test_cut_must_be_1_to_100(cut):
    with pytest.raises(ValidationError):
        RunWhatIfArgs.model_validate({"selection": {"kind": "category", "value": "Restaurants"}, "cut_pct": cut})


def test_no_customer_field_in_arguments():
    with pytest.raises(ValidationError):
        RunWhatIfArgs.model_validate({"selection": {"kind": "category", "value": "Restaurants"}, "cut_pct": 20,
                                      "customer_id": "CUST00002"})


def test_caveats_follow_the_status():
    assert len(caveats_for("estimate", "en")) == 1
    assert "unexpected necessities" in caveats_for("estimate_with_caveat", "en")[1]
    assert "Regular essentials are not cut" in caveats_for("not_offered", "en")[1]


# ---- #55 review follow-ups -------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["١٢٣٤", "４１２１", "4121,٥٨١٢"])
def test_mcc_codes_must_be_ascii_digits(bad):
    """A \\d pattern would also accept Arabic-Indic or full-width digits; MCC codes are ASCII only."""
    with pytest.raises(ValidationError):
        WhatIfSelection(kind="mcc", value=bad)


def test_merchant_with_a_health_mcc_is_rejected():
    """R9 for a merchant selection also uses the health MCC list, not only the category."""
    pharmacy = Tx(id=1, tx_date=date(2026, 9, 1), tx_at=datetime(2026, 9, 1, 12, 0), category="Lifestyle",
                  tx_type="purchase", merchant_id="MRC-X-0001", mcc="5912", amount_eur=Decimal("-20.00"))
    ctx = ToolContext(customer_id="CUST00001", as_of=date(2026, 9, 30), conn=None, _history=[pharmacy])
    with pytest.raises(ValueError, match="R9"):  # refused before any SQL runs (conn is None)
        run_what_if(ctx, {"selection": {"kind": "merchant", "value": "store_a"}, "cut_pct": 10})


@pytest.mark.parametrize("name", ["demo_today", "customer_from", "customer_to", "customer_anything"])
def test_metric_runner_refuses_reserved_settings(name):
    """The customer range and as_of come only from run()'s arguments, never from a caller's settings."""
    with pytest.raises(ValueError, match="reserved"):
        metric_sql.run(None, "03_safe_to_spend.sql", "CUST00001", date(2026, 9, 30), {name: "CUST00000"})
