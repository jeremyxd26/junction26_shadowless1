"""Load the finlit corpus into PostgreSQL and embed it.

Usage:
    python -m core.finlit.ingest              # schema, corpus sync, embeddings for changed chunks, vector index
    python -m core.finlit.ingest --dry-run    # check the corpus and count what would be embedded; no writes, no API
    python -m core.finlit.ingest --model gemini-embedding-2
    python -m core.finlit.ingest --prune      # only when the corpus really lost more than a quarter of a table

Reads DATABASE_URL and GEMINI_API_KEY from the environment or the repository's .env. Writes only inside schema
finlit (plus CREATE EXTENSION IF NOT EXISTS vector). Prints how many Gemini requests it made.
"""

from __future__ import annotations

import argparse
import sys
import time

from core.finlit.corpus import check_corpus, content_hash, embed_text, load_corpus
from core.finlit.embed import DOCUMENT, Embedder, gemini_client
from core.finlit.settings import FinlitSettings
from core.finlit import store


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", help="embedding model (default FINLIT_EMBED_MODEL or gemini-embedding-001)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prune", action="store_true", help="allow deleting more than a quarter of a table's rows")
    a = ap.parse_args(argv)
    settings = FinlitSettings()
    model = a.model or settings.finlit_embed_model
    if not store.MODEL_RE.match(model):
        sys.exit(f"unexpected model name {model!r}")
    corpus = load_corpus()
    errs = check_corpus(corpus)
    if errs:
        print("corpus check failed:", *errs[:20], sep="\n  ")
        return 1
    if settings.database_url is None:
        sys.exit("DATABASE_URL is not set (environment or .env)")
    t0 = time.monotonic()
    try:
        conn = store.connect(settings.database_url.get_secret_value())
    except store.DatabaseUnavailable as exc:
        sys.exit(str(exc))
    with conn:
        exists = conn.execute("SELECT to_regclass('finlit.chunk_embeddings') IS NOT NULL").fetchone()[0]
        have = store.embedded_hashes(conn, model) if exists else {}
        conn.commit()
        pending = [c["id"] for c in corpus.chunks if have.get(c["id"]) != content_hash(c)]   # corpus on disk vs DB
        if a.dry_run:
            print(f"corpus ok: {len(corpus.sources)} sources, {len(corpus.facts)} facts, {len(corpus.chunks)} chunks; "
                  f"schema {'exists' if exists else 'missing'}; {len(pending)} chunks to embed with {model} "
                  f"(at most {-(-len(pending) // 100)} requests, fewer with the local cache)")
            return 0
        if pending and settings.gemini_api_key is None:     # before any write: never sync without the means to embed
            sys.exit("GEMINI_API_KEY is not set (environment or .env)")
        store.ensure_schema(conn)
        try:
            synced = store.sync_corpus(conn, corpus, prune=a.prune)
        except ValueError as exc:
            conn.rollback()
            sys.exit(str(exc))
        print("synced:", synced)
        todo = store.stale_embeddings(conn, model)
        conn.commit()                                       # no transaction stays open across Gemini calls
        embedder = None
        if todo:
            embedder = Embedder(gemini_client(settings.gemini_api_key.get_secret_value()), model)
            by_id = {c["id"]: c for c in corpus.chunks}
            for start in range(0, len(todo), 500):
                ids = todo[start:start + 500]
                vecs = embedder.embed([embed_text(by_id[i]) for i in ids], DOCUMENT)
                store.upsert_embeddings(conn, model, [(i, content_hash(by_id[i]), v) for i, v in zip(ids, vecs)])
                print(f"embedded {min(start + 500, len(todo))}/{len(todo)} (requests so far: {embedder.calls})")
        index = store.ensure_vector_index(conn, model)
        print("index:", index)
        print("database:", store.counts(conn))
    print(f"model {model}: {len(todo)} chunks embedded, Gemini requests {embedder.calls if embedder else 0}, "
          f"cache hits {embedder.cache_hits if embedder else 0}, {time.monotonic() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
