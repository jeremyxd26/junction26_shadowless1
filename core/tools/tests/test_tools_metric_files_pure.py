"""Checks on the metric SQL files themselves (no database).

03_safe_to_spend_bills.sql is the per-bill output of 03_safe_to_spend.sql (metrics.md section 3.2). Its
text from `SET statement_timeout` up to the end-of-shared-part marker must be identical to 03's, so each
per-bill row is exactly one term of 03's `bills_due_eur`. A change to that part of 03 (for example to the
shared classification block) must be copied into the per-bill file as well.
"""

import re
from pathlib import Path

METRICS = Path(__file__).resolve().parents[2] / "metrics"
MARKER = "-- ---- end of the part shared with 03_safe_to_spend_bills.sql"


def shared_part(file_name: str) -> str:
    text = (METRICS / file_name).read_text(encoding="utf-8")
    start = re.search(r"^SET statement_timeout", text, re.M).start()  # the statement, not a comment
    end = text.index("\n", text.index(MARKER)) + 1
    return text[start:end]


def test_per_bill_file_shares_03_up_to_the_bill_items():
    shared = shared_part("03_safe_to_spend.sql")
    assert "bill_items AS (" in shared and "-- ---- shared classification block: begin" in shared
    assert shared_part("03_safe_to_spend_bills.sql") == shared


def test_03_sums_the_same_bill_items():
    text = (METRICS / "03_safe_to_spend.sql").read_text(encoding="utf-8")
    after = text[text.index(MARKER):]
    assert "sum(i.bill_due_eur)" in after and "LEFT JOIN bill_items i" in after


def test_per_bill_file_returns_one_statement_result():
    """metric_sql.run keeps the last result set, so the per-bill file has exactly one SELECT at the end."""
    text = (METRICS / "03_safe_to_spend_bills.sql").read_text(encoding="utf-8")
    code = "\n".join(line.split("--")[0] for line in text.splitlines())  # comments removed
    assert code.count(";") == 2  # SET statement_timeout; and the one WITH ... SELECT
    assert code.rstrip().endswith(";") and "SELECT i.customer_id" in code


# Every file that carries the shared classification block (params .. cls). core/marts/build.py takes its
# copy from 02, so a block that is the same here is also the one the marts are built with.
BLOCK_FILES = ("02_baskets.sql", "03_safe_to_spend.sql", "03_safe_to_spend_bills.sql", "04_what_if.sql",
               "05_spender_profile.sql", "06_peer_benchmark.sql")
BLOCK = re.compile(r"^-- -+ shared classification block: begin -*$\n(.*?)^-- -+ shared classification block: end",
                   re.S | re.M)


def shared_block(file_name: str) -> str:
    match = BLOCK.search((METRICS / file_name).read_text(encoding="utf-8"))
    assert match, f"{file_name}: shared classification block not found"
    return match.group(1)


def test_shared_classification_block_is_identical_in_all_six_files():
    blocks = {f: shared_block(f) for f in BLOCK_FILES}
    assert sorted(p.name for p in METRICS.glob("*.sql") if BLOCK.search(p.read_text(encoding="utf-8"))) == \
        sorted(BLOCK_FILES)                                   # no copy is missed when a file is added
    reference = blocks["02_baskets.sql"]
    assert [f for f, b in blocks.items() if b != reference] == []


def test_marts_build_reads_the_same_block():
    import importlib.util

    spec = importlib.util.spec_from_file_location("marts_build", METRICS.parent / "marts" / "build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    assert build.shared_block() == shared_block("02_baskets.sql")
