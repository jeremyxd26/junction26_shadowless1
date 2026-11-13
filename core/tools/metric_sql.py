"""Run a metric SQL file of core/metrics/ for exactly one customer, the single source of truth.

The metric files read their inputs from session settings (`app.demo_today`, `app.customer_from`,
`app.customer_to`, plus file-specific ones such as `app.whatif`), so a tool sets them for one
customer, runs the file unchanged and gets the same numbers the metrics document shows. The settings
are local to one transaction, so they never leak into the next query on the shared connection.

Every read inside the files is restricted to the customer range and to tx_date <= as_of; nothing
here aggregates the whole `transactions` table and nothing is created.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg

METRICS_DIR = Path(__file__).resolve().parents[1] / "metrics"
CUSTOMER_ID = re.compile(r"^CUST(\d{5})$")
SETTING_NAME = re.compile(r"^[a-z_]+$")


def customer_range(customer_id: str) -> tuple[str, str]:
    """[customer_id, next id): the half-open range that holds exactly this customer."""
    match = CUSTOMER_ID.fullmatch(customer_id)
    if not match:
        raise ValueError(f"unexpected customer id format: {customer_id!r}")
    return customer_id, f"CUST{int(match.group(1)) + 1:05d}"


def run(conn: psycopg.Connection, file: str, customer_id: str, as_of: date,
        settings: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Run core/metrics/<file> for one customer and return the rows of its last result set."""
    if "/" in file or "\\" in file or not file.endswith(".sql"):
        raise ValueError(f"not a metric file name: {file!r}")
    sql = (METRICS_DIR / file).read_text(encoding="utf-8")
    lo, hi = customer_range(customer_id)
    values = {"demo_today": as_of.isoformat(), "customer_from": lo, "customer_to": hi, **(settings or {})}
    with conn.transaction():
        for name, value in values.items():
            if not SETTING_NAME.fullmatch(name):
                raise ValueError(f"bad setting name {name!r}")
            conn.execute("SELECT set_config(%s, %s, true)", (f"app.{name}", str(value)))
        cur = conn.cursor()
        cur.execute(sql)  # the file's own statements, unchanged
        rows: list[dict[str, Any]] = []
        while True:
            if cur.description:
                cols = [d.name for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            if not cur.nextset():
                break
    return rows


def run_one(conn: psycopg.Connection, file: str, customer_id: str, as_of: date,
            settings: dict[str, str] | None = None) -> dict[str, Any] | None:
    """The single row of a per-customer metric file, or None when the file returns no row."""
    rows = [r for r in run(conn, file, customer_id, as_of, settings) if r.get("customer_id") == customer_id]
    if len(rows) > 1:
        raise RuntimeError(f"{file} returned {len(rows)} rows for one customer")
    return rows[0] if rows else None


def decimal(value: Any) -> Decimal:
    """A metric column as Decimal (numeric columns arrive as Decimal; ints and floats are converted)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
