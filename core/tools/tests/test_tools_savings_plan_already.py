"""#560 without a database: what already goes to savings, beside the savings plan. The recurring savings series'
own typical month (the bills tool's Number, the same method and evidence) and its share of the typical income; no
such series gives no Numbers; never added to the plan's total; never a peer metric."""

from __future__ import annotations

from datetime import date

import pytest

from core.tools import config
from core.tools import savings_plan as sp
from core.tools.context import ToolContext
from core.tools.models import Unit
from core.tools.peer import GetPeerBenchmarkArgs
from core.tools.tests.test_tools_savings_plan_pure import fake, num  # noqa: F401 - the shared fixture, used by name

SAVING = num("242.95", "ev_invest", "recurring.typical_month_eur@1")
SALARY = num("3171.65", "ev_salary", "recurring.typical_month_eur@1")


def plan(language="en"):
    ctx = ToolContext(customer_id="CUST00349", as_of=date(2026, 9, 30), conn=None, language=language)
    return sp.get_savings_plan(ctx, {}), ctx


@pytest.fixture
def state(request):
    """The pure tests' fake tools (what-if, safe to spend, S-Bonus, evidence store)."""
    return request.getfixturevalue("fake")


@pytest.fixture
def flows(monkeypatch):
    state = {"saving": [SAVING], "income": [SALARY]}
    monkeypatch.setattr(sp, "already_saving", lambda ctx: (state["saving"], state["income"]))
    return state


def test_the_series_own_number_and_its_share_of_income(state, flows):
    result, ctx = plan()
    d = result.data
    assert d.saving_seen is True
    assert (d.already_saving.value, d.already_saving.method, d.already_saving.evidence_ref) == (
        242.95, "recurring.typical_month_eur@1", "ev_invest")              # the bills tool's own Number
    assert (d.already_share.value, d.already_share.unit, d.already_share.method) == (
        7.7, Unit.PERCENT, "savings_plan.already_share_pct@1")
    spec = state.specs[d.already_share.evidence_ref]
    assert spec["formula"] == "share_pct"
    assert {p["role"]: p["ref"] for p in spec["parts"]} == {"part": "ev_invest", "whole": "ev_salary"}
    assert {"ev_invest", "ev_salary", d.already_share.evidence_ref} <= set(result.evidence)
    assert {d.already_saving.id, d.already_share.id} <= set(ctx.numbers.all())


def test_it_is_never_added_to_the_plan_total(state, flows):
    with_flow, _ = plan()
    flows["saving"] = []
    without, _ = plan()
    a, b = with_flow.data, without.data
    assert (a.total_month.value, a.total_year.value) == (b.total_month.value, b.total_year.value) == (63.17, 758.04)
    total_spec = state.specs[a.total_month.evidence_ref]
    assert "ev_invest" not in [p["ref"] for p in total_spec["parts"]]
    assert a.savings_goal.value == b.savings_goal.value                     # the goal is unchanged too
    assert [lv.saving.value for lv in a.levers] == [lv.saving.value for lv in b.levers]


def test_no_saving_series_gives_no_numbers(state, flows):
    flows["saving"] = []
    result, ctx = plan()
    d = result.data
    assert (d.saving_seen, d.already_saving, d.already_share) == (False, None, None)
    view = result.model_view
    assert (view["saving_seen"], view["already_saving"], view["already_share"]) == (False, None, None)
    assert len(ctx.numbers.all()) == 7                                     # the plan's own numbers only


def test_a_failing_read_leaves_the_plan_and_no_line(state, monkeypatch):
    monkeypatch.setattr(sp, "already_saving", lambda ctx: (_ for _ in ()).throw(RuntimeError("down")))
    d = plan()[0].data
    assert (d.saving_seen, d.already_saving, d.already_share) == (None, None, None)
    assert d.total_month.value == 63.17


def test_two_saving_series_are_one_sum_of_their_numbers(state, flows):
    flows["saving"] = [SAVING, num("50.00", "ev_fund", "recurring.typical_month_eur@1")]
    d = plan()[0].data
    assert d.already_saving.value == 292.95 and d.already_saving.method == "savings_plan.already_month_eur@1"
    spec = state.specs[d.already_saving.evidence_ref]
    assert spec["formula"] == "sum" and sorted(p["ref"] for p in spec["parts"]) == ["ev_fund", "ev_invest"]
    assert d.already_share.value == 9.2                                    # 292.95 / 3171.65


def test_no_income_series_gives_the_amount_without_a_share(state, flows):
    flows["income"] = []
    d = plan()[0].data
    assert d.already_saving.value == 242.95 and d.already_share is None


def test_the_model_view_gives_both_as_numbers(state, flows):
    view = plan("fi")[0].model_view
    assert view["saving_seen"] is True
    assert view["already_saving"]["value"] == 242.95 and view["already_share"]["value"] == 7.7
    assert view["already_saving"]["label"] == config.label(config.SAVINGS_PLAN_TEXT["already_month"], "fi")


def test_saving_is_never_a_peer_metric():
    # Product decision (14 Nov): saving is never compared with other customers.
    assert not set(config.SAVINGS_CATEGORIES) & set(config.PEER_METRICS)
    assert not any("sav" in m.lower() or "invest" in m.lower() for m in config.PEER_METRICS)
    for metric in (*config.SAVINGS_CATEGORIES, "saving", "savings_rate", "already_saving"):
        with pytest.raises(ValueError):
            GetPeerBenchmarkArgs.model_validate({"metric": metric})
