"""Argument validation, evidence refs, aliases, formatting and classification. No database."""

import re
from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.tools import aliases, config, evidence
from core.tools.classify import classify
from core.tools.db import Tx
from core.tools.formatting import display
from core.tools.models import Unit
from core.tools.selection import Selection
from core.tools.spending import GetSpendingArgs


# ---- argument validation -------------------------------------------------------------------------

def test_valid_args_and_defaults():
    a = GetSpendingArgs.model_validate({"period": {"preset": "last_month"}, "filter": {"mcc_groups": ["taxi"]}})
    assert (a.direction.value, a.group_by.value, a.compare_to.value, a.top_n) == ("out", "none", "none", 5)


@pytest.mark.parametrize("payload", [
    {"period": {"preset": "next_month"}},                                        # unknown preset
    {"period": {"preset": "last_month"}, "filter": {"categories": ["Taxi"]}},    # unknown category
    {"period": {"preset": "last_month"}, "filter": {"mcc_groups": ["bars"]}},    # unknown MCC group
    {"period": {"preset": "last_month"}, "group_by": "day"},
    {"period": {"preset": "last_month"}, "compare_to": "last_decade"},
    {"period": {"preset": "last_month"}, "direction": "sideways"},
    {"period": {"preset": "last_month"}, "top_n": 11},
    {"period": {"preset": "last_month"}, "filter": {"merchant": "MRC-GRO-0035"}},  # ids are not aliases
    {"period": {"preset": "last_month"}, "filter": {"merchant": "store_1"}},       # aliases have no digits
    {"period": {"preset": "last_month"}, "filter": {"merchant": "x'; DROP TABLE transactions; --"}},
])
def test_invalid_args_are_rejected(payload):
    with pytest.raises(ValidationError):
        GetSpendingArgs.model_validate(payload)


@pytest.mark.parametrize("payload", [
    {"period": {"preset": "last_month"}, "customer_id": "CUST00002"},
    {"period": {"preset": "last_month"}, "filter": {"customer_id": "CUST00002"}},
    {"period": {"preset": "last_month", "customer_id": "CUST00002"}},
])
def test_customer_id_in_args_is_rejected(payload):
    with pytest.raises(ValidationError):
        GetSpendingArgs.model_validate(payload)


def test_json_schema_has_no_customer_field():
    schema = GetSpendingArgs.model_json_schema()
    assert "customer" not in str(schema).lower()


# ---- evidence refs ---------------------------------------------------------------------------------

SEL = Selection(direction="out", start=date(2026, 8, 1), end=date(2026, 8, 31), mcc_groups=("taxi",))


def test_ref_is_stable_and_pinned():
    spec = evidence.transactions_spec("CUST00001", date(2026, 9, 30), "spending.total@1", SEL, Decimal("42.10"))
    ref = evidence.make_ref(spec)
    assert re.fullmatch(r"ev_[0-9a-f]{12}", ref)
    assert ref == evidence.make_ref(dict(reversed(list(spec.items()))))   # key order does not matter
    # Golden value: sha256 of the canonical JSON below. It changes only if the spec format changes,
    # which would orphan every stored ref, so a change here must be deliberate.
    assert evidence.canonical_json(spec) == (
        '{"as_of":"2026-09-30","customer_id":"CUST00001","kind":"transactions","method":"spending.total@1",'
        '"selection":{"baskets":[],"categories":[],"direction":"out","group":null,"mcc_groups":["taxi"],'
        '"merchant_id":null,"period":{"end":"2026-08-31","start":"2026-08-01"}},"v":1,"value":"42.10"}'
    )
    assert ref == "ev_94520607c689"


def test_ref_changes_with_customer_method_value_and_as_of():
    def ref(**kw):
        args = dict(customer_id="CUST00001", as_of=date(2026, 9, 30), method="spending.total@1", sel=SEL,
                    value=Decimal("42.10"))
        args.update(kw)
        return evidence.make_ref(evidence.transactions_spec(**args))

    refs = {ref(), ref(customer_id="CUST00002"), ref(method="spending.n_tx@1"), ref(value=Decimal("42.11")),
            ref(as_of=date(2026, 9, 14))}
    assert len(refs) == 5


def test_composite_formulas():
    v = {"current": Decimal("2315.60"), "baseline": Decimal("1948.20")}
    assert evidence.compute_formula("difference", v) == Decimal("367.40")
    assert evidence.compute_formula("pct_change", v) == Decimal("18.9")
    assert evidence.compute_formula("share_pct", {"part": Decimal("1"), "whole": Decimal("3")}) == Decimal("33.3")


# ---- aliases -------------------------------------------------------------------------------------

def tx(i, d, category, amount, merchant=None, mcc=None, tx_type="purchase"):
    return Tx(i, d, datetime.combine(d, datetime.min.time()), category, tx_type, merchant, mcc, Decimal(amount))


def test_aliases_rank_by_spend_and_have_no_digits():
    history = [
        tx(1, date(2026, 9, 1), "Groceries", "-10.00", "MRC-GRO-0035", "5411"),
        tx(2, date(2026, 9, 2), "Restaurants", "-30.00", "MRC-RES-0112", "5812"),
        tx(3, date(2026, 9, 3), "Transportation", "-20.00", "MRC-TRN-0007", "4121"),
        tx(4, date(2026, 10, 3), "Groceries", "-999.00", "MRC-GRO-0099", "5411"),  # after as_of: ignored
    ]
    amap = aliases.build(history, date(2026, 9, 30))
    assert amap.keys() == ["store_a", "store_b", "store_c"]
    assert amap.merchant_id("store_a") == "MRC-RES-0112"
    labels = [amap.for_merchant(m).label(lang) for m in ("MRC-RES-0112", "MRC-TRN-0007", "MRC-GRO-0035")
              for lang in ("en", "fi")]
    assert labels == ["Restaurant A", "Ravintola A", "Taxi B", "Taksi B", "Grocery store C", "Ruokakauppa C"]
    assert not any(ch.isdigit() for text in labels + amap.keys() for ch in text)
    with pytest.raises(KeyError):
        amap.merchant_id("store_z")


def test_alias_letters_past_z():
    assert [aliases.letters(n) for n in (1, 26, 27, 52, 53, 702, 703)] == ["a", "z", "aa", "az", "ba", "zz", "aaa"]


# ---- formatting ------------------------------------------------------------------------------------

def test_display():
    assert display(Decimal("1234.5"), Unit.EUR) == "€1,234.50"
    assert display(Decimal("1234.5"), Unit.EUR, "fi") == "1 234,50 €"
    assert display(Decimal("-24.5"), Unit.EUR) == "-€24.50"
    assert display(Decimal("18.94"), Unit.PERCENT) == "18.9%"
    assert display(Decimal("18.95"), Unit.PERCENT, "fi") == "19,0 %"
    assert display(Decimal("14"), Unit.COUNT) == "14"


# ---- classification (metrics.md section 1) ---------------------------------------------------------

def test_basket_rules_and_one_off():
    as_of = date(2026, 9, 30)
    history = [tx(i, date(2026, 9, 1 + i % 20), "Groceries", "-20.00", f"MRC-GRO-{i:04d}", "5411")
               for i in range(1, 11)]                                                   # 10 purchases, median 20
    history += [
        tx(20, date(2026, 9, 25), "Groceries", "-150.00", "MRC-GRO-0001", "5411"),      # > 5 x 20: one-off
        tx(21, date(2026, 9, 25), "Transportation", "-30.00", "MRC-TRN-0001", "4121"),  # taxi
        tx(22, date(2026, 9, 25), "Transportation", "-3.00", "MRC-TRN-0002", "4111"),   # public transport
        tx(23, date(2026, 9, 4), "Housing", "-800.00", tx_type="housing_payment"),
        tx(24, date(2026, 9, 5), "Health", "-12.00", "MRC-HEA-0001", "5912"),
        tx(25, date(2026, 9, 6), "Restaurants", "-25.00", "MRC-RES-0001", "5812"),
        tx(26, date(2026, 9, 15), "Salary", "2500.00", tx_type="salary"),
        tx(27, date(2026, 9, 18), "Invest Deposit", "-200.00", tx_type="investment_deposit"),
    ]
    by_id = {c.tx.id: c for c in classify(history, as_of)}
    assert by_id[1].basket == "regular_essentials" and not by_id[1].is_one_off
    assert by_id[20].is_one_off and by_id[20].basket == "unexpected_necessities"
    assert by_id[21].basket == "everyday_spending" and by_id[21].mcc_group == "taxi"
    assert by_id[22].basket == "regular_essentials" and by_id[22].mcc_group == "public_transport"
    assert by_id[23].basket == "regular_essentials"
    assert by_id[24].basket == "unexpected_necessities" and by_id[24].mcc_group == "health"
    assert by_id[25].basket == "everyday_spending"
    assert (by_id[26].flow, by_id[26].basket) == ("income", None)
    assert (by_id[27].flow, by_id[27].basket) == ("saving", None)


def test_mcc_groups_cover_disjoint_codes():
    codes = [c for group in config.MCC_GROUPS.values() for c in group]
    assert len(codes) == len(set(codes))
    assert "Invest Withdraw" not in config.INCOME_CATEGORIES   # metrics.md section 2.3
