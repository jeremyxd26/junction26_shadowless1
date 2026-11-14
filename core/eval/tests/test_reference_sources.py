"""The reference source knows every number source of the eval set (#466). No database.

The reference run stopped at the first savings-plan case (#411) with KeyError 'total_month_eur', and no case
after it was scored. This walks every number and forbid item of core/eval/cases.yaml and asks the reference
source for its method id, so a new kind of source cannot stop the run again unnoticed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sources import SAVINGS_PLAN_METHODS, method_of  # noqa: E402

from core.app.api import texts  # noqa: E402
from core.tools import config as tools_config  # noqa: E402

CASES = yaml.safe_load((Path(__file__).resolve().parents[1] / "cases.yaml").read_text(encoding="utf-8"))
ITEMS = [(case["id"], kind, item) for case in CASES["cases"] for kind in ("numbers", "forbid")
         for item in case.get(kind) or [] if "source" in item]


@pytest.mark.parametrize("case_id,kind,item", ITEMS, ids=[f"{c}:{k}:{i['name']}" for c, k, i in ITEMS])
def test_the_reference_source_knows_every_number_source(case_id, kind, item):
    method = method_of(item["source"])
    assert isinstance(method, str) and method.endswith("@1"), (case_id, item["name"])


def test_every_query_of_the_eval_set_is_covered():
    queries = {item["source"].get("query") for _, _, item in ITEMS} - {None}
    assert {"savings_plan", "bonus"} <= queries      # the kinds the run stopped at, and its neighbour
    for _, _, item in ITEMS:
        for part in item["source"].get("plus") or []:   # each part of a forbidden sum is a known source too
            assert method_of(part).endswith("@1")


def test_the_savings_plan_sources_name_the_tools_own_methods():
    assert method_of({"query": "savings_plan", "column": "total_month_eur"}) == \
        tools_config.SAVINGS_PLAN_METHODS["total_month"]
    assert method_of({"query": "savings_plan", "column": "total_year_eur"}) == \
        tools_config.SAVINGS_PLAN_METHODS["total_year"]
    assert method_of({"query": "savings_plan", "column": "total_month_eur",
                      "plus": [{"metric": "safe_to_spend", "column": "safe_to_save_monthly_eur"}]}) == \
        "savings_plan.total_month_eur@1"
    assert set(SAVINGS_PLAN_METHODS.values()) <= set(texts.METHODS)   # each has a name and a unit
