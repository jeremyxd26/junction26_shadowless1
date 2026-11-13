"""Load the S-Pankki synthetic dataset into PostgreSQL.

Usage:
    python core/ingest/load.py data/s-pankki

Reads DATABASE_URL from the environment, or from a .env file in the repository root.
Re-runnable: recreates the tables (schema.sql) and loads everything again.
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = Path(__file__).with_name("schema.sql")
CHUNK = 1 << 20  # 1 MiB
TS_FORMAT = "DDMONYY:HH24:MI:SS"  # e.g. 03OCT24:09:04:04

# Staging tables mirror the CSV headers exactly; everything is text until it is cast.
STAGING = {
    "stg_transactions": (
        "tx_junction_transactions.csv",
        "customer_id, bank_account_id, tx_date, tx_timestamp, category, tx_amount_eur, "
        "balance_after_eur, transaction_type, merchant_id, mcc_code",
    ),
    "stg_customers": (
        "tx_customers_junction.csv",
        "customer_id, customer_postal_code, customer_age",
    ),
    "stg_mortgage_applications": (
        "mtg_tx_customer_link_and_final_mtg_infio.csv",
        "mortgage_customer_id, customer_id, final_decision, rejection_reason, "
        "final_property_price_eur, final_requested_loan_eur, final_equity_amount_eur, "
        "final_collateral_value_eur, required_monthly_income_eur, lfinal_loan_to_value",
    ),
    "stg_mortgage_events": (
        "mtg_negotiation_history.csv",
        "mortgage_customer_id, timestamp, event_type, property_id, property_type, "
        "property_price_estimate, loan_amount, equity_amount, collateral_type, collateral_value, "
        "collateral_status, decision, rejection_reason, expense_type, expense_amount, note",
    ),
}

TRANSFORM = f"""
INSERT INTO customers (customer_id, postal_code, age)
SELECT customer_id, customer_postal_code, customer_age::int FROM stg_customers;

INSERT INTO transactions (customer_id, account_id, tx_date, tx_at, category, amount_eur,
                          balance_after, tx_type, merchant_id, mcc)
SELECT customer_id, bank_account_id, tx_date::date, to_timestamp(tx_timestamp, '{TS_FORMAT}')::timestamp,
       category, tx_amount_eur::numeric, NULLIF(balance_after_eur, '')::numeric, transaction_type,
       NULLIF(merchant_id, ''), NULLIF(mcc_code, '')
FROM stg_transactions;

INSERT INTO mortgage_applications
SELECT mortgage_customer_id, customer_id, final_decision, NULLIF(rejection_reason, ''),
       NULLIF(final_property_price_eur, '')::numeric, NULLIF(final_requested_loan_eur, '')::numeric,
       NULLIF(final_equity_amount_eur, '')::numeric, NULLIF(final_collateral_value_eur, '')::numeric,
       NULLIF(required_monthly_income_eur, '')::numeric, NULLIF(lfinal_loan_to_value, '')::numeric
FROM stg_mortgage_applications;

INSERT INTO mortgage_events (mortgage_customer_id, event_at, event_type, property_id, property_type,
    property_price_estimate, loan_amount, equity_amount, collateral_type, collateral_value,
    collateral_status, decision, rejection_reason, expense_type, expense_amount, note)
SELECT mortgage_customer_id, to_timestamp(timestamp, '{TS_FORMAT}')::timestamp, event_type,
       NULLIF(property_id, ''), NULLIF(property_type, ''), NULLIF(property_price_estimate, '')::numeric,
       NULLIF(loan_amount, '')::numeric, NULLIF(equity_amount, '')::numeric, NULLIF(collateral_type, ''),
       NULLIF(collateral_value, '')::numeric, NULLIF(collateral_status, ''), NULLIF(decision, ''),
       NULLIF(rejection_reason, ''), NULLIF(expense_type, ''), NULLIF(expense_amount, '')::numeric,
       NULLIF(note, '')
FROM stg_mortgage_events;
"""

INDEXES = """
CREATE INDEX tx_customer_time     ON transactions (customer_id, tx_at);
CREATE INDEX tx_customer_category ON transactions (customer_id, category, tx_date);
CREATE INDEX tx_customer_mcc      ON transactions (customer_id, mcc, tx_date) WHERE mcc IS NOT NULL;
CREATE INDEX mortgage_apps_customer ON mortgage_applications (customer_id);
CREATE INDEX mortgage_events_app    ON mortgage_events (mortgage_customer_id, event_at);
ANALYZE;
"""

EXPECTED = {
    "transactions": 3_626_755,
    "customers": 5_100,
    "mortgage_applications": 200,
    "mortgage_events": 3_452,
}


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url and (ROOT / ".env").exists():
        match = re.search(r"^DATABASE_URL=(.+)$", (ROOT / ".env").read_text(encoding="utf-8"), re.M)
        url = match.group(1).strip().strip("\"'") if match else None
    if not url:
        sys.exit("DATABASE_URL is not set (environment or .env)")
    return url


def copy_csv(conn: psycopg.Connection, table: str, path: Path, columns: str) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {table}")
    cols = ", ".join(f"{c.strip()} text" for c in columns.split(","))
    conn.execute(f"CREATE UNLOGGED TABLE {table} ({cols})")
    size = path.stat().st_size
    sent = 0
    with conn.cursor() as cur, cur.copy(
        f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')"
    ) as copy, path.open("rb") as f:
        while chunk := f.read(CHUNK):
            copy.write(chunk)
            sent += len(chunk)
            if sent % (50 * CHUNK) < CHUNK:
                print(f"  {path.name}: {sent * 100 // size}%", flush=True)


def main() -> None:
    data_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "data/s-pankki")
    for _, (name, _) in STAGING.items():
        if not (data_dir / name).exists():
            sys.exit(f"missing {data_dir / name}")

    started = time.time()
    with psycopg.connect(database_url(), autocommit=True) as conn:
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
        for table, (name, columns) in STAGING.items():
            print(f"copy {name}", flush=True)
            copy_csv(conn, table, data_dir / name, columns)
        print("transform", flush=True)
        conn.execute(TRANSFORM)
        for table in STAGING:
            conn.execute(f"DROP TABLE {table}")
        print("indexes", flush=True)
        conn.execute(INDEXES)

        ok = True
        for table, expected in EXPECTED.items():
            got = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            ok &= got == expected
            print(f"{table:24} {got:>10,}  {'ok' if got == expected else f'EXPECTED {expected:,}'}")
        size = conn.execute("SELECT pg_size_pretty(pg_database_size(current_database()))").fetchone()[0]
        print(f"database size {size}, took {time.time() - started:.0f}s")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
