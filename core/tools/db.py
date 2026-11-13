"""Database access for the tools: one connection, a 60 s statement timeout, per-customer reads.

Every query in core/tools is parameterised and restricted to one customer and to tx_date <= as_of.
Nothing here aggregates the whole `transactions` table. The only table the tools create or write
is `coach_evidence` (evidence specs).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]

STATEMENT_TIMEOUT = "60s"

EVIDENCE_DDL = """
CREATE TABLE IF NOT EXISTS coach_evidence (
    ref         text PRIMARY KEY,
    customer_id text NOT NULL,
    spec        jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
)
"""


def database_url(required: bool = True) -> str | None:
    """DATABASE_URL from the environment, else from the repository's .env. Never printed."""
    url = os.environ.get("DATABASE_URL")
    env_file = ROOT / ".env"
    if not url and env_file.exists():
        match = re.search(r"^DATABASE_URL=(.+)$", env_file.read_text(encoding="utf-8"), re.M)
        url = match.group(1).strip().strip("\"'") if match else None
    if not url and required:
        raise RuntimeError("DATABASE_URL is not set (environment or .env)")
    return url or None


def connect() -> psycopg.Connection:
    """Open the single connection the tools use, with the statement timeout set."""
    conn = psycopg.connect(database_url(), autocommit=True)
    conn.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'")
    return conn


def ensure_evidence_table(conn: psycopg.Connection) -> None:
    """Create coach_evidence if it does not exist. The only DDL the tools run."""
    conn.execute(EVIDENCE_DDL)


@dataclass(frozen=True)
class Tx:
    """One transaction of the customer, as read from the database."""

    id: int
    tx_date: date
    tx_at: datetime
    category: str
    tx_type: str
    merchant_id: str | None
    mcc: str | None
    amount_eur: Decimal  # bank sign: negative = money out


TX_SQL = """
SELECT id, tx_date, tx_at, category, tx_type, merchant_id, mcc, amount_eur
FROM transactions
WHERE customer_id = %(customer_id)s
  AND tx_date <= %(as_of)s
ORDER BY tx_date, tx_at, id
"""


def load_transactions(conn: psycopg.Connection, customer_id: str, as_of: date) -> list[Tx]:
    """All of one customer's transactions up to as_of (about 700 rows), via tx_customer_time."""
    rows = conn.execute(TX_SQL, {"customer_id": customer_id, "as_of": as_of}).fetchall()
    return [Tx(*row) for row in rows]
