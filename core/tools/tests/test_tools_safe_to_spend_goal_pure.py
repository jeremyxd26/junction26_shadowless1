"""#459: the savings goal of 03_safe_to_spend.sql is computed as with no labels, in every review state.

For that the goal needs each row's basket by the rules, labels ignored. The shared classification block (in six
files) gives only the labelled basket, so `cls_rules` carries a copy of the rule CASE of `cls`. These tests keep the
copy byte-identical to the original, keep it outside the shared block, and check that the goal's CTEs read the
rules' basket and leave out only the first review's purchase. No database."""

from __future__ import annotations

from pathlib import Path

FILE = Path(__file__).resolve().parents[2] / "metrics" / "03_safe_to_spend.sql"


def text() -> str:
    return FILE.read_text(encoding="utf-8").replace("\r\n", "\n")


def rule_case_of_cls(s: str) -> str:
    start = s.index("           COALESCE(o.basket,\n") + len("           COALESCE(o.basket,\n")
    end = s.index("END) AS basket,", start)
    return s[start:end]


def rule_case_of_cls_rules(s: str) -> str:
    block = s[s.index("cls_rules AS ("):]
    start = block.index("    SELECT x.*,\n") + len("    SELECT x.*,\n")
    end = block.index("END AS rule_basket", start)
    return block[start:end]


def test_the_copy_of_the_rule_case_equals_the_original_byte_for_byte():
    s = text()
    original, copy = rule_case_of_cls(s), rule_case_of_cls_rules(s)
    assert original.strip().startswith("CASE") and "ELSE 'unclassified'" in original
    assert copy == original


def test_the_copy_is_outside_the_shared_block_and_read_only_by_the_goal():
    s = text()
    end_of_shared = s.index("-- ---- shared classification block: end")
    assert s.index("cls_rules AS (") > end_of_shared
    # the goal's two CTEs read it; nothing else does
    users = [line for line in s.split("\n") if "FROM cls_rules" in line]
    assert len(users) == 2


def test_the_goal_reads_the_rules_basket_and_leaves_out_only_the_first_purchase():
    s = text()
    review = s[s.index("review_purchase AS ("):s.index("run_rates_before AS (")]
    rates = s[s.index("run_rates_before AS ("):s.index("-- Safe to save (metrics.md 3.1)")]
    assert "c.rule_basket IN ('unexpected_necessities', 'everyday_spending')" in review
    assert "overridden" not in review and "overridden" not in rates          # labels play no part
    assert "c.basket" not in rates and rates.count("c.rule_basket") == 3
    assert "c.id IS DISTINCT FROM rp.tx_id" in rates
