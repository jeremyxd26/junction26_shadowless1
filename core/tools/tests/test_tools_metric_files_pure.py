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
