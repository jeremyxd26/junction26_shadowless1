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
from psycopg import pq

METRICS_DIR = Path(__file__).resolve().parents[1] / "metrics"
CUSTOMER_ID = re.compile(r"CUST([0-9]{5})")
SETTING_NAME = re.compile(r"[a-z_]+")
# Set by run() itself from its arguments; a caller's settings may never override them (the customer
# range and as_of decide which rows a metric file reads).
RESERVED_SETTINGS = frozenset({"demo_today", "customer_from", "customer_to"})


def is_reserved_setting(name: str) -> bool:
    """A name that would set the customer range or as_of. PostgreSQL setting names are not case
    sensitive (`app.Customer_from` is `app.customer_from`), so the check ignores case and surrounding
    whitespace (#122); evidence.resolve uses it for stored specs as well."""
    key = str(name).strip().lower()
    return key in RESERVED_SETTINGS or key.startswith("customer_")


BILL_AMOUNT = re.compile(r"[0-9]{1,6}\.[0-9]{2}")   # euros with cents, ASCII digits
BILL_AMOUNT_MAX = Decimal("100000.00")


def _bill_amount(value: str) -> bool:
    """More than 0 and at most 100,000.00, written with exactly two decimals."""
    return bool(BILL_AMOUNT.fullmatch(value)) and Decimal(0) < Decimal(value) <= BILL_AMOUNT_MAX


# Settings with a declared type and bound: their value is checked here before anything runs, for a tool's
# settings and for a stored evidence spec alike, and a value that fails is refused, never repaired. The
# value reaches PostgreSQL only as a bound parameter of set_config, never spliced into the SQL.
# - extra_bill_due_eur (03_safe_to_spend.sql, #242): a bill the customer showed, due before payday.
TYPED_SETTINGS = {"extra_bill_due_eur": _bill_amount}


def check_settings(settings: dict[str, str] | None) -> None:
    """Refuse a reserved or malformed setting name, or a typed setting's value out of its bound, before
    anything touches the database."""
    for name, value in (settings or {}).items():
        if is_reserved_setting(name):
            raise ValueError(f"setting {name!r} is reserved: run() sets it from its arguments")
        if not isinstance(name, str) or not SETTING_NAME.fullmatch(name):
            raise ValueError(f"bad setting name {name!r}")
        if name in TYPED_SETTINGS and not TYPED_SETTINGS[name](str(value)):
            raise ValueError(f"setting {name!r} is out of its bound")


def customer_range(customer_id: str) -> tuple[str, str]:
    """[customer_id, next id): the half-open range that holds exactly this customer."""
    match = CUSTOMER_ID.fullmatch(customer_id)
    if not match:
        raise ValueError(f"unexpected customer id format: {customer_id!r}")
    return customer_id, f"CUST{int(match.group(1)) + 1:05d}"


def run(conn: psycopg.Connection, file: str, customer_id: str, as_of: date,
        settings: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Run core/metrics/<file> for one customer and return the rows of its last result set.

    On an idle connection (the tools' and the API's connections are in autocommit mode) the file runs
    in its own READ ONLY transaction, so nothing in it can write. Inside a caller's open transaction it
    runs in a savepoint instead and the caller's transaction mode is left as it is: a read-only setting
    made in a savepoint would stay in force for the rest of the caller's transaction.
    """
    if "/" in file or "\\" in file or not file.endswith(".sql"):
        raise ValueError(f"not a metric file name: {file!r}")
    check_settings(settings)
    sql = (METRICS_DIR / file).read_text(encoding="utf-8")
    lo, hi = customer_range(customer_id)
    # The caller's settings first and the customer range and as_of last, in the sequence of set_config
    # calls as well as in value: a later set_config of the same name wins in PostgreSQL, so the
    # server's values win even if a name ever slipped past check_settings (defence in depth, #122).
    # tx_labels (#68) comes before everything: the customer's labels as JSON, passed by the caller
    # (core.tools.labels.metric_settings) so its evidence spec records them; empty means none, so a
    # session-level value can never leak in. The typed settings are reset the same way (#242): a
    # transaction-local set_config inside a caller's open transaction stays set until that transaction
    # ends, so a bill's extra_bill_due_eur would otherwise reach the next run of 03 in it (the hero).
    server = [("demo_today", as_of.isoformat()), ("customer_from", lo), ("customer_to", hi)]
    resets = [("tx_labels", "")] + [(name, "") for name in TYPED_SETTINGS]
    values = resets + list((settings or {}).items()) + server
    own_transaction = conn.info.transaction_status == pq.TransactionStatus.IDLE
    with conn.transaction():
        if own_transaction:
            conn.execute("SET TRANSACTION READ ONLY")
        for name, value in values:
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
