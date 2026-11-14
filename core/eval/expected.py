"""Regenerate the expected values of the eval set from SQL (issue #40).

Usage:
    python core/eval/expected.py --check                      # all personas; exit 1 on any difference
    python core/eval/expected.py --check --persona CUST00860  # one persona
    python core/eval/expected.py --persona CUST00860          # print the fresh values of one persona
    python core/eval/expected.py --write                      # write fresh values into cases.yaml

Every expected value in core/eval/cases.yaml has a `source`: a metric file and output column
(core/metrics/*.sql, docs/design/metrics.md), or a plain spending query over one customer's
transactions (`spending`, `spending_change` below: the `spending.*` methods of agent-core.md).
The reference answer source of run.py answers with the same functions, so a stale committed value
fails both `--check` and `run.py --source reference`.

Database limits (shared database): one connection, statement_timeout 60s, every query restricted to
one customer, no aggregate over the whole transactions table, nothing created.
Reads DATABASE_URL from the environment, or from a .env file in the repository root. Never prints it,
and never prints a driver error from a connection attempt (it can repeat parts of the URL).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import psycopg
import yaml
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
METRICS = ROOT / "core" / "metrics"
CASES = Path(__file__).with_name("cases.yaml")
PERSONAS = ROOT / "core" / "config" / "personas.yaml"

# Metric name (the <metric> of a method id in agent-core.md) -> SQL file.
METRIC_FILES = {
    "recurring": "01_recurring.sql",
    "baskets": "02_baskets.sql",
    "safe_to_spend": "03_safe_to_spend.sql",
    "what_if": "04_what_if.sql",
    "spender_profile": "05_spender_profile.sql",
    "peer_benchmark": "06_peer_benchmark.sql",   # reads the marts of core/marts/build.py
    "small_purchases": "08_small_purchases.sql",  # #256: the last 3 complete months, EUR 10 (the tool's defaults)
}

# MCC groups of agent-core.md section 6.1, with the codes metrics.md section 1 names.
MCC_GROUPS = {
    "taxi": ["4121"],
    "public_transport": ["4111"],
    "fuel": ["5541", "5542"],
    "parking": ["7523"],
    "restaurants": ["5812", "5813", "5814"],  # card payments only; "dining out" is the category Restaurants
}

# Categories that are not spending (metrics.md section 0, "Flows").
NOT_SPEND = ["Salary", "Other Income", "Invest Withdraw", "Invest Deposit", "Salary Sweep"]

# Plain sum and count over one customer's transactions (methods spending.total and spending.n_tx).
# With categories: those categories, whatever their flow (so Invest Deposit can be asked about).
# Without categories: spending only. The end date is clamped to as_of (R5).
SPENDING_SQL = """
SELECT count(*) AS n_tx, COALESCE(sum(-amount_eur), 0) AS total_eur
FROM transactions
WHERE customer_id = %(customer_id)s
  AND tx_date BETWEEN %(start)s AND LEAST(%(end)s::date, %(as_of)s::date)
  AND (%(categories)s::text[] IS NOT NULL OR category <> ALL(%(not_spend)s::text[]))
  AND (%(categories)s::text[] IS NULL OR category = ANY(%(categories)s::text[]))
  AND (%(mccs)s::text[] IS NULL OR mcc = ANY(%(mccs)s::text[]))
"""

UNIT_FAMILY = {"eur": "money", "eur_per_day": "money", "eur_per_week": "money", "eur_per_month": "money",
               "eur_per_year": "money", "percent": "percent", "percentile": "percent", "count": "count",
               "days": "count", "months": "count", "date": "date"}
ITEM_KINDS = ("numbers", "dates", "labels", "forbid")
# "words": a general money question answered in plain words (#572): no tool, no number, at most four sentences
EXPECTS = ("answered", "no_data", "refused", "meta", "any", "words")
REFUSAL_KINDS = ("investment_advice", "credit_decision", "out_of_scope", "other_person_data", "unsafe")


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url and (ROOT / ".env").exists():
        match = re.search(r"^DATABASE_URL=(.+)$", (ROOT / ".env").read_text(encoding="utf-8"), re.M)
        url = match.group(1).strip().strip("\"'") if match else None
    if not url:
        sys.exit("DATABASE_URL is not set (environment or .env)")
    return url


def next_id(cid: str) -> str:
    return f"CUST{int(cid[4:]) + 1:05d}"


class Db:
    """One connection; metric files run unchanged for one customer ([id, next id)); results cached."""

    def __init__(self, as_of: str):
        self.as_of = as_of
        self.conn = psycopg.connect(database_url(), autocommit=True, row_factory=dict_row)
        self.cur = self.conn.cursor()
        self.cur.execute("SET statement_timeout = '60s'")
        self.cache: dict = {}
        self.queries = 0
        self.seconds = 0.0

    def metric(self, name: str, cid: str, settings: dict | None = None) -> list[dict]:
        key = ("metric", name, cid, tuple(sorted((settings or {}).items())))
        if key not in self.cache:
            values = {"app.demo_today": self.as_of, "app.customer_from": cid, "app.customer_to": next_id(cid)}
            values.update({f"app.{k}": str(v) for k, v in (settings or {}).items()})
            for k, v in values.items():
                self.cur.execute("SELECT set_config(%s, %s, false)", (k, v))
            t = time.perf_counter()
            self.cur.execute((METRICS / METRIC_FILES[name]).read_text(encoding="utf-8"))
            rows: list[dict] = []
            while True:
                if self.cur.description:
                    rows = self.cur.fetchall()
                if not self.cur.nextset():
                    break
            self.seconds += time.perf_counter() - t
            self.queries += 1
            for k in (settings or {}):  # back to the file's defaults for the next run
                self.cur.execute("SELECT set_config(%s, '', false)", (f"app.{k}",))
            self.cache[key] = rows
        return self.cache[key]

    def spending(self, cid: str, start: str, end: str, categories=None, mcc_group=None) -> dict:
        key = ("spending", cid, start, end, tuple(categories or ()), mcc_group)
        if key not in self.cache:
            t = time.perf_counter()
            self.cur.execute(SPENDING_SQL, {
                "customer_id": cid, "start": start, "end": end, "as_of": self.as_of,
                "categories": list(categories) if categories else None, "not_spend": NOT_SPEND,
                "mccs": MCC_GROUPS[mcc_group] if mcc_group else None})
            self.cache[key] = self.cur.fetchone()
            self.seconds += time.perf_counter() - t
            self.queries += 1
        return self.cache[key]


def connect(as_of: str) -> Db:
    try:
        return Db(as_of)
    except Exception as e:
        # Never print a driver error from a connection attempt: psycopg and libpq repeat parts of a
        # malformed DATABASE_URL in their messages, including the password.
        sys.exit(f"{type(e).__name__}: could not connect; check DATABASE_URL")


def evaluate(db: Db, cid: str, src: dict):
    """The value a source spec produces for one customer (Decimal, int, str or date)."""
    if "metric" in src:
        rows = db.metric(src["metric"], cid, src.get("settings"))
        where = src.get("where", {})
        match = [r for r in rows if all(str(r.get(k)) == str(v) for k, v in where.items())]
        if len(match) != 1:
            raise ValueError(f"{cid} {src}: {len(match)} matching rows")
        value = match[0][src["column"]]
    elif src.get("query") == "spending":
        value = db.spending(cid, src["start"], src["end"], src.get("categories"), src.get("mcc_group"))[src["column"]]
    elif src.get("query") == "spending_change":
        cur = db.spending(cid, src["start"], src["end"], src.get("categories"), src.get("mcc_group"))["total_eur"]
        prev = db.spending(cid, src["prev_start"], src["prev_end"], src.get("categories"),
                           src.get("mcc_group"))["total_eur"]
        if src["column"] == "change_eur":
            value = cur - prev
        elif src["column"] == "change_pct":
            value = 100 * (cur - prev) / prev if prev else None
        else:
            raise ValueError(f"unknown column {src['column']}")
    elif src.get("query") == "bonus":
        # The S-Bonus estimate (#216): the grocery base from SQL (the 6-month window's Groceries average,
        # cents), then the rules file's formula (core/config/s_group_benefits.yaml) the tool applies.
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from core.tools.bonus import RULES, estimate
        from core.tools.formatting import money

        total = db.spending(cid, src["start"], src["end"], ["Groceries"], None)["total_eur"]
        grocery = money(Decimal(str(total)) / 6)
        share = int(src.get("share_pct") or RULES.default_share_pct)
        value = getattr(estimate(grocery, share), src["column"])
    elif src.get("query") == "savings_plan":
        # The savings plan (#369): the what-if savings of the plan's levers, from 04_what_if.sql with the
        # tool's settings (config.SAVINGS_PLAN_*): Restaurants at its cut, then the other category with the
        # largest baseline at the other cut; a lever counts from the threshold; the year is twelve months.
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from core.tools import config as tools_config

        def what_if(category: str, pct: int) -> dict | None:
            rows = db.metric("what_if", cid, {"whatif": f"category:{category}", "whatif_pct": pct})
            return next((r for r in rows if r.get("customer_id") == cid), None)

        first_cat, first_pct = tools_config.SAVINGS_PLAN_FIRST
        others = {c: what_if(c, tools_config.SAVINGS_PLAN_OTHER_CUT_PCT) for c in tools_config.SAVINGS_PLAN_OTHER_CATEGORIES
                  if c != first_cat}   # never the first lever's category again, as the tool
        offered = sorted((-Decimal(str(r["baseline_month_eur"])), c) for c, r in others.items()
                         if r is not None and r["status"] != "not_offered")
        levers = {"first": what_if(first_cat, first_pct), "other": others[offered[0][1]] if offered else None}
        savings = {k: Decimal(str(r["saving_month_eur"])) for k, r in levers.items()
                   if r is not None and r["status"] != "not_offered"
                   and Decimal(str(r["saving_month_eur"])) >= tools_config.SAVINGS_PLAN_MIN_EUR}
        month = sum(savings.values(), Decimal("0"))
        value = {"total_month_eur": month, "total_year_eur": month * 12,
                 "first_saving_eur": savings.get("first"), "other_saving_eur": savings.get("other")}[src["column"]]
    else:
        raise ValueError(f"unknown source {src}")
    if "multiply" in src and value is not None:
        value = Decimal(str(value)) * Decimal(str(src["multiply"]))
    if "plus" in src and value is not None:   # a sum a confused coach would give (forbid), e.g. plan + safe to save
        value = Decimal(str(value)) + sum((Decimal(str(evaluate(db, cid, s))) for s in src["plus"]), Decimal("0"))
    return value


def normalise(value, unit: str | None):
    """A value as stored in cases.yaml: money to 2 decimals and percent to 1 (half up), counts int,
    dates ISO, labels as text."""
    if value is None:
        return None
    if unit is None:
        return str(value)
    family = UNIT_FAMILY[unit]
    if family == "date":
        return value.isoformat() if isinstance(value, date) else str(value)
    if family == "count":
        return int(value)
    places = Decimal("0.01") if family == "money" else Decimal("0.1")
    return float(Decimal(str(value)).quantize(places, ROUND_HALF_UP))


def items(case: dict):
    for kind in ITEM_KINDS:
        for item in case.get(kind) or []:
            yield kind, item


def fresh_value(db: Db, cid: str, item: dict):
    return normalise(evaluate(db, cid, item["source"]), item.get("unit"))


def load(path: Path = CASES) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def validate(doc: dict) -> list[str]:
    """Structural checks of the case file: what issue #40 asks every case to have."""
    errors = []
    personas = {p["customer_id"] for p in yaml.safe_load(PERSONAS.read_text(encoding="utf-8"))["personas"]}
    seen = set()
    for c in doc["cases"]:
        cid = c.get("id", "?")
        for key in ("id", "persona", "question", "intent", "expect", "tags"):
            if not c.get(key):
                errors.append(f"{cid}: missing {key}")
        if cid in seen:
            errors.append(f"{cid}: duplicate id")
        seen.add(cid)
        if c.get("persona") not in personas:
            errors.append(f"{cid}: persona {c.get('persona')} is not in personas.yaml")
        if not (c.get("question") or {}).get("en"):
            errors.append(f"{cid}: no English question")
        if c.get("expect") not in EXPECTS:
            errors.append(f"{cid}: expect must be one of {EXPECTS}")
        if c.get("expect") == "refused":
            if not c.get("refusal_kinds") or set(c["refusal_kinds"]) - set(REFUSAL_KINDS):
                errors.append(f"{cid}: refusal_kinds must be a subset of {REFUSAL_KINDS}")
        if c.get("expect") == "answered" and not (c.get("numbers") or c.get("labels")):
            errors.append(f"{cid}: an answered case needs expected numbers or labels")
        if c.get("expect") == "words" and (c.get("numbers") or c.get("expected_tools") or not c.get("no_data_tool_call")):
            errors.append(f"{cid}: a plain-words case expects no number and no tool (no_data_tool_call: true)")
        for kind, item in items(c):
            for key in ("name", "source"):
                if key not in item:
                    errors.append(f"{cid}: {kind} item without {key}")
            if kind in ("numbers", "forbid"):
                if item.get("unit") not in UNIT_FAMILY or UNIT_FAMILY[item["unit"]] == "date":
                    errors.append(f"{cid}: {item.get('name')}: bad unit {item.get('unit')}")
                if "tolerance" not in item:
                    errors.append(f"{cid}: {item.get('name')}: no tolerance")
            if kind == "dates" and item.get("unit") != "date":
                errors.append(f"{cid}: {item.get('name')}: dates need unit date")
        for item in c.get("forbid_text") or []:
            if not item.get("name") or not item.get("pattern"):
                errors.append(f"{cid}: forbid_text item needs a name and a pattern")
                continue
            try:
                re.compile(item["pattern"])
            except re.error:
                errors.append(f"{cid}: forbid_text {item['name']}: the pattern does not compile")
    return errors


# ---- writing cases.yaml in one stable layout, so that --write is reproducible ----------------------

class Flow(dict):
    pass


class Dumper(yaml.SafeDumper):
    pass


Dumper.add_representer(Flow, lambda d, v: d.represent_mapping("tag:yaml.org,2002:map", v, flow_style=True))


def write_cases(doc: dict, path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    header = "".join(lines[:next(i for i, line in enumerate(lines) if not line.startswith("#"))])
    out = dict(doc)
    out["cases"] = [{k: ([Flow(i) for i in v] if k in ITEM_KINDS else v) for k, v in c.items()}
                    for c in doc["cases"]]
    body = yaml.dump(out, Dumper=Dumper, sort_keys=False, allow_unicode=True, default_flow_style=None, width=1000)
    body = re.sub(r"\n- id:", "\n\n- id:", body)  # a blank line between cases
    path.write_text(header + "\n" + body, encoding="utf-8", newline="\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", default=str(CASES))
    ap.add_argument("--persona", action="append", help="customer_id; repeat for several (default: all)")
    ap.add_argument("--check", action="store_true", help="compare with the committed values; exit 1 on a difference")
    ap.add_argument("--write", action="store_true", help="write the fresh values into the cases file")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Finnish text on any console

    path = Path(args.cases)
    doc = load(path)
    errors = validate(doc)
    if errors:
        print("\n".join(errors))
        sys.exit(f"{len(errors)} problems in {path.name}")
    personas = set(args.persona) if args.persona else None
    t0 = time.perf_counter()
    db = connect(str(doc["as_of"]))
    diffs, per_persona = [], {}
    try:
        for case in doc["cases"]:
            if personas and case["persona"] not in personas:
                continue
            for kind, item in items(case):
                new = fresh_value(db, case["persona"], item)
                per_persona[case["persona"]] = per_persona.get(case["persona"], 0) + 1
                if not (args.check or args.write):
                    print(f"{case['id']:<40} {kind:<7} {item['name']:<28} {new}")
                if item.get("value") != new:
                    diffs.append((case, kind, item, new))
    except psycopg.errors.QueryCanceled:
        sys.exit("stopped: a statement hit statement_timeout (60s)")
    except psycopg.OperationalError as e:
        sys.exit(f"stopped: {type(e).__name__} (details hidden)")
    finally:
        print(f"-- {db.queries} queries, {db.seconds:.2f} s in the database, {time.perf_counter() - t0:.2f} s total")

    print("values regenerated per persona: " + ", ".join(f"{p} {n}" for p, n in sorted(per_persona.items())))
    if args.write:
        for case, kind, item, new in diffs:
            item["value"] = new
        write_cases(doc, path)
        print(f"wrote {len(diffs)} changed values to {path.name}")
    elif args.check:
        for case, kind, item, new in diffs:
            print(f"DIFF {case['id']} {kind} {item['name']}: committed {item.get('value')!r}, fresh {new!r}")
        print(f"check: {len(diffs)} differences")
        sys.exit(1 if diffs else 0)


if __name__ == "__main__":
    main()
