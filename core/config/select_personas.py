"""Select demo personas and compute their reference answers (issue #22).

Usage:
    python core/config/select_personas.py                                  # the scan as it was run
    python core/config/select_personas.py --from CUST00000 --to CUST01000
    python core/config/select_personas.py --answers CUST00860,CUST00493,CUST00349,CUST00849 --out answers.json

Method: docs/design/personas.md. The metric numbers come from the unchanged files in core/metrics/
(docs/design/metrics.md); this script only runs them and compares their output with the checks.
The screening (taxi and dining-month checks, lead slot) is the scan as it was run. After the scan a
product decision dropped the taxi criterion, made CUST00860 the lead and added CUST00849; the
document records that. --answers computes the reference answers for any personas.

Database limits (shared database, 2 GB RAM, 25 connections): one connection,
statement_timeout 60s, customer ranges of at most 100 customers, at most 2,000 customers screened,
never an aggregate over the whole transactions table, nothing created. Every query on transactions
names its customers in WHERE. The script stops at the first timeout or connection error.

Reads DATABASE_URL from the environment, or from a .env file in the repository root. Never prints it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
METRICS = ROOT / "core" / "metrics"
SCREEN_SQL = Path(__file__).with_name("select_personas.sql")
BATCH = 100        # customers per range, the database limit
MAX_CUSTOMERS = 2000
PEER_MIN_N = 20    # app.peer_min_n of 06_peer_benchmark.sql: at least 20 other peers
DINING = "category:Restaurants"     # "dining out": the category, including non-card payments without MCC
DINING_CARD = "mcc:5812,5813,5814"  # the MCC group restaurants: card payments only
SLOTS = ("young_everyday", "midlife_essentials", "recent_unexpected")

# First pass: customers with a taxi ride last month (every persona needs one). Uses the
# (customer_id, mcc, tx_date) index; the other checks only run for these customers.
TAXI_PREFILTER = """
SELECT customer_id, count(*) AS taxi_n
FROM transactions
WHERE customer_id >= %(frm)s AND customer_id < %(to)s
  AND mcc = '4121'
  AND tx_date BETWEEN %(lm_start)s AND %(lm_end)s
  AND tx_date <= %(today)s
GROUP BY customer_id
ORDER BY customer_id
"""

# Size of the peer cell (age band + first 3 postal digits, the most specific level of metrics.md
# section 6), from customers only (5,100 rows). Sweep customers are not removed here; 06 removes
# them when it reads the marts of #21.
CELL_SIZE = """
SELECT count(*) AS n
FROM customers
WHERE left(postal_code, 3) = %(area3)s
  AND CASE WHEN age < 25 THEN '18-24' WHEN age < 35 THEN '25-34' WHEN age < 45 THEN '35-44'
           WHEN age < 55 THEN '45-54' WHEN age < 65 THEN '55-64' WHEN age < 75 THEN '65-74'
           ELSE '75+' END = %(age_band)s
"""

# Direct checks for the reference answers, straight from transactions for one customer.
DIRECT_TAXI = """
SELECT count(*) AS n, COALESCE(sum(-amount_eur), 0) AS eur
FROM transactions
WHERE customer_id = %(cid)s AND mcc = '4121'
  AND tx_date BETWEEN %(lm_start)s AND %(lm_end)s AND tx_date <= %(today)s
"""
DIRECT_DINING = """
SELECT to_char(date_trunc('month', tx_date), 'YYYY-MM') AS month, count(*) AS n, sum(-amount_eur) AS eur
FROM transactions
WHERE customer_id = %(cid)s AND category = 'Restaurants'
  AND tx_date BETWEEN %(dining_start)s AND %(today)s
GROUP BY 1 ORDER BY 1
"""
DIRECT_DINING_WINDOW = """
SELECT count(*) AS n, COALESCE(sum(-amount_eur), 0) AS eur,
       count(*) FILTER (WHERE mcc IS NULL) AS n_no_mcc, COALESCE(sum(-amount_eur) FILTER (WHERE mcc IS NULL), 0) AS eur_no_mcc
FROM transactions
WHERE customer_id = %(cid)s AND category = 'Restaurants'
  AND tx_date BETWEEN %(win_start)s AND %(win_end)s AND tx_date <= %(today)s
"""


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url and (ROOT / ".env").exists():
        match = re.search(r"^DATABASE_URL=(.+)$", (ROOT / ".env").read_text(encoding="utf-8"), re.M)
        url = match.group(1).strip().strip("\"'") if match else None
    if not url:
        sys.exit("DATABASE_URL is not set (environment or .env)")
    return url


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def periods(today: date) -> dict:
    """The periods of select_personas.sql and core/metrics (window = last 6 complete months)."""
    month_start = today.replace(day=1)
    win_next = add_months((today + timedelta(days=1)).replace(day=1), 0)  # date_trunc('month', today + 1)
    return {
        "today": today,
        "win_start": add_months(win_next, -6),
        "win_end": win_next - timedelta(days=1),
        "lm_start": add_months(month_start, -1),
        "lm_end": month_start - timedelta(days=1),
        "dining_start": add_months(month_start, -6),
    }


def cust_id(n: int) -> str:
    return f"CUST{n:05d}"


def next_id(cid: str) -> str:
    return cust_id(int(cid[4:]) + 1)


class Db:
    def __init__(self, today: date):
        self.conn = psycopg.connect(database_url(), autocommit=True, row_factory=dict_row)
        self.cur = self.conn.cursor()
        self.cur.execute("SET statement_timeout = '60s'")
        self.today = today
        self.p = periods(today)
        self.seconds = 0.0
        self.queries = 0

    def query(self, sql: str, params: dict | None = None) -> list[dict]:
        t = time.perf_counter()
        self.cur.execute(sql, params)
        rows = self.cur.fetchall()
        self.seconds += time.perf_counter() - t
        self.queries += 1
        return rows

    def run_file(self, path: Path, frm: str, to: str, extra: dict | None = None) -> list[dict]:
        """Run a SQL file unchanged on [frm, to) and return the rows of its last result set."""
        settings = {"app.demo_today": self.today.isoformat(), "app.customer_from": frm, "app.customer_to": to}
        settings.update(extra or {})
        for k, v in settings.items():
            self.cur.execute("SELECT set_config(%s, %s, false)", (k, str(v)))
        t = time.perf_counter()
        self.cur.execute(path.read_text(encoding="utf-8"))  # no parameters: the file runs as written
        rows: list[dict] = []
        while True:
            if self.cur.description:
                rows = self.cur.fetchall()
            if not self.cur.nextset():
                break
        self.seconds += time.perf_counter() - t
        self.queries += 1
        for k in (extra or {}):  # reset the optional knobs so the next file sees its defaults
            self.cur.execute("SELECT set_config(%s, '', false)", (k,))
        return rows

    def one(self, path: Path, cid: str, extra: dict | None = None) -> list[dict]:
        return self.run_file(path, cid, next_id(cid), extra)


def cell_others(db: Db, age_band: str, area3: str, cache: dict) -> int:
    key = (age_band, area3)
    if key not in cache:
        cache[key] = db.query(CELL_SIZE, {"age_band": age_band, "area3": area3})[0]["n"] - 1
    return cache[key]


def screen_one(db: Db, cid: str, cells: dict) -> dict:
    """Checks of issue #22 for one customer. `tier` is lead (every check, strict), other (the relaxed
    taxi and dining checks of personas 2 and 3) or None. Metric files run only if the cheap checks pass."""
    c = dict(db.one(SCREEN_SQL, cid)[0])
    fails = []
    if c["taxi_n_last_month"] < 1:
        fails.append("no_taxi")
    if c["dining_months_of_6"] < 5:
        fails.append("dining<5_of_6")
    if c["housing_months"] < 6 or c["housing_this_month"] < 1:   # demo quality: no skipped housing month
        fails.append("housing_not_every_month")
    if c["sweep_months"] > 0:
        fails.append("salary_sweep")
    c["peer_area3_others"] = cell_others(db, c["age_band"], c["area3"], cells)
    if c["peer_area3_others"] < PEER_MIN_N:
        fails.append("peer_area3<20")
    if fails:
        c["fails"], c["tier"] = fails, None
        return c

    sts = db.one(METRICS / "03_safe_to_spend.sql", cid)[0]
    for k in ("safe_to_spend_7d_eur", "binding_limit", "salary_status", "balance_eur", "next_payday"):
        c[k] = sts[k]
    c["safe_status"] = sts["status"]
    if not sts["safe_to_spend_7d_eur"] > 0:
        fails.append("safe_to_spend<=0")
    if sts["salary_status"] != "received_this_month":
        fails.append("salary_not_received_this_month")
    if fails:
        c["fails"], c["tier"] = fails, None
        return c

    rec = {r["series_key"]: r for r in db.one(METRICS / "01_recurring.sql", cid)}
    c["salary_recurring"] = rec.get("salary", {}).get("direction") == "in"
    c["housing_recurring"] = "housing_payment" in rec
    c["salary_typical_eur"] = rec.get("salary", {}).get("typical_month_eur")
    c["housing_typical_eur"] = rec.get("housing_payment", {}).get("typical_month_eur")
    if not c["salary_recurring"]:
        fails.append("salary_not_recurring")
    if not c["housing_recurring"]:
        fails.append("housing_not_recurring")

    prof = db.one(METRICS / "05_spender_profile.sql", cid)[0]
    for k in ("profile", "traits", "keep_rate_pct", "regular_share_pct", "unexpected_share_pct",
              "everyday_share_pct", "net_income_month_eur", "spend_month_eur"):
        c[k] = prof[k]
    c["fails"] = fails
    if fails:
        c["tier"] = None
    elif c["taxi_n_last_month"] >= 3 and c["dining_months_of_6"] == 6:
        c["tier"] = "lead"
    else:
        c["tier"] = "other"
    c["kinds"] = kind_scores(c) if not fails else {}
    return c


def kind_scores(c: dict) -> dict:
    """Which persona slot a passing candidate fits, with the score that ranks it (higher is better)."""
    s = {}
    if c["age"] <= 34:
        s["young_everyday"] = float(c["everyday_share_pct"] or 0)
    if 35 <= c["age"] <= 54:
        s["midlife_essentials"] = float(c["regular_share_pct"] or 0)
    if c["unexp_eur"] is not None and float(c["unexp_eur"]) >= 300 and (
            c["unexp_is_one_off"] or float(c["unexp_x_median"] or 0) >= 3):
        s["recent_unexpected"] = float(c["unexp_eur"])
    return s


def rank(pool: list[dict], slot: str) -> list[dict]:
    """Within a slot: status ok first, then the slot score, then more taxi rides; customer_id breaks ties."""
    return sorted([c for c in pool if slot in c["kinds"]],
                  key=lambda c: (c["safe_status"] == "ok", c["kinds"][slot], c["taxi_n_last_month"],
                                 c["customer_id"]), reverse=True)


def choose(passing: list[dict]) -> dict:
    """The lead (strict tier) takes its slot first, in SLOTS order; the other two slots are filled from
    every passing candidate, rarest slot first, preferring an age band not chosen yet so the three
    look different. Returns {} if no full set of three exists."""
    for lead_slot in SLOTS:
        leads = rank([c for c in passing if c["tier"] == "lead"], lead_slot)
        if not leads:
            continue
        lead = leads[0]
        chosen, used = {lead_slot: lead}, {lead["customer_id"]}
        rest = [s for s in SLOTS if s != lead_slot]
        for s in sorted(rest, key=lambda s: (len(rank(passing, s)), SLOTS.index(s))):
            bands = {c["age_band"] for c in chosen.values()}
            pool = [c for c in rank(passing, s) if c["customer_id"] not in used]
            pick = next((c for c in pool if c["age_band"] not in bands), pool[0] if pool else None)
            if pick:
                chosen[s] = pick
                used.add(pick["customer_id"])
        if len(chosen) == 3:
            return {"lead": lead_slot, **chosen}
    return {}


def screen(db: Db, args, cells: dict) -> dict:
    start, end = int(args.frm[4:]), int(args.to[4:])
    end = min(end, start + MAX_CUSTOMERS)
    candidates: list[dict] = []
    ranges, to = 0, args.frm
    for lo in range(start, end, BATCH):
        frm, to = cust_id(lo), cust_id(min(lo + BATCH, end))
        t = time.perf_counter()
        hits = db.query(TAXI_PREFILTER, {"frm": frm, "to": to, **db.p})
        new = [screen_one(db, h["customer_id"], cells) for h in hits]
        candidates += new
        ranges += 1
        passing = [c for c in candidates if c["tier"]]
        per_slot = {s: len(rank(passing, s)) for s in SLOTS}
        n_lead = sum(c["tier"] == "lead" for c in passing)
        print(f"{frm}..{to}  taxi {len(hits):2d}  pass {sum(bool(c['tier']) for c in new):2d}  "
              f"lead {n_lead:2d}  slots {per_slot}  {time.perf_counter() - t:.2f} s", flush=True)
        if n_lead >= args.enough and choose(passing) and all(n >= args.enough for n in per_slot.values()):
            break
        time.sleep(args.pause)

    passing = [c for c in candidates if c["tier"]]
    print(f"\nscreened {ranges} ranges ({args.frm}..{to}), {len(candidates)} with a taxi ride last month, "
          f"{len(passing)} pass every check ({sum(c['tier'] == 'lead' for c in passing)} as lead)\n")
    print("customer   tier  age area profile         ess%  unx%  evd%  safe7d  status      taxi din  "
          "unexpected            peers  slots")
    for c in passing:
        print(f"{c['customer_id']} {c['tier']:<5} {c['age']:3d} {c['area3']}  {c['profile']:<15} "
              f"{c['regular_share_pct']:>5} {c['unexpected_share_pct']:>5} {c['everyday_share_pct']:>5} "
              f"{c['safe_to_spend_7d_eur']:>7} {c['safe_status']:<11} {c['taxi_n_last_month']:>4} "
              f"{c['dining_months_of_6']:>3}  {(c['unexp_category'] or '-')[:11]:<11} "
              f"{str(c['unexp_eur'] or ''):>8}  {c['peer_area3_others']:>5}  {','.join(c['kinds']) or '-'}")
    fails: dict[str, int] = {}
    for c in candidates:
        for f in c["fails"]:
            fails[f] = fails.get(f, 0) + 1
    print(f"\nfailed checks among the customers with a taxi ride: {fails}")
    chosen = choose(passing)
    print("\nchosen:" if chosen else "\nno full set of three found")
    for slot, c in chosen.items():
        if slot != "lead":
            print(f"  {slot:<20} {c['customer_id']}  {c['tier']:<5} age {c['age']}  {c['postal_code']}  "
                  f"{c['profile']}{'  (lead)' if slot == chosen['lead'] else ''}")
    return {"candidates": candidates,
            "chosen": {s: (c if s == "lead" else c["customer_id"]) for s, c in chosen.items()}}


def answers(db: Db, cid: str, cells: dict) -> dict:
    """Reference answers to the demo questions for one persona, from the metric files."""
    p = db.p
    a: dict = {"customer_id": cid}
    a["screen"] = db.one(SCREEN_SQL, cid)[0]
    a["recurring"] = db.one(METRICS / "01_recurring.sql", cid)
    a["baskets"] = db.one(METRICS / "02_baskets.sql", cid)
    a["safe_to_spend"] = db.one(METRICS / "03_safe_to_spend.sql", cid)[0]
    a["whatif_dining"] = (db.one(METRICS / "04_what_if.sql", cid,
                                 {"app.whatif": DINING, "app.whatif_pct": "20"}) or [None])[0]
    a["whatif_dining_card"] = (db.one(METRICS / "04_what_if.sql", cid,
                                      {"app.whatif": DINING_CARD, "app.whatif_pct": "20"}) or [None])[0]
    a["profile"] = db.one(METRICS / "05_spender_profile.sql", cid)[0]
    a["direct_taxi"] = db.query(DIRECT_TAXI, {"cid": cid, **p})[0]
    a["direct_dining_window"] = db.query(DIRECT_DINING_WINDOW, {"cid": cid, **p})[0]
    a["direct_dining_by_month"] = db.query(DIRECT_DINING, {"cid": cid, **p})
    s = a["screen"]
    a["peer_cell_others"] = cell_others(db, s["age_band"], s["area3"], cells)
    # 06 reads the marts of core/marts/build.py when they hold rows for this as_of (peer_source = marts).
    a["peer"] = db.one(METRICS / "06_peer_benchmark.sql", cid)
    return a


def print_answer(a: dict) -> None:
    s, sts, w, pr, pe = a["screen"], a["safe_to_spend"], a["whatif_dining"], a["profile"], a["peer"]
    print(f"\n== {a['customer_id']}  age {s['age']} ({s['age_band']}), postal {s['postal_code']}")
    for b in a["baskets"]:
        print(f"  basket {b['basket']:<23} {b['month_avg_eur']:>9}/month  {b['share_pct']:>5}%  "
              f"excl one-offs {b['month_avg_excl_one_off_eur']:>9}  one-offs {b['n_one_off']} = {b['one_off_total_eur']}")
    print(f"  taxi last month: {s['taxi_n_last_month']} rides, {s['taxi_eur_last_month']} EUR"
          f"  | direct: {a['direct_taxi']['n']} rides, {a['direct_taxi']['eur']} EUR")
    print(f"  safe to spend 7d: {sts['safe_to_spend_7d_eur']} ({sts['binding_limit']} limit, {sts['status']});"
          f" balance limit {sts['balance_limit_7d_eur']}, budget limit {sts['budget_limit_7d_eur']}")
    if w:
        print(f"  dining -20% ({w['selection']}): baseline {w['baseline_month_eur']}/month, saves "
              f"{w['saving_month_eur']}/month, {w['saving_week_eur']}/week, {w['saving_year_eur']}/year; "
              f"{w['n_tx']} tx, one-offs left out {w['one_off_excluded_eur']} ({w['n_one_off']})")
    r = a["whatif_dining_card"]
    if r:
        print(f"    card payments only ({r['selection']}): baseline {r['baseline_month_eur']}, {r['n_tx']} tx, "
              f"one-offs {r['one_off_excluded_eur']} ({r['n_one_off']})")
    dw = a["direct_dining_window"]
    print(f"    direct Restaurants in the window: {dw['n']} tx, {dw['eur']} EUR "
          f"({dw['n_no_mcc']} without MCC, {dw['eur_no_mcc']} EUR); by month: "
          + ", ".join(f"{d['month']} {d['eur']} ({d['n']})" for d in a["direct_dining_by_month"]))
    print(f"  profile: {pr['profile']} {pr['traits']}, keep rate {pr['keep_rate_pct']}%, "
          f"everyday share {pr['everyday_share_pct']}%, regular share {pr['regular_share_pct']}%")
    print(f"  peers ({a['peer_cell_others']} other customers in the cell on the customers table):")
    for r in pe:
        if r["metric"] in ("spend_total", "regular_essentials", "unexpected_necessities", "everyday_spending"):
            print(f"    {r['metric']:<23} you {r['you_month_eur']:>8}  median {r['peer_median_month_eur']}  "
                  f"p25 {r['peer_p25_month_eur']}  p75 {r['peer_p75_month_eur']}  percentile {r['percentile']}  "
                  f"vs median {r['vs_median_pct']}%  {r['peer_level']} {r['peer_group']} n={r['peer_n']} "
                  f"shown={r['shown']} source={r.get('peer_source')}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="frm", default="CUST00000", help="first customer_id, inclusive")
    ap.add_argument("--to", default="CUST02000", help="end customer_id, exclusive (at most 2,000 customers)")
    ap.add_argument("--today", default=os.environ.get("DEMO_TODAY") or "2026-09-30")
    ap.add_argument("--enough", type=int, default=3, help="stop once every slot has this many candidates")
    ap.add_argument("--answers", help="comma-separated customer_ids: compute reference answers only")
    ap.add_argument("--out", help="write the full result as JSON to this file")
    ap.add_argument("--pause", type=float, default=0.5, help="seconds between customer ranges")
    args = ap.parse_args()

    db = None
    cells: dict = {}
    t0 = time.perf_counter()
    result: dict = {"as_of": args.today}
    try:
        db = Db(date.fromisoformat(args.today))
    except Exception as e:
        # Never print a driver error from a connection attempt: psycopg and libpq repeat parts of a
        # malformed DATABASE_URL in their messages, including the password.
        sys.exit(f"{type(e).__name__}: could not connect; check DATABASE_URL")
    try:
        if args.answers:
            result["answers"] = [answers(db, cid.strip(), cells) for cid in args.answers.split(",")]
            for a in result["answers"]:
                print_answer(a)
        else:
            result.update(screen(db, args, cells))
    except psycopg.errors.QueryCanceled:
        sys.exit("stopped at the first database error: a statement hit statement_timeout (60s)")
    except psycopg.OperationalError as e:
        # The message of a connection error can contain the host, so only the class name is printed.
        sys.exit(f"stopped at the first database error: {type(e).__name__} (details hidden)")
    finally:
        if db:
            print(f"-- {db.queries} queries, {db.seconds:.1f} s in the database, "
                  f"{time.perf_counter() - t0:.1f} s total")
    if args.out:
        Path(args.out).write_text(json.dumps(result, default=str, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
