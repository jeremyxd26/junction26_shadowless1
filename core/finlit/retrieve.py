"""Retrieval over finlit.chunks: dense (pgvector cosine) and lexical (PostgreSQL full text) legs fused by
reciprocal rank, weighted by the source's priority.

Two separate result lists, each with its own quota:
- texts: source cards and open-licence page text, at most `per_source` chunks from one source;
- facts: Statistics Finland numbers, filtered strictly to the customer's age band plus the totals ("all"); with
  no band, the totals only.
Every leg filters on the request's language (en or fi) and, for texts, the age band (band or "all") when given.

The lexical leg ORs the question's words (prefix match from 4 letters), because websearch_to_tsquery ANDs them
and a natural question then matches almost nothing. With its default weight (0.15 against 1.0 for the dense leg)
it re-ranks the dense candidates; a chunk only the lexical leg finds cannot outrank the dense pool. The source
prior (0.75 + 0.25 x priority by default) can move a chunk several ranks; both weights were tuned on
core/finlit/eval_set.jsonl, which has no held-out split.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import psycopg

from core.finlit.corpus import APP_BANDS, TS_CONFIG
from core.finlit.embed import QUERY, Embedder
from core.finlit.store import vector_literal

TEXT_KINDS = ["page_text", "source_card"]
FACT_KINDS = ["fact"]
MODES = ("dense", "lexical", "hybrid", "hybrid_prior")
RRF_K = 60
WORD = re.compile(r"[^\W\d_]{2,}|\d{2,}")


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    source_id: str
    kind: str
    title: str
    text: str
    source_url: str
    attribution: str
    fact_id: str | None
    priority: float
    score: float
    dense_rank: int | None
    lexical_rank: int | None


@dataclass(frozen=True)
class Result:
    texts: list[Hit]
    facts: list[Hit]


def tsquery_text(question: str) -> str | None:
    """'how much do people spend on food' -> 'how | much:* | do | ...': words ORed, prefix match from 4 letters.
    Only letters and digits reach to_tsquery, so the string can carry no operator of its own."""
    words: list[str] = []
    for w in WORD.findall(unicodedata.normalize("NFC", question).lower()):
        if w not in words:
            words.append(w)
    if not words:
        return None
    return " | ".join(f"{w}:*" if len(w) >= 4 else w for w in words[:40])


def rrf(rankings: list[list[str]], k: int = RRF_K, weights: list[float] | None = None) -> dict[str, float]:
    scores: dict[str, float] = {}
    for i, ranking in enumerate(rankings):
        w = weights[i] if weights else 1.0
        for rank, cid in enumerate(ranking, 1):
            scores[cid] = scores.get(cid, 0.0) + w / (k + rank)
    return scores


def with_prior(scores: dict[str, float], priority: dict[str, float], weight: float = 1.0) -> dict[str, float]:
    """Scale each score by (1 - w/2) + (w/2) x priority; with w = 1 that is 0.5 + 0.5 x priority, so an official
    source outranks an equally similar bank blog."""
    return {cid: s * ((1 - weight / 2) + (weight / 2) * priority.get(cid, 0.5)) for cid, s in scores.items()}


def top(scores: dict[str, float], source_of: dict[str, str], k: int, per_source: int | None) -> list[str]:
    out: list[str] = []
    if k <= 0:
        return out
    taken: dict[str, int] = {}
    for cid in sorted(scores, key=lambda c: (-scores[c], c)):
        src = source_of[cid]
        if per_source is not None and taken.get(src, 0) >= per_source:
            continue
        out.append(cid)
        taken[src] = taken.get(src, 0) + 1
        if len(out) == k:
            break
    return out


class Retriever:
    def __init__(self, conn: psycopg.Connection, embedder: Embedder | None, model: str, pool: int = 40,
                 exact: bool = False, lexical_weight: float = 0.15, prior_weight: float = 0.5) -> None:
        self.conn = conn
        self.embedder = embedder
        self.model = model
        self.pool = pool
        # Filtered HNSW scans keep going until enough rows pass the filters, in distance order;
        # exact=True turns the index off (used to check that the index returns what an exact scan would).
        self.exact = exact
        self.lexical_weight = lexical_weight   # the lexical leg's weight in the fusion (dense = 1)
        self.prior_weight = prior_weight       # 1: score x (0.5 + 0.5 x priority); 0: no prior
        conn.execute("SET hnsw.iterative_scan = strict_order")
        conn.execute("SET hnsw.ef_search = 100")

    def search(self, question: str, lang: str, age_band: str | None = None, k_texts: int = 5, k_facts: int = 5,
               mode: str = "hybrid_prior", per_source: int = 2, query_vec: list[float] | None = None) -> Result:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if lang not in TS_CONFIG:
            raise ValueError(f"lang must be one of {sorted(TS_CONFIG)}")
        if age_band is not None and age_band not in APP_BANDS:
            raise ValueError(f"age_band must be None or one of {APP_BANDS}")
        if query_vec is None and mode != "lexical":
            if self.embedder is None:
                raise ValueError("an embedder or query_vec is needed for dense retrieval")
            query_vec = self.embedder.embed([question], QUERY)[0]
        text_bands = None if age_band is None else [age_band, "all"]
        fact_bands = ["all"] if age_band is None else [age_band, "all"]   # never another group's numbers
        texts = self._group(question, lang, text_bands, TEXT_KINDS, k_texts, mode, per_source, query_vec)
        facts = self._group(question, lang, fact_bands, FACT_KINDS, k_facts, mode, None, query_vec)
        return Result(texts, facts)

    def _group(self, question, lang, bands, kinds, k, mode, per_source, qv) -> list[Hit]:
        if k <= 0:
            return []
        dense = self._dense(qv, lang, bands, kinds) if mode != "lexical" else []
        lexical = self._lexical(question, lang, bands, kinds) if mode != "dense" else []
        legs = [(r, w) for r, w in ((dense, 1.0), (lexical, self.lexical_weight)) if r and w > 0]
        if not legs:
            return []
        scores = rrf([r for r, _ in legs], weights=[w for _, w in legs])
        rows = self._rows(list(scores))
        if mode == "hybrid_prior" and self.prior_weight:
            scores = with_prior(scores, {cid: r["priority"] for cid, r in rows.items()}, self.prior_weight)
        chosen = top(scores, {cid: r["source_id"] for cid, r in rows.items()}, k, per_source)
        drank = {cid: i for i, cid in enumerate(dense, 1)}
        lrank = {cid: i for i, cid in enumerate(lexical, 1)}
        return [Hit(cid, rows[cid]["source_id"], rows[cid]["kind"], rows[cid]["title"], rows[cid]["body"],
                    rows[cid]["source_url"], rows[cid]["attribution"], rows[cid]["fact_id"], rows[cid]["priority"],
                    round(scores[cid], 6), drank.get(cid), lrank.get(cid)) for cid in chosen]

    DENSE_SQL = """SELECT c.id FROM finlit.chunk_embeddings e JOIN finlit.chunks c ON c.id = e.chunk_id
               WHERE e.model = %(model)s AND e.content_hash = c.content_hash
                 AND c.lang = %(lang)s AND c.kind = ANY(%(kinds)s)
                 AND (%(bands)s::text[] IS NULL OR c.age_bands && %(bands)s::text[])
               ORDER BY e.embedding <=> %(qv)s::vector LIMIT %(pool)s"""

    def _dense_params(self, qv, lang, bands, kinds) -> dict:
        return {"model": self.model, "lang": lang, "kinds": kinds, "bands": bands, "qv": vector_literal(qv),
                "pool": self.pool}

    def dense_plan(self, qv, lang, band, kinds=TEXT_KINDS) -> str:
        bands = None if band is None else [band, "all"]
        """EXPLAIN of the dense query, to see whether the HNSW index is used."""
        self.conn.execute(f"SET enable_indexscan = {'off' if self.exact else 'on'}")
        rows = self.conn.execute("EXPLAIN " + self.DENSE_SQL, self._dense_params(qv, lang, bands, kinds)).fetchall()
        return "\n".join(r[0] for r in rows)

    def _dense(self, qv, lang, bands, kinds) -> list[str]:
        self.conn.execute(f"SET enable_indexscan = {'off' if self.exact else 'on'}")
        rows = self.conn.execute(self.DENSE_SQL, self._dense_params(qv, lang, bands, kinds)).fetchall()
        return [r[0] for r in rows]

    def _lexical(self, question, lang, bands, kinds) -> list[str]:
        tsq = tsquery_text(question)
        if not tsq:
            return []
        rows = self.conn.execute(
            """SELECT c.id FROM finlit.chunks c, to_tsquery(%(cfg)s::regconfig, %(tsq)s) q
               WHERE c.lang = %(lang)s AND c.kind = ANY(%(kinds)s) AND c.tsv @@ q
                 AND (%(bands)s::text[] IS NULL OR c.age_bands && %(bands)s::text[])
               ORDER BY ts_rank_cd(c.tsv, q) DESC, c.id LIMIT %(pool)s""",
            {"cfg": TS_CONFIG[lang], "tsq": tsq, "lang": lang, "kinds": kinds, "bands": bands,
             "pool": self.pool}).fetchall()
        return [r[0] for r in rows]

    def _rows(self, ids: list[str]) -> dict[str, dict]:
        cur = self.conn.execute(
            """SELECT id, source_id, kind, title, body, source_url, attribution, fact_id, priority
               FROM finlit.chunks WHERE id = ANY(%s)""", (ids,))
        cols = [d.name for d in cur.description]
        return {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}
