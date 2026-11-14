"""Every tool's model view, for every persona, on the shared database (#487, the review of #484). Skipped
without DATABASE_URL.

The model view is what the language model is given. It holds no customer id, no account number, no merchant
id, no evidence ref, no transaction row, no age band and no postal area (the peer card keeps its group label).
A new tool whose arguments have no defaults makes this test fail until its arguments are added to ARGS.
"""

from __future__ import annotations

import json
import re
from datetime import date

import pytest

from core.agent.toolset import default_registry
from core.tools.context import ToolContext

AS_OF = date(2026, 9, 30)
PERSONAS = ["CUST00860", "CUST00493", "CUST00349", "CUST00849"]
ARGS = {
    "get_spending": {"period": {"preset": "last_month"}},
    "get_basket_breakdown": {"period": {"preset": "last_6_months"}},
    "run_what_if": {"selection": {"kind": "category", "value": "Restaurants"}, "cut_pct": 20},
    "get_peer_benchmark": {"metric": "spend_total"},
}
REGISTRY = default_registry()
FORBIDDEN_KEYS = re.compile(r'"(?:rows|tx_id|transaction_id|merchant_id|iban|account_number|customer_id|bill_id|'
                            r'evidence_ref)"')
AGE_BAND = re.compile(r"\b(?:1[89]|[2-9]\d)-[2-9]\d\b(?![-\d])")


@pytest.mark.parametrize("customer_id", PERSONAS)
@pytest.mark.parametrize("name", sorted(REGISTRY.tools))
def test_a_model_view_holds_nothing_the_model_must_not_see(conn, name, customer_id):
    _, args = REGISTRY.parse(name, ARGS.get(name, {}))
    result = REGISTRY.tools[name].fn(ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn, language="en"), args)
    text = json.dumps(result.model_view, default=str, ensure_ascii=False)
    assert customer_id not in text and "CUST" not in text, text
    assert "MRC-" not in text and "ev_" not in text, text                   # merchant ids, evidence refs (R3)
    assert not re.search(r"\bFI\d{2}\s?\d{4}", text), text                  # no account number
    assert not FORBIDDEN_KEYS.search(text), text                           # no rows, ids or refs
    assert not AGE_BAND.search(text), text                                 # no age band such as 35-44
    group = getattr(result.card, "peer_group", None) if result.card is not None else None
    if isinstance(group, dict) and group.get("label"):
        # The card keeps the group label; the model gets neither it nor its age band or area digits. (The
        # estimate sentence may say "people of your age band in your area" in words: no values.)
        assert group["label"] not in text
        for value in re.findall(r"\d[\d-]*", group["label"]):
            assert value not in text, (value, text)
