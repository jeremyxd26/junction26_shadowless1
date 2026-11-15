"""Measure retrieval on the verified eval set (core/finlit/eval_set.jsonl).

Usage:
    python -m core.finlit.evaluate [--model gemini-embedding-001] [--parity]

Each item is a customer question with its language, age band and gold answer: a source id for page-text and
source-card targets (scored on the texts list), the one fact that answers it for fact targets (scored on the
facts list). Page-text items are also scored on their exact chunk (kind:page_text@chunk).
Every question is embedded in one batched request (cached afterwards). Reports recall@1/3/5 and MRR@10 for
the dense, lexical, hybrid and hybrid_prior modes, overall and by target kind and language. --parity checks
that the HNSW index returns the same dense top 10 as an exact scan.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from core.finlit.embed import QUERY, Embedder, gemini_client
from core.finlit.retrieve import MODES, Retriever
from core.finlit.settings import FinlitSettings
from core.finlit import store

EVAL_SET = Path(__file__).with_name("eval_set.jsonl")
K = 10


def first_hit(item: dict, res) -> int | None:
    if item["target_kind"] == "fact":
        gold, hits, key = set(item["gold_fact_ids"]), res.facts, "fact_id"
    else:
        gold, hits, key = set(item["gold_source_ids"]), res.texts, "source_id"
    for rank, h in enumerate(hits, 1):
        if getattr(h, key) in gold:
            return rank
    return None


def chunk_hit(item: dict, res) -> int | None:
    """Rank of the exact target chunk among the texts (page_text items): stricter than any chunk of the source."""
    for rank, h in enumerate(res.texts, 1):
        if h.chunk_id == item["target_chunk_id"]:
            return rank
    return None


def summarise(ranks: list[int | None]) -> dict:
    n = len(ranks) or 1
    return {"n": len(ranks),
            **{f"recall@{k}": round(sum(1 for r in ranks if r and r <= k) / n, 3) for k in (1, 3, 5)},
            "mrr@10": round(sum(1 / r for r in ranks if r) / n, 3)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model")
    ap.add_argument("--set", default=str(EVAL_SET))
    ap.add_argument("--parity", action="store_true")
    ap.add_argument("--out", help="write per-question results as JSON here")
    a = ap.parse_args(argv)
    s = FinlitSettings()
    if s.database_url is None or s.gemini_api_key is None:
        sys.exit("DATABASE_URL and GEMINI_API_KEY are needed (environment or .env)")
    model = a.model or s.finlit_embed_model
    items = [json.loads(x) for x in Path(a.set).read_text(encoding="utf-8").splitlines() if x.strip()]
    embedder = Embedder(gemini_client(s.gemini_api_key.get_secret_value()), model)
    qvecs = embedder.embed([it["question"] for it in items], QUERY)
    report, per_q = {}, []
    with store.connect(s.database_url.get_secret_value(), statement_timeout_s=30) as conn:
        retriever = Retriever(conn, embedder, model)
        for mode in MODES:
            buckets: dict[str, list] = defaultdict(list)
            for it, qv in zip(items, qvecs):
                res = retriever.search(it["question"], it["lang"], it["age_band"], k_texts=K, k_facts=K, mode=mode,
                                       query_vec=qv)
                r = first_hit(it, res)
                for b in ("all", f"kind:{it['target_kind']}", f"lang:{it['lang']}"):
                    buckets[b].append(r)
                if it["target_kind"] == "page_text":
                    buckets["kind:page_text@chunk"].append(chunk_hit(it, res))
                if mode == "hybrid_prior":
                    per_q.append({"id": it["id"], "question": it["question"], "lang": it["lang"],
                                  "age_band": it["age_band"], "kind": it["target_kind"], "rank": r,
                                  "top_texts": [h.source_id for h in res.texts[:3]],
                                  "top_facts": [h.fact_id for h in res.facts[:3]]})
            report[mode] = {b: summarise(v) for b, v in sorted(buckets.items())}
        if a.parity:
            exact = Retriever(conn, None, model, exact=True)
            same = 0
            for it, qv in zip(items, qvecs):
                ra = retriever.search(it["question"], it["lang"], it["age_band"], K, K, mode="dense", query_vec=qv)
                rb = exact.search(it["question"], it["lang"], it["age_band"], K, K, mode="dense", query_vec=qv)
                same += [h.chunk_id for h in ra.texts + ra.facts] == [h.chunk_id for h in rb.texts + rb.facts]
            report["parity_hnsw_vs_exact"] = f"{same}/{len(items)} identical dense top-{K} lists"
            plan = retriever.dense_plan(qvecs[0], items[0]["lang"], items[0]["age_band"])
            report["hnsw_index_used"] = "hnsw" in plan.lower()
    for mode in MODES:
        row = report[mode]["all"]
        print(f"{mode:13} n={row['n']}  R@1 {row['recall@1']:.3f}  R@3 {row['recall@3']:.3f}  "
              f"R@5 {row['recall@5']:.3f}  MRR@10 {row['mrr@10']:.3f}")
    print(json.dumps(report, indent=1))
    print(f"Gemini requests: {embedder.calls} (cache hits {embedder.cache_hits})")
    if a.out:
        Path(a.out).write_text(json.dumps({"model": model, "report": report, "questions": per_q},
                                          ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
