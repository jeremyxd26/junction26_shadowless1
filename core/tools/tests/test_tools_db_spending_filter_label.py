"""#399 on the database, the lead persona CUST00860 only: the sum of Housing and Restaurants in September 2026 is
labelled and explained as that filter, never as total spending. Skipped without DATABASE_URL. Read only, except
the evidence specs every tool writes."""

from __future__ import annotations

from datetime import date

import pytest

from core.app.api import evidence as evidence_api
from core.tools import evidence
from core.tools.context import ToolContext
from core.tools.spending import get_spending

AS_OF = date(2026, 9, 30)
LEAD = "CUST00860"
SEPTEMBER = {"preset": "custom", "start": "2026-09-01", "end": "2026-09-30"}


@pytest.mark.parametrize("language,label", [("en", "Housing and restaurants"), ("fi", "Asuminen ja ravintolat")])
def test_the_two_category_sum_is_named_in_its_label_card_and_evidence_title(conn, language, label):
    ctx = ToolContext(customer_id=LEAD, as_of=AS_OF, conn=conn, language=language)
    result = get_spending(ctx, {"period": SEPTEMBER, "filter": {"categories": ["Housing", "Restaurants"]}})
    total = result.data.total
    assert total.label == label and result.card.title == label
    res = evidence.resolve(conn, total.evidence_ref, LEAD)
    assert res.reconciles is True
    view = evidence_api.build(conn, res, LEAD, language)
    assert view.title.startswith(label + ", ") and view.number.value == total.value
    # the month's own total is a different, larger number, labelled as all spending
    everything = get_spending(ToolContext(customer_id=LEAD, as_of=AS_OF, conn=conn, language=language),
                              {"period": SEPTEMBER}).data.total
    assert everything.value > total.value and everything.label in ("Spending", "Kulutus")


@pytest.mark.parametrize("language", ["en", "fi"])
def test_a_category_with_a_merchant_is_named_alike_in_the_number_and_the_evidence_title(conn, language):
    # #501: the evidence title of a filter across dimensions equals the Number label, the merchant by its alias
    from core.tools import aliases
    ctx = ToolContext(customer_id=LEAD, as_of=AS_OF, conn=conn, language=language)
    history = ctx.history()
    restaurant = next(t.merchant_id for t in reversed(history) if t.category == "Restaurants" and t.merchant_id)
    alias = aliases.build(history, AS_OF).for_merchant(restaurant)
    result = get_spending(ctx, {"period": {"preset": "last_6_months"},
                                "filter": {"categories": ["Restaurants"], "merchant": alias.key}})
    total = result.data.total
    connector = " kauppiaalla " if language == "fi" else " at "
    assert total.label == ("Ravintolat" if language == "fi" else "Restaurants") + connector + alias.label(language)
    assert result.card.title == total.label
    res = evidence.resolve(conn, total.evidence_ref, LEAD, language=language)
    assert res.reconciles is True
    view = evidence_api.build(conn, res, LEAD, language)
    assert view.title.startswith(total.label + ", ") and view.number.label == total.label
