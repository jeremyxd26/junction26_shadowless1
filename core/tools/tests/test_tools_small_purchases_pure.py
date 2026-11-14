"""get_small_purchases without a database (#256): the definition, its boundaries, the numbers and their
evidence, the card and the model view."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.tools import config
from core.tools.classify import classify
from core.tools.context import ToolContext
from core.tools.db import Tx
from core.tools.evidence import compute_formula
from core.tools.selection import Selection, select, value_of
from core.tools.small_purchases import GetSmallPurchasesArgs, get_small_purchases
from core.tools.tests.test_tools_safe_to_save_pure import FakeStore

AS_OF = date(2026, 9, 30)            # last full month: August 2026
AUG = date(2026, 8, 1)


def tx(i, d, category, amount, tx_type="purchase", merchant=None, mcc=None):
    return Tx(i, d, datetime.combine(d, datetime.min.time()), category, tx_type, merchant, mcc, Decimal(amount))


def august(*rows):
    """(category, amount) pairs as purchases on consecutive August days, ids from 1."""
    return [tx(i, date(2026, 8, 1 + i % 28), cat, amount) for i, (cat, amount) in enumerate(rows, start=1)]


def run(history, language="en", labels=None, **args):
    store = FakeStore()
    ctx = ToolContext(customer_id="CUST00001", as_of=AS_OF, conn=store, language=language, _history=history)
    if labels is not None:
        ctx._labels = labels
    return get_small_purchases(ctx, args), store, ctx


FIVE = [("Restaurants", "-4.50"), ("Restaurants", "-3.20"), ("Entertainment", "-9.00"),
        ("Lifestyle", "-6.30"), ("Restaurants", "-2.00")]


def test_the_default_is_the_last_three_complete_months_and_ten_euros():
    """Coordinator, #256: one month holds too few small purchases for any persona; three months and EUR 10."""
    args = GetSmallPurchasesArgs.model_validate({})
    assert (args.period.preset.value, args.max_amount) == ("last_3_months", 10.0)
    june, september = tx(80, date(2026, 6, 30), "Restaurants", "-3.00"), tx(90, date(2026, 9, 3), "Restaurants", "-3.00")
    result, _, _ = run(august(*FIVE) + [june, september])                      # June: out; September: in
    d = result.data
    assert (d.period.start, d.period.end) == (date(2026, 7, 1), date(2026, 9, 30))
    assert (d.count.value, d.total.value, d.average.value) == (6, 28.0, 4.67)
    assert d.max_amount.value == 10.0 and d.max_amount.method == "small_purchases.max_amount_eur@1"


def test_the_month_average_is_the_total_over_whole_months_only():
    result, store, _ = run(august(*FIVE, ("Restaurants", "-0.01")))         # 25.01 / 3 = 8.336...
    m = result.data.month_average
    assert (m.value, m.unit.value, m.method, m.display) == (8.34, "eur_per_month", "small_purchases.month_avg_eur@1",
                                                            "€8.34 a month")
    spec = store.rows[m.evidence_ref]
    assert spec["formula"] == "scale" and spec["params"] == {"factor_num": 1, "factor_den": 3}
    # one month: the average would only repeat the total, so there is none, in the data, the view or the card (#465)
    for preset in ("last_month", "this_month"):                              # 1-30 Sep is whole: one month too
        one, _, _ = run(august(*FIVE), period={"preset": preset})
        assert one.data.month_average is None and one.model_view["per_month"] is None, preset
        assert "small_purchases.month_avg_eur@1" not in one.card.model_dump_json(), preset
    two, _, _ = run(august(*FIVE), period={"preset": "custom", "start": "2026-07-01", "end": "2026-08-31"})
    assert two.data.month_average.value == 12.5                              # two whole months: 25.00 / 2
    odd, _, _ = run(august(*FIVE), period={"preset": "custom", "start": "2026-08-03", "end": "2026-08-31"})
    assert odd.data.month_average is None                                    # not whole months: no average
    assert odd.model_view["per_month"] is None


def test_exactly_the_limit_counts_a_cent_more_does_not():
    result, _, _ = run(august(*FIVE, ("Restaurants", "-10.00"), ("Restaurants", "-10.01")))
    assert (result.data.count.value, result.data.total.value) == (6, 35.0)
    lower, _, _ = run(august(*FIVE, ("Restaurants", "-4.99"), ("Restaurants", "-5.00"), ("Restaurants", "-5.01")),
                      max_amount=5)
    assert lower.data.count.value == 5                      # 4.50 3.20 2.00 4.99 5.00; 9.00 6.30 5.01 are over
    assert lower.data.total.value == 19.69
    assert lower.data.max_amount.display == "€5.00"


def test_a_refund_is_not_a_purchase_but_lowers_everyday_spending():
    result, _, _ = run(august(*FIVE, ("Restaurants", "5.00")) + [tx(50, AUG, "Restaurants", "-40.00")])
    d = result.data
    assert d.count.value == 5 and d.total.value == 25.0                    # the refund is not counted
    assert d.flexible_total.value == 60.0                                   # 25 + 40 - 5 (netted, as the baskets)
    assert d.share.value == 41.7                                            # 25 / 60


def test_only_the_flexible_everyday_categories_and_never_bills_or_subscriptions():
    netflix = [tx(100 + m, date(2026, m, 12), "Entertainment", "-9.99", merchant="m_stream") for m in range(4, 10)]
    others = [tx(200 + i, date(2026, 8, 20), cat, amount) for i, (cat, amount) in enumerate(
        [("Groceries", "-3.00"), ("Travel", "-4.00"), ("Health", "-5.00"), ("Transportation", "-2.80")])]
    result, _, ctx = run(august(*FIVE) + netflix + others)
    rows = classify(ctx.history(), AS_OF)
    assert {c.basket for c in rows if c.tx.merchant_id == "m_stream"} == {"regular_essentials"}   # a subscription
    assert result.data.count.value == 5                     # groceries, travel, health, transport, the stream: out
    assert config.SMALL_PURCHASE_CATEGORIES == ("Entertainment", "Lifestyle", "Restaurants")


def test_a_purchase_the_customer_labelled_elsewhere_is_not_flexible():
    history = august(*FIVE, ("Restaurants", "-7.00"))
    result, _, _ = run(history, labels={6: "unexpected_necessities"})
    assert result.data.count.value == 5


def test_zero_purchases_and_fewer_than_five():
    none, _, _ = run([tx(1, AUG, "Groceries", "-30.00")])
    d = none.data
    assert (d.count.value, d.total.value, d.average, d.few, d.categories) == (0, 0.0, None, True, [])
    assert d.share is None                                  # no everyday spending at all
    assert [a.type for a in none.card.actions] == ["open_evidence"]          # nothing to cut
    assert none.model_view["takeaway"] == {"kind": "none", "largest_category": None}
    four, _, _ = run(august(*FIVE[:4]))
    assert four.data.few and four.model_view["takeaway"]["kind"] == "few"
    five, _, _ = run(august(*FIVE))
    assert not five.data.few and five.model_view["takeaway"] == {"kind": "summary", "largest_category": "Restaurants"}


def test_categories_largest_first_with_their_share_of_the_small_total():
    result, _, _ = run(august(*FIVE))
    items = [(c.key, c.amount.value, c.share.value) for c in result.data.categories]
    assert items == [("Restaurants", 9.7, 38.8), ("Entertainment", 9.0, 36.0), ("Lifestyle", 6.3, 25.2)]


def test_every_number_is_evidence_backed_and_reproducible():
    result, store, ctx = run(august(*FIVE, ("Travel", "-80.00")))
    rows = classify(ctx.history(), AS_OF, {})
    d = result.data
    for n in (d.count, d.total, d.flexible_total, *(c.amount for c in d.categories)):
        spec = store.rows[n.evidence_ref]
        assert spec["kind"] == "transactions" and spec["method"].startswith("small_purchases.")
        sel = Selection.from_spec(spec["selection"])
        assert value_of(select(rows, sel), sel, spec["method"]) == Decimal(spec["value"])
    count_spec = store.rows[d.count.evidence_ref]["selection"]
    assert len(count_spec["tx_ids"]) == 5 and count_spec["baskets"] == ["everyday_spending"]
    for n in (d.average, d.share, d.max_amount, *(c.share for c in d.categories)):
        spec = store.rows[n.evidence_ref]
        parts = {p["role"]: Decimal(store.rows[p["ref"]]["value"]) for p in spec["parts"]}
        assert compute_formula(spec["formula"], parts, spec.get("params")) == Decimal(spec["value"])
    assert d.flexible_total.value == 105.0 and d.share.value == 23.8        # travel is everyday spending


def test_the_card_is_the_breakdown_card_and_asks_the_what_if_without_an_amount():
    result, _, _ = run(august(*FIVE))
    card = result.card
    assert (card.type, card.display_hint, card.title, card.subtitle) == ("breakdown", "list", "Small purchases",
                                                                         "1 Jul – 30 Sep 2026")
    assert card.total.method == "small_purchases.total_eur@1" and card.comparison is None
    assert [i["key"] for i in card.items] == ["Restaurants", "Entertainment", "Lifestyle"]
    assert all(i["change"] is None and i["flags"] == [] for i in card.items)
    show, ask = card.actions
    assert (show.type, show.evidence_ref) == ("open_evidence", card.total.evidence_ref)
    assert (ask.type, ask.prompt) == ("ask", "What if I cut restaurants?")
    fi, _, _ = run(august(*FIVE), language="fi")
    assert fi.card.actions[1].prompt == "Mitä jos vähentäisin kulutusta luokassa Ravintolat?"
    assert fi.card.title == "Pienet ostokset" and fi.data.total.display == "25,00 €"


def test_the_model_view_has_numbers_and_labels_only():
    result, _, _ = run(august(*FIVE) + [tx(9, AUG, "Restaurants", "-3.00", merchant="m_secret")])
    view = result.model_view
    text = repr(view)
    assert "m_secret" not in text and "ev_" not in text and "CUST" not in text
    assert set(view) == {"tool", "period", "period_preset", "max_amount", "count", "total", "average", "per_month",
                         "share_of_everyday", "everyday_total", "categories", "takeaway", "notes"}
    assert view["count"]["value"] == 6 and view["categories"][0]["label"] == "Restaurants"


@pytest.mark.parametrize("bad", [0.5, 25.01, 30, -1])
def test_max_amount_is_one_to_twenty_five_euros(bad):
    with pytest.raises(ValidationError):
        GetSmallPurchasesArgs.model_validate({"max_amount": bad})
    assert GetSmallPurchasesArgs.model_validate({"max_amount": 25}).max_amount == 25


def test_another_period_and_a_note_when_it_is_clamped():
    history = august(*FIVE) + [tx(60, date(2026, 9, 2), "Restaurants", "-3.00")]
    this_month, _, _ = run(history, period={"preset": "this_month"})
    assert this_month.data.count.value == 1 and this_month.data.few
    clamped, _, _ = run(history, period={"preset": "custom", "start": "2026-09-01", "end": "2026-10-31"})
    assert clamped.data.period.end == AS_OF and clamped.notes
