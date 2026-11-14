"""Evidence specs, refs and the evidence store (agent-core.md section 5.2, R2).

A spec is the recipe that rebuilds one number: customer, as_of, method, the selection (or the
input refs for a composite) and the value. The ref is `ev_` plus the first 12 hex characters of
sha256 over the canonical JSON of the spec, so the same number always gets the same ref. Labels,
display strings and language are not part of the spec: English and Finnish share refs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from core.tools import aliases
from core.tools.classify import classify
from core.tools.db import load_transactions
from core.tools.selection import Selection, select, value_of

SPEC_VERSION = 1
MAX_LIMIT = 200
DEFAULT_LIMIT = 50


class EvidenceNotFound(LookupError):
    pass


class EvidenceForbidden(PermissionError):
    """The ref belongs to another customer (the API answers 403 evidence_forbidden)."""


class EvidenceCollision(RuntimeError):
    """Internal error: a ref is already stored with a different spec, so it would resolve to another number."""


def canonical_json(spec: dict[str, Any]) -> str:
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def make_ref(spec: dict[str, Any]) -> str:
    return "ev_" + hashlib.sha256(canonical_json(spec).encode("utf-8")).hexdigest()[:12]


def transactions_spec(customer_id: str, as_of: date, method: str, sel: Selection, value: Decimal,
                      params: dict[str, Any] | None = None,
                      label_set: list[list[Any]] | None = None) -> dict[str, Any]:
    spec = {
        "v": SPEC_VERSION,
        "kind": "transactions",
        "customer_id": customer_id,
        "as_of": as_of.isoformat(),
        "method": method,
        "selection": sel.to_spec(),
        "value": str(value),
    }
    if params:  # only when set (for example n_months), so refs of other numbers do not change
        spec["params"] = params
    if label_set:  # the customer's labels in effect (#68); only when there are any, as for params
        spec["labels"] = label_set
    return spec


# Composite formulas: how a value is computed from its parts (all Decimal, rounded at the end).
# A tuple fixes the roles and their order; None means any number of parts in the given order.
FORMULAS = {
    "difference": ("current", "baseline"),     # current - baseline, cents
    "pct_change": ("current", "baseline"),     # (current - baseline) / baseline * 100, 1 decimal
    "share_pct": ("part", "whole"),            # part / whole * 100, 1 decimal
    "scale": ("base",),                        # base * factor_num / factor_den, cents (params rounding: down)
    "sum": None,                               # sum of all parts, cents
    "minimum": ("a", "b"),                     # the smaller of two amounts, cents (safe to spend, #55)
    "mean": ("total", "count"),                # total / count, cents (the average small purchase, #256)
    # Safe to spend after the savings goal (#391): the smaller of the two limits; the goal is a part so its
    # evidence shows it, and it is already inside the budget limit (03: (free month - goal) x 7 / 30.4375).
    "minimum_after_goal": ("a", "b", "goal"),
    # S-Bonus estimate (#158). The rule's values and its source travel in params, so a ref names the
    # exact table row or rate it was computed with (core/config/s_group_benefits.yaml).
    # bonus_level, percent_of and rate_of work on the unrounded scaled base, base * share_num / share_den
    # (params; 1/1 when absent), and round once at the end, as the document's formula does.
    "rule_value": (),                          # a value of the rule itself, params["value"]
    "bonus_level": ("base",),                  # the percent of the highest table row at or below the base
    "percent_of": ("percent", "base"),         # base * percent / 100, cents
    "rate_of": ("base",),                      # base * params["percent"] / 100, cents
    # Balance forecast (#257): balance - bills due by the day - daily pace * params["days"], cents.
    "balance_forecast": ("balance", "bills", "pace"),
    "excess": ("amount", "reserved"),          # max(amount - reserved, 0), cents (a bill, #242)
}

# A composite part can be a value the user gave instead of a stored number (#242: a bill's amount, read
# from its barcode or typed). Such a part carries its value inline and has no ref; only these methods.
INPUT_METHODS = frozenset({"user_input@1", "bill_barcode@1"})
INPUT_MAX = Decimal("100000.00")   # the largest inline value: a bill amount (contracts/api.md 11.1)


def _scaled(base: Decimal, p: dict[str, Any]) -> Decimal:
    """base * share_num / share_den, unrounded (the what-if share of #158)."""
    return base * Decimal(str(p.get("share_num", 1))) / Decimal(str(p.get("share_den", 1)))


def compute_formula(formula: str, values: dict[str, Decimal], params: dict[str, Any] | None = None) -> Decimal:
    from core.tools.formatting import money, pct

    if formula == "difference":
        return money(values["current"] - values["baseline"])
    if formula == "excess":
        return money(max(values["amount"] - values["reserved"], Decimal(0)))
    if formula == "pct_change":
        return pct((values["current"] - values["baseline"]) / values["baseline"] * 100)
    if formula == "share_pct":
        return pct(values["part"] / values["whole"] * 100)
    if formula == "scale":
        p = params or {}
        scaled = values["base"] * Decimal(str(p["factor_num"])) / Decimal(str(p["factor_den"]))
        if p.get("rounding") == "down":  # #158: a shown base that never passes a threshold it did not reach
            return scaled.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        return money(scaled)
    if formula == "sum":
        return money(sum(values.values(), Decimal("0")))
    if formula in ("minimum", "minimum_after_goal"):
        return money(min(values["a"], values["b"]))
    if formula == "mean":
        return money(values["total"] / values["count"])
    if formula == "rule_value":
        return Decimal(str((params or {})["value"]))
    if formula == "bonus_level":
        p = params or {}
        base = _scaled(values["base"], p)
        percent = Decimal(str(p["below_lowest_percent"]))
        for minimum, row_percent in p["levels"]:  # ascending by minimum
            if Decimal(str(minimum)) <= base:
                percent = Decimal(str(row_percent))
        return percent
    if formula == "percent_of":
        return money(_scaled(values["base"], params or {}) * values["percent"] / 100)
    if formula == "rate_of":
        p = params or {}
        return money(_scaled(values["base"], p) * Decimal(str(p["percent"])) / 100)
    if formula == "balance_forecast":
        days = Decimal(str((params or {})["days"]))
        return money(values["balance"] - values["bills"] - values["pace"] * days)
    raise ValueError(f"unknown formula {formula!r}")


def metric_spec(customer_id: str, as_of: date, method: str, file: str, column: str,
                settings: dict[str, str], value: Decimal, period: dict[str, str] | None = None) -> dict[str, Any]:
    """A number read from a metric SQL file (core/metrics/<file>) for one customer (#55).

    Resolving it re-runs the file for the same customer, as_of and settings and compares the column,
    so the number reconciles against the metric definition itself. `period` ({start, end}) is the
    period the card shows for the number; GET /api/evidence takes it from params.period.
    """
    spec = {
        "v": SPEC_VERSION,
        "kind": "metric",
        "customer_id": customer_id,
        "as_of": as_of.isoformat(),
        "method": method,
        "source": {"file": file, "column": column, "settings": dict(sorted(settings.items()))},
        "value": str(value),
    }
    if period:
        spec["params"] = {"period": period}
    return spec


def peer_spec(customer_id: str, as_of: date, method: str, file: str, metric: str, column: str,
              settings: dict[str, str], value: Decimal, period: dict[str, str] | None = None) -> dict[str, Any]:
    """A peer-group statistic read from 06_peer_benchmark.sql for one customer and metric (#69).

    Kind `peer_aggregate` (agent-core.md section 5.2): resolving it re-runs the file for the same
    customer, as_of and settings, picks the metric's row and returns the group statistics only
    (median, quartiles, group size, level), never another customer's rows.
    """
    spec = {
        "v": SPEC_VERSION,
        "kind": "peer_aggregate",
        "customer_id": customer_id,
        "as_of": as_of.isoformat(),
        "method": method,
        "source": {"file": file, "metric": metric, "column": column, "settings": dict(sorted(settings.items()))},
        "value": str(value),
    }
    if period:
        spec["params"] = {"period": period}
    return spec


# The group statistics a peer_aggregate resolution shows: (role, output column of 06, method id).
PEER_PARTS = (
    ("peer_median", "peer_median_month_eur", "peer_benchmark.peer_median_month_eur@1"),
    ("peer_p25", "peer_p25_month_eur", "peer_benchmark.peer_p25_month_eur@1"),
    ("peer_p75", "peer_p75_month_eur", "peer_benchmark.peer_p75_month_eur@1"),
    ("peer_n", "peer_n", "peer_benchmark.peer_n@1"),
)


def period_param(period) -> dict[str, str]:
    """{start, end} of a Period, as stored in params.period of a spec."""
    return {"start": period.start.isoformat(), "end": period.end.isoformat()}


def composite_spec(customer_id: str, as_of: date, method: str, formula: str,
                   parts: dict[str, str | dict[str, Any]], value: Decimal,
                   params: dict[str, Any] | None = None) -> dict[str, Any]:
    """`parts` maps each role to a ref, or to an inline input `{method, value, period}` with no ref (a
    value the user gave, INPUT_METHODS). A part with a ref is stored exactly as before, so the refs of
    existing numbers do not change."""
    roles = FORMULAS[formula] or tuple(parts)

    def part(role: str) -> dict[str, Any]:
        p = parts[role]
        if isinstance(p, str):
            return {"role": role, "ref": p}
        if p.get("method") not in INPUT_METHODS:
            raise ValueError("an inline composite part must be a value the user gave")
        return {"role": role, "ref": None, "input": {"method": p["method"], "value": str(p["value"]),
                                                     "period": p["period"]}}

    spec = {
        "v": SPEC_VERSION,
        "kind": "composite",
        "customer_id": customer_id,
        "as_of": as_of.isoformat(),
        "method": method,
        "formula": formula,
        "parts": [part(role) for role in roles],
        "value": str(value),
    }
    if params:  # only when set, so refs of other numbers do not change
        spec["params"] = params
    return spec


def input_spec(inline: Any, as_of: str) -> dict[str, Any]:
    """The pseudo spec of an inline composite part, for showing it like any other part. A stored spec is
    data: only the input methods, a decimal value and a date period are accepted (ValueError otherwise)."""
    if not isinstance(inline, dict) or inline.get("method") not in INPUT_METHODS:
        raise ValueError("not an inline input part")
    try:
        value = Decimal(str(inline["value"]))
    except InvalidOperation:
        raise ValueError("not a decimal value") from None
    # A bill amount (the only inline part today): more than 0, at most 100,000.00, in cents. Checked in
    # this order, so a huge exponent (1e10000) is refused before any arithmetic on it.
    if not value.is_finite() or not Decimal(0) < value <= INPUT_MAX or value != value.quantize(Decimal("0.01")):
        raise ValueError("not a bill amount")
    period = inline["period"]
    start, end = date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
    return {"kind": "input", "method": inline["method"], "value": str(value), "as_of": as_of,
            "params": {"period": {"start": start.isoformat(), "end": end.isoformat()}}}


# ---- store ---------------------------------------------------------------------------------------

INSERT_SQL = """
INSERT INTO coach_evidence (ref, customer_id, spec)
VALUES (%s, %s, %s)
ON CONFLICT (ref) DO NOTHING
"""
LOAD_SQL = "SELECT customer_id, spec FROM coach_evidence WHERE ref = %s"
READ_BACK_SQL = "SELECT ref, spec FROM coach_evidence WHERE ref = ANY(%s)"


def write(conn: psycopg.Connection, specs: dict[str, dict[str, Any]]) -> None:
    """Store specs by ref. Idempotent: an existing ref is left as it is.

    The stored specs are read back afterwards. If a ref already holds a different spec (a hash
    collision, or a spec format change without a version bump), EvidenceCollision is raised instead
    of silently resolving that ref to another number.
    """
    if not specs:
        return
    with conn.cursor() as cur:
        cur.executemany(INSERT_SQL, [(ref, s["customer_id"], Jsonb(s)) for ref, s in specs.items()])
    stored = dict(conn.execute(READ_BACK_SQL, (list(specs),)).fetchall())
    for ref, spec in specs.items():
        if ref not in stored:
            raise EvidenceCollision(f"evidence {ref} was not stored")
        if canonical_json(stored[ref]) != canonical_json(spec):
            raise EvidenceCollision(f"evidence {ref} is already stored with a different spec")


def load(conn: psycopg.Connection, ref: str) -> tuple[str, dict[str, Any]]:
    row = conn.execute(LOAD_SQL, (ref,)).fetchone()
    if row is None:
        raise EvidenceNotFound(ref)
    return row[0], row[1]


# ---- resolve -------------------------------------------------------------------------------------

@dataclass
class Resolution:
    ref: str
    kind: str
    method: str
    value: Decimal
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int | None = None
    reconciles: bool | None = None
    parts: list[dict[str, Any]] = field(default_factory=list)  # role, ref, method, value, spec
    next_cursor: str | None = None
    spec: dict[str, Any] | None = None  # the stored spec, for callers that rebuild the Number


def _row(c, alias_map: aliases.AliasMap, language: str) -> dict[str, Any]:
    t = c.tx
    merchant = None
    if t.merchant_id is not None:
        merchant = {"id": t.merchant_id, "label": alias_map.for_merchant(t.merchant_id).label(language)}
    return {
        "tx_id": f"tx_{t.id}",
        "date": t.tx_date.isoformat(),
        "time": t.tx_at.strftime("%H:%M"),
        "category": t.category,
        "merchant": merchant,
        "mcc": t.mcc,
        "amount": f"{t.amount_eur:.2f}",
        "currency": "EUR",
    }


def _cursor_offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if not cursor.startswith("cur_") or not cursor[4:].isdigit():
        raise ValueError("invalid cursor")
    return int(cursor[4:])


def resolve(conn: psycopg.Connection, ref: str, customer_id: str, *, limit: int = DEFAULT_LIMIT,
            cursor: str | None = None, language: str = "en") -> Resolution:
    """Load a ref, check it belongs to `customer_id`, re-run its spec and reconcile."""
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be 1..{MAX_LIMIT}")
    offset = _cursor_offset(cursor)
    owner, spec = load(conn, ref)
    if owner != customer_id or spec.get("customer_id") != customer_id:
        raise EvidenceForbidden(ref)
    value = Decimal(spec["value"])
    as_of = date.fromisoformat(spec["as_of"])

    if spec["kind"] == "composite":
        part_values: dict[str, Decimal] = {}
        parts = []
        for part in spec["parts"]:
            if part.get("ref") is None:
                # a value the user gave (#242), stored inline: shown as a part without a ref. A stored spec is
                # data: a malformed inline part is refused like a bad metric setting (#122), not a 500.
                try:
                    part_spec = input_spec(part.get("input"), spec["as_of"])
                except (ValueError, KeyError, TypeError):
                    raise EvidenceForbidden(ref) from None
                part_values[part["role"]] = Decimal(part_spec["value"])
                parts.append({"role": part["role"], "ref": None, "method": part_spec["method"],
                              "value": part_spec["value"], "spec": part_spec})
                continue
            part_owner, part_spec = load(conn, part["ref"])
            if part_owner != customer_id:
                raise EvidenceForbidden(part["ref"])
            part_values[part["role"]] = Decimal(part_spec["value"])
            parts.append({"role": part["role"], "ref": part["ref"], "method": part_spec["method"],
                          "value": part_spec["value"], "spec": part_spec})
        try:
            reconciles = compute_formula(spec["formula"], part_values, spec.get("params")) == value
        except (ValueError, KeyError, ArithmeticError, TypeError):
            # a formula this version does not know, or params it cannot compute with (a crafted or
            # damaged spec): no check, not a 500
            reconciles = None
        return Resolution(ref, "composite", spec["method"], value, parts=parts, reconciles=reconciles, spec=spec)

    if spec["kind"] == "metric":  # #55: re-run the metric SQL file for this customer
        from core.tools import config, metric_sql

        source = spec["source"]
        # A stored spec is data: only the files the tools write metric specs for, and never a setting
        # that is reserved (it would move the customer range or as_of) or malformed. The same check as
        # run() makes, before anything runs; a refusal is 403 evidence_forbidden, not a 500 (#122).
        if source["file"] not in config.METRIC_EVIDENCE_FILES:
            raise EvidenceForbidden(ref)
        try:
            metric_sql.check_settings(source["settings"])
        except ValueError:
            raise EvidenceForbidden(ref) from None
        row = metric_sql.run_one(conn, source["file"], customer_id, as_of, source["settings"])
        column = row.get(source["column"]) if row else None
        recomputed = None if column is None else metric_sql.decimal(column)
        return Resolution(ref, "metric", spec["method"], value, reconciles=recomputed == value, spec=spec)

    if spec["kind"] == "peer_aggregate":  # #69: re-run 06 for this customer; statistics only, no rows
        from core.tools import config, metric_sql

        source = spec["source"]
        if source["file"] != config.PEER_FILE:  # the file is fixed in code, never taken from a stored spec
            raise ValueError("peer evidence must come from 06_peer_benchmark.sql")
        settings = {"peer_min_n": config.PEER_MIN_N}   # pinned from config, never from the stored spec
        if "tx_labels" in source["settings"]:          # the labels the number was computed with (#68)
            settings["tx_labels"] = source["settings"]["tx_labels"]
        try:
            metric_sql.check_settings(settings)        # the same check as the metric branch (#122)
        except ValueError:
            raise EvidenceForbidden(ref) from None
        rows = [r for r in metric_sql.run(conn, config.PEER_FILE, customer_id, as_of, settings)
                if r.get("customer_id") == customer_id and r.get("metric") == source["metric"]]
        row = rows[0] if len(rows) == 1 else None
        column = row.get(source["column"]) if row else None
        recomputed = None if column is None else metric_sql.decimal(column)
        parts = []
        if row is not None and row.get("shown"):
            parts = [{"role": role, "method": method, "value": str(row[col])} for role, col, method in PEER_PARTS]
            parts.append({"role": "peer_level", "method": None, "value": row["peer_level"]})
        return Resolution(ref, "peer_aggregate", spec["method"], value, parts=parts, reconciles=recomputed == value,
                          spec=spec)

    if spec["kind"] != "transactions":
        # A kind this version cannot re-run: the evidence still opens, without a reconciliation check.
        return Resolution(ref, spec["kind"], spec["method"], value, reconciles=None, spec=spec)

    sel = Selection.from_spec(spec["selection"])
    history = load_transactions(conn, customer_id, as_of)
    # The labels the number was computed with (#68), not today's: a ref issued before a label keeps
    # resolving to the number as it was. A spec without labels was computed without any.
    overrides = {int(tx_id): basket for tx_id, basket in spec.get("labels", [])}
    rows = select(classify(history, as_of, overrides), sel)
    try:
        reconciles = value_of(rows, sel, spec["method"], spec.get("params")) == value
    except (ValueError, KeyError, ArithmeticError, TypeError):  # unknown method or bad params: no check
        reconciles = None
    rows.sort(key=lambda c: (c.tx.tx_date, c.tx.tx_at, c.tx.id), reverse=True)
    page = rows[offset:offset + limit]
    alias_map = aliases.build(history, as_of)
    next_cursor = f"cur_{offset + limit}" if offset + limit < len(rows) else None
    return Resolution(
        ref, "transactions", spec["method"], value,
        rows=[_row(c, alias_map, language) for c in page],
        row_count=len(rows),
        reconciles=reconciles,
        next_cursor=next_cursor,
        spec=spec,
    )
