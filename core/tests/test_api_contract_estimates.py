"""#380, the contract side: the estimate examples match the model field by field, and every `estimate` in every
example of contracts/api.md says what it observed and what it assumes. No database."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_api_contract import examples, mismatches  # noqa: E402

from core.app.api import schemas  # noqa: E402
from core.tools.models import ASSUMPTION_CODES  # noqa: E402

# estimate-only examples for the kinds that have no card example (contracts/api.md section 3, Estimates)
ESTIMATE_EXAMPLES = sorted(n for n in examples() if n.startswith("estimate."))


def test_there_is_one_estimate_example_per_kind_without_a_card_example():
    assert {"estimate.bonus", "estimate.forecast", "estimate.savings_plan"} <= set(ESTIMATE_EXAMPLES)   # dev: the plan


@pytest.mark.parametrize("name", ESTIMATE_EXAMPLES)
def test_estimate_example_matches_the_model_field_by_field(name):
    raw = examples()[name]
    assert mismatches(schemas.Estimate.model_validate(raw), raw) == []


def estimates_in(name: str, raw) -> list[tuple[str, str | None, dict]]:
    """(example, card type, estimate) for every estimate of an example."""
    if name.startswith("estimate."):
        return [(name, None, raw)]
    out = []

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("estimate"), dict):
                out.append((name, o.get("type"), o["estimate"]))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(raw)
    return out


def test_every_example_estimate_says_what_it_observed_and_what_it_assumes():
    found = [e for name, raw in examples().items() for e in estimates_in(name, raw)]
    assert len(found) >= 15                     # the stores example has `estimate: null` until a tool builds it
    for name, card_type, est in found:
        assert {"observed", "assumptions"} <= set(est), name
        assert card_type != "stores", name
        assert est["observed"] and est["assumptions"], name
        for a in est["assumptions"]:
            assert a["code"] in ASSUMPTION_CODES, (name, a["code"])
            assert not re.search(r"[0-9]", a["text"]), (name, a["text"])
            assert a["value"] is None or {"value", "unit", "method", "display"} <= set(a["value"]), name
