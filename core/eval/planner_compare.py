"""Compare planner models (#169): round 1 of the service's planner, one request per question.

    SPIKE_REVIEWS=off GEMINI_MODEL=gemini-3.5-flash-lite GEMINI_FALLBACK_MODEL=none python core/eval/planner_compare.py \
        --thinking minimal --ledger var/m169/planner-lite-requests.jsonl --cap 61 --out var/m169/planner-lite.jsonl
    python core/eval/planner_compare.py --summary var/m169/planner-lite.jsonl var/m169/planner-flash.jsonl

Questions: the 39 phrasings the rules do not recognise (issue #340, r-qa's table: 30 as typed and 9 typed
without diacritics), the eval's red-team questions, and three live problem questions with a hand key.
It sends the service's own planner prompt and tool declarations (default_registry), as the pipeline's
first round does, with no history. Every response is cached in var/gemini-cache; the ledger caps the
requests; a refused or failed call is recorded and never retried, and a 429, a refused key or model, or
the cap stops the run."""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from core.agent import guard  # noqa: E402
from core.agent.gemini import make_model  # noqa: E402
from core.agent.model import ModelError, PlanInput  # noqa: E402
from core.agent.toolset import default_registry  # noqa: E402

SERVER_ERROR_WAIT_S = 31.0   # longer than the adapter's short pause after a 5xx (30 s on main and on dev)
Q1, Q2, Q3, Q4 = (["get_basket_breakdown"], ["get_spender_profile"], ["get_safe_to_spend"],
                  ["get_safe_to_save", "get_basket_breakdown"])
# (phrasing, language, intent, any of these tools is right, also typed without diacritics)
UNRECOGNISED = [
    ("where does all my money disappear to?", "en", "q1", Q1, False),
    ("what am I spending the most on?", "en", "q1", Q1, False),
    ("show me my spending breakdown", "en", "q1", Q1, False),
    ("wher did my mony go", "en", "q1", Q1, False),
    ("Mihin kaikki rahani on mennyt?", "fi", "q1", Q1, False),
    ("mihin mun rahat menee", "fi", "q1", Q1, False),
    ("Mihin käytän eniten rahaa?", "fi", "q1", Q1, True),
    ("what's my spending style?", "en", "q2", Q2, False),
    ("describe my spending habits", "en", "q2", Q2, False),
    ("be honest, am I a good or bad spender?", "en", "q2", Q2, False),
    ("what knd of spender am i", "en", "q2", Q2, False),
    ("Millainen rahankäyttäjä olen?", "fi", "q2", Q2, True),
    ("Olenko tuhlari?", "fi", "q2", Q2, False),
    ("millanen kuluttaja mä oon", "fi", "q2", Q2, True),
    ("milainen kuluttaja olen", "fi", "q2", Q2, False),
    ("how much can i spend till next friday without getting into trouble", "en", "q3", Q3, False),
    ("what can i safly spend this wek", "en", "q3", Q3, False),
    ("paljon mä voin käyttää tällä viikol", "fi", "q3", Q3, True),
    ("how can I save money?", "en", "q4", Q4, False),
    ("where can I cut back?", "en", "q4", Q4, False),
    ("help me spend less", "en", "q4", Q4, False),
    ("any tips to save a bit more each month?", "en", "q4", Q4, False),
    ("how can I put more money aside each month?", "en", "q4", Q4, False),
    ("what's a realistic amount I could save monthly?", "en", "q4", Q4, False),
    ("how culd i save mor", "en", "q4", Q4, False),
    ("Miten voisin säästää?", "fi", "q4", Q4, True),
    ("Missä voisin säästää?", "fi", "q4", Q4, True),
    ("Miten saisin rahaa säästöön?", "fi", "q4", Q4, True),
    ("paljonko voisin laittaa säästöön kuussa?", "fi", "q4", Q4, True),
    ("miten voisin säästä enemmän rahaa joka kuu", "fi", "q4", Q4, True),
]
LIVE = [
    ("what was that €1,080?", "en", "live_purchase", ["ask_clarifying_question", "get_spending"]),
    ("what if I took 10% fewer taxis?", "en", "live_taxi_what_if", ["run_what_if"]),
    ("is it ok if i spend a bit this week, what's my limit?", "en", "live_limit", Q3),
]


def without_dots(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def questions() -> list[dict]:
    out = []
    for q, lang, intent, key, folded in UNRECOGNISED:
        out.append({"set": "unrecognised", "question": q, "lang": lang, "intent": intent, "key": key})
        if folded:
            out.append({"set": "unrecognised", "question": without_dots(q), "lang": lang, "intent": intent, "key": key})
    cases = yaml.safe_load(open(ROOT / "core" / "eval" / "cases.yaml", encoding="utf-8"))["cases"]
    for c in cases:
        if "red_team" in c["tags"]:
            for lang, q in c["question"].items():
                out.append({"set": "red_team", "question": q, "lang": lang, "intent": c["id"], "key": ["decline"],
                            "refusal_kinds": c.get("refusal_kinds") or []})
    for q, lang, intent, key in LIVE:
        out.append({"set": "live", "question": q, "lang": lang, "intent": intent, "key": key})
    return out


def grade(item: dict, names: list[str], decline_kind: str | None) -> str:
    if not names:
        return "no call"
    if any(n in item["key"] for n in names):
        if item["set"] == "red_team" and item.get("refusal_kinds") and decline_kind not in item["refusal_kinds"]:
            return "right (other refusal kind)"
        return "right"
    if "ask_clarifying_question" in names:
        return "clarify"
    if "decline" in names:
        return "declined"
    return "wrong tool"


def summarise(rows: list[dict]) -> dict:
    """Accuracy per question set, latency (median, p90, max) and the slowest questions."""
    from collections import Counter
    from statistics import median

    out: dict = {"questions": len(rows), "requests": sum(r["network"] for r in rows)}
    for name in ("unrecognised", "red_team", "live"):
        part = [r for r in rows if r["set"] == name]
        out[name] = {"n": len(part), "grades": dict(Counter(r["grade"] for r in part)),
                     "right": sum(r["grade"].startswith("right") for r in part)}
    ms = sorted(r["latency_ms"] for r in rows if not r["error"])
    out["latency_ms"] = {"median": median(ms) if ms else None, "p90": ms[round(0.9 * (len(ms) - 1))] if ms else None,
                         "max": ms[-1] if ms else None}
    out["slowest"] = [(r["latency_ms"], r["question"]) for r in sorted(rows, key=lambda r: -r["latency_ms"])[:3]]
    out["errors"] = dict(Counter(r["error"] for r in rows if r["error"]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--thinking")
    ap.add_argument("--ledger")
    ap.add_argument("--cap", type=int)
    ap.add_argument("--out")
    ap.add_argument("--limit", type=int, default=0, help="only the first N questions (a probe)")
    ap.add_argument("--summary", nargs="+", help="print the summary of these output files and exit")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.summary:
        for path in args.summary:
            print(path, json.dumps(summarise([json.loads(x) for x in open(path, encoding="utf-8")]),
                                   ensure_ascii=False, indent=1))
        return
    import os
    os.environ["MODEL_DAILY_BUDGET"] = str(args.cap)
    model = make_model(ledger_path=ROOT / args.ledger, plan_thinking=args.thinking, compose_thinking=args.thinking)
    if model is None:
        sys.exit("GEMINI_API_KEY is not set")
    tools = default_registry().schemas()
    items = questions()
    if args.limit:
        items = items[:args.limit]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "a", encoding="utf-8") as f:
        for item in items:
            q = item["question"]
            n_calls = len(model.client.calls)
            t0 = time.perf_counter()
            try:
                result = model.plan(PlanInput(question=q, language=item["lang"], as_of="2026-09-30", tools=tools,
                                              guard_flags=guard.flags(q), round=1))
                names = [c.name for c in result.calls]
                decline = next((c.args.get("kind") for c in result.calls if c.name == "decline"), None)
                args_by = {c.name: c.args for c in result.calls}
                error = None
            except ModelError as exc:
                names, decline, args_by, error = [], None, {}, str(exc)
            wall = int((time.perf_counter() - t0) * 1000)
            rec = model.client.calls[n_calls:]
            line = {**item, "model": model.client.model, "calls": names, "args": args_by, "decline_kind": decline,
                    "grade": grade(item, names, decline) if error is None else f"error {error}",
                    "latency_ms": rec[-1].latency_ms if rec else wall, "cached": bool(rec and rec[-1].cached),
                    "network": sum(r.network for r in rec), "error": error}
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
            print(f"{line['grade']:<28} {line['latency_ms']:>6} ms  {names}  {q}", flush=True)
            if error and ("rate_limited" in error or error.startswith("http_4") or error in ("budget", "pause")):
                print("stopping: " + error, flush=True)
                break
            if error == "server" and line["network"]:
                # A 5xx may pause the adapter for a short while (its overload or failure-streak pause, whose
                # name differs between versions); wait it out, so the next questions are asked instead of
                # being refused by the pause. Never a retry.
                time.sleep(SERVER_ERROR_WAIT_S)


if __name__ == "__main__":
    main()
