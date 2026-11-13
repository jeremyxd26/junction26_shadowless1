"""Build the peer-benchmark and store-index marts in batches of customers.

Usage:
    python core/marts/build.py                    # all 52 batches, CUST00000 .. CUST05200
    python core/marts/build.py --from CUST01200   # resume from a customer id
    python core/marts/build.py --dry-run          # list the batches, touch nothing

Reads DATABASE_URL (required) and DEMO_TODAY (default 2026-09-30) from the environment only, and
never prints DATABASE_URL. Creates the three mart tables if they are missing (core/marts/schema.sql),
then fills them for as_of = DEMO_TODAY, one batch of customers at a time:

- each batch is one transaction: delete the batch's rows for this as_of, then insert them again,
  so re-running a batch gives the same rows;
- every statement runs under statement_timeout = 60s and reads `transactions` only through the
  batch's customer range (never a whole-table aggregate);
- a batch that hits the timeout is split in half and each half is tried once; if a half times out
  too, or any other error happens, the script stops and names the range.

Design: docs/design/metrics.md, section 8. The classification SQL is not copied here: it is read
from the shared block in core/metrics/02_baskets.sql, so the marts always match metrics 1 to 6.
"""

from __future__ import annotations

import argparse
from datetime import date
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = Path(__file__).with_name("schema.sql")
BLOCK_SOURCE = ROOT / "core" / "metrics" / "02_baskets.sql"
FIRST, LAST = 0, 5200  # customer numbers; the data has CUST00001 .. CUST05100
DEFAULT_TODAY = "2026-09-30"


def cust(n: int) -> str:
    return f"CUST{n:05d}"


def cust_number(text: str) -> int:
    match = re.fullmatch(r"CUST(\d{5})", text)
    if not match:
        raise argparse.ArgumentTypeError(f"expected a customer id like CUST01200, got {text!r}")
    return int(match.group(1))


def shared_block() -> str:
    """The shared classification CTEs (params .. cls) from 02_baskets.sql, ending with a comma."""
    text = BLOCK_SOURCE.read_text(encoding="utf-8")
    match = re.search(r"^-- -+ shared classification block: begin -*$\n(.*?)^-- -+ shared classification block: end -*$",
                      text, re.S | re.M)
    if not match:
        sys.exit(f"shared classification block not found in {BLOCK_SOURCE}")
    return match.group(1)


# Insert statements. The customer range and as_of reach the shared block through the session
# settings app.customer_from / app.customer_to / app.demo_today, set locally for each transaction.
def customer_month_sql(block: str) -> str:
    return f"""
INSERT INTO metric_customer_month (as_of, customer_id, month, metric, value_eur, n_tx)
WITH
{block}
spend AS (
    SELECT c.customer_id, date_trunc('month', c.tx_date)::date AS month, u.metric, c.out_eur
    FROM cls c
    CROSS JOIN params p
    CROSS JOIN LATERAL (VALUES ('spend_total'), (c.basket), (c.category)) AS u (metric)
    WHERE c.flow = 'spend' AND c.tx_date BETWEEN p.win_start AND p.win_end
      AND u.metric <> 'Health'   -- R9: Health is never benchmarked, so it is not stored
)
SELECT (SELECT today FROM params), customer_id, month, metric, sum(out_eur), count(*)
FROM spend
GROUP BY customer_id, month, metric
"""


def peer_flags_sql(block: str) -> str:
    return f"""
INSERT INTO metric_peer_flags (as_of, customer_id, age_band, area3, city2, comparable, n_months)
WITH
{block}
months AS (   -- months covered by the customer's history inside the window (1..6), as in 02_baskets.sql
    SELECT c.customer_id,
           GREATEST(1, LEAST(6, (extract(year FROM age(p.win_end + 1, date_trunc('month', min(c.tx_date))))::int * 12
                                + extract(month FROM age(p.win_end + 1, date_trunc('month', min(c.tx_date))))::int))) AS n_months
    FROM cls c, params p
    GROUP BY c.customer_id, p.win_end
),
sweepers AS (   -- monthly Salary Sweep in at least 4 of the 6 months, as in 06_peer_benchmark.sql
    SELECT c.customer_id
    FROM cls c, params p
    WHERE c.flow = 'transfer' AND c.tx_date BETWEEN p.win_start AND p.win_end
    GROUP BY 1
    HAVING count(DISTINCT date_trunc('month', c.tx_date)) >= 4
)
SELECT p.today, cu.customer_id,
       CASE WHEN cu.age < 25 THEN '18-24' WHEN cu.age < 35 THEN '25-34' WHEN cu.age < 45 THEN '35-44'
            WHEN cu.age < 55 THEN '45-54' WHEN cu.age < 65 THEN '55-64' WHEN cu.age < 75 THEN '65-74'
            ELSE '75+' END,
       left(cu.postal_code, 3), left(cu.postal_code, 2),
       cu.customer_id NOT IN (SELECT customer_id FROM sweepers),
       m.n_months
FROM customers cu
JOIN months m USING (customer_id)
CROSS JOIN params p
WHERE cu.customer_id >= current_setting('app.customer_from')
  AND cu.customer_id <  current_setting('app.customer_to')
"""


GROCERY_CELLS_SQL = """
INSERT INTO metric_grocery_cells (as_of, customer_id, merchant_id, mcc, n, sy, syy, spend_eur)
SELECT current_setting('app.demo_today')::date, t.customer_id, t.merchant_id, max(t.mcc),
       count(*), sum(ln(-t.amount_eur)), sum(ln(-t.amount_eur) ^ 2), sum(-t.amount_eur)
FROM transactions t
WHERE t.customer_id >= current_setting('app.customer_from')
  AND t.customer_id <  current_setting('app.customer_to')
  AND t.tx_date <= current_setting('app.demo_today')::date
  AND t.tx_date >  current_setting('app.demo_today')::date - 365
  AND t.category = 'Groceries' AND t.merchant_id IS NOT NULL AND t.amount_eur < 0
GROUP BY t.customer_id, t.merchant_id
"""

TABLES = ("metric_customer_month", "metric_peer_flags", "metric_grocery_cells")


class BuildError(Exception):
    pass


def run_range(conn, lo: int, hi: int, as_of: str, inserts: list[str]) -> list[int]:
    """Rebuild one customer range in one transaction. Returns rows inserted per table."""
    with conn.transaction():
        conn.execute("SELECT set_config('app.demo_today', %s, true), set_config('app.customer_from', %s, true),"
                     " set_config('app.customer_to', %s, true)", (as_of, cust(lo), cust(hi)))
        for table in TABLES:
            conn.execute(f"DELETE FROM {table} WHERE as_of = %s AND customer_id >= %s AND customer_id < %s",
                         (as_of, cust(lo), cust(hi)))
        return [conn.execute(sql).rowcount for sql in inserts]


def build_batch(conn, psycopg, lo: int, hi: int, as_of: str, inserts: list[str]) -> list[int]:
    try:
        return run_range(conn, lo, hi, as_of, inserts)
    except psycopg.errors.QueryCanceled:
        mid = (lo + hi) // 2
        print(f"  {cust(lo)}-{cust(hi)} hit the statement timeout; retrying as two halves", flush=True)
        totals = [0] * len(inserts)
        for a, b in ((lo, mid), (mid, hi)):
            try:
                counts = run_range(conn, a, b, as_of, inserts)
            except psycopg.errors.QueryCanceled:
                raise BuildError(f"range {cust(a)}-{cust(b)} timed out again after the split") from None
            totals = [t + c for t, c in zip(totals, counts)]
        return totals


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the peer-benchmark and store-index marts in batches.")
    parser.add_argument("--from", dest="start", type=cust_number, default=FIRST,
                        help="first customer id of the first batch (default CUST00000)")
    parser.add_argument("--to", dest="end", type=cust_number, default=LAST,
                        help="end of the last batch, exclusive (default CUST05200)")
    parser.add_argument("--batch", type=int, default=100, help="customers per batch (default 100)")
    parser.add_argument("--pause", type=float, default=1.0, help="seconds to wait between batches (default 1)")
    parser.add_argument("--dry-run", action="store_true", help="print the batches and exit; no database access")
    parser.add_argument("--timeout-ms", type=int, default=60000,
                        help="statement timeout for the batch statements in ms, at most 60000 (default 60000); "
                             "a small value is only for testing the split-and-retry path")
    args = parser.parse_args()
    if not 0 < args.timeout_ms <= 60000:
        parser.error("--timeout-ms must be between 1 and 60000")
    if args.batch < 1:
        parser.error("--batch must be at least 1")
    if args.start >= args.end:
        parser.error(f"--from ({cust(args.start)}) must come before --to ({cust(args.end)})")

    as_of = os.environ.get("DEMO_TODAY") or DEFAULT_TODAY
    try:
        date.fromisoformat(as_of)
    except ValueError:
        sys.exit("DEMO_TODAY must be a date like 2026-09-30")
    batches = [(lo, min(lo + args.batch, args.end)) for lo in range(args.start, args.end, args.batch)]
    print(f"as_of {as_of}: {len(batches)} batches of up to {args.batch} customers, "
          f"{cust(args.start)} to {cust(args.end)}", flush=True)

    if args.dry_run:
        for i, (lo, hi) in enumerate(batches, 1):
            print(f"  batch {i:>2}/{len(batches)}  {cust(lo)} <= customer_id < {cust(hi)}")
        return

    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set in the environment")

    import psycopg  # imported here so that --dry-run works without the driver

    block = shared_block()
    inserts = [customer_month_sql(block), peer_flags_sql(block), GROCERY_CELLS_SQL]
    started = time.time()
    durations: list[tuple[float, str]] = []
    # Driver error messages can contain parts of the connection string (a malformed DATABASE_URL is
    # echoed back, password included), so no driver message is ever printed: only the class name.
    try:
        conn = psycopg.connect(url, autocommit=True, application_name="marts-build")
    except Exception as e:
        sys.exit(f"stopped: could not connect ({type(e).__name__}); check DATABASE_URL")
    current = "schema setup"
    try:
        with conn:
            conn.execute("SET statement_timeout = '60s'")
            conn.execute(SCHEMA.read_text(encoding="utf-8"))
            conn.execute(f"SET statement_timeout = {int(args.timeout_ms)}")
            for i, (lo, hi) in enumerate(batches, 1):
                current = f"batch {i}/{len(batches)} {cust(lo)}-{cust(hi)}"
                t0 = time.time()
                counts = build_batch(conn, psycopg, lo, hi, as_of, inserts)
                dt = time.time() - t0
                durations.append((dt, f"{cust(lo)}-{cust(hi)}"))
                print(f"batch {i:>2}/{len(batches)}  {cust(lo)}-{cust(hi)}  "
                      f"customer_month {counts[0]:>6}  peer_flags {counts[1]:>4}  grocery_cells {counts[2]:>5}  "
                      f"{dt:5.1f}s", flush=True)
                if i < len(batches):
                    time.sleep(args.pause)

            current = "final row counts"
            print(f"done: {len(batches)} batches in {time.time() - started:.0f}s; "
                  f"slowest {max(durations)[1]} {max(durations)[0]:.1f}s", flush=True)
            for table in TABLES:
                n = conn.execute(f"SELECT count(*) FROM {table} WHERE as_of = %s", (as_of,)).fetchone()[0]
                print(f"  {table:24} {n:>8} rows for as_of {as_of}")
    except BuildError as e:
        sys.exit(f"stopped: {e}")
    except psycopg.Error as e:
        sys.exit(f"stopped at {current} after {len(durations)} completed batches: {type(e).__name__} "
                 f"(SQLSTATE {getattr(e, 'sqlstate', None) or 'none'}); the driver's message is not printed")


if __name__ == "__main__":
    main()
