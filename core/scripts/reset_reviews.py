"""Demo reset for spike reviews (#68): delete the named customers' rows from `spike_reviews`.

Labels live only in that table and in every viewer's answers to it (`spike_review_answers`, #144),
which go with it (ON DELETE CASCADE). A reset therefore returns these customers to the published
numbers for every viewer, and the next overview asks about their spike again (the weekly limit counts
only rows that exist). It refuses to run without explicit customer ids, and it touches nothing else.
One presenter alone gets a fresh state without this script: open /api/viewer/reset or a new private
window.

Usage (from the repository root; DATABASE_URL from the environment or .env):
    python core/scripts/reset_reviews.py CUST00860
    python core/scripts/reset_reviews.py CUST00860 CUST00493 CUST00387 CUST00849   # the four personas
    python core/scripts/reset_reviews.py --dry-run CUST00860                        # show, delete nothing
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.tools import db, reviews  # noqa: E402

CUSTOMER_ID = re.compile(r"^CUST[0-9]{5}$")


def parse(argv: list[str] | None) -> argparse.Namespace | None:
    parser = argparse.ArgumentParser(description="Delete the spike reviews of the named customers.")
    parser.add_argument("customer_ids", nargs="*", help="one or more ids, for example CUST00860")
    parser.add_argument("--dry-run", action="store_true", help="show the rows, delete nothing")
    args = parser.parse_args(argv)
    if not args.customer_ids:
        print("refusing to run: name the customers to reset, for example CUST00860", file=sys.stderr)
        return None
    bad = [c for c in args.customer_ids if not CUSTOMER_ID.fullmatch(c)]
    if bad:
        print(f"refusing to run: not a customer id: {', '.join(bad)}", file=sys.stderr)
        return None
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    if args is None:
        return 2
    ids = sorted(set(args.customer_ids))
    conn = db.connect()
    try:
        now = reviews.utcnow()
        for customer_id in ids:
            states = Counter(r.state(now) for r in reviews.load_reviews(conn, customer_id))
            shown = ", ".join(f"{n} {s}" for s, n in sorted(states.items())) or "no reviews"
            print(f"{customer_id}: {shown}; {reviews.count_answers(conn, [customer_id])} viewer answers")
        if args.dry_run:
            print("dry run: nothing deleted")
            return 0
        print(f"deleted {reviews.reset(conn, ids)} review rows")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
