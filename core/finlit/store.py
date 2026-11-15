"""PostgreSQL side of finlit: schema, corpus sync, embeddings and the vector index, all inside schema finlit.

Every write is idempotent: rows are upserted by id, rows whose id left the corpus are deleted (only inside
finlit), and a chunk is re-embedded only when its content hash changed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import psycopg

from core.finlit.corpus import TS_CONFIG, Corpus, content_hash, corpus_version, embed_text

SCHEMA = Path(__file__).with_name("schema.sql")
MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,62}$")


class DatabaseUnavailable(RuntimeError):
    """The connection failed. The message never repeats the driver's text, which can echo DATABASE_URL."""


def connect(database_url: str, statement_timeout_s: int = 120) -> psycopg.Connection:
    try:
        return psycopg.connect(database_url, connect_timeout=15,
                               options=f"-c statement_timeout={statement_timeout_s * 1000}")
    except Exception as exc:  # noqa: BLE001 - any failure here may carry parts of the URL
        raise DatabaseUnavailable(f"could not connect to the database ({type(exc).__name__}); check DATABASE_URL") from None


def ensure_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()


def vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


MAX_PRUNE_SHARE = 0.25   # without prune=True, a sync may delete at most this share of a table's rows


def sync_corpus(conn: psycopg.Connection, corpus: Corpus, prune: bool = False) -> dict[str, int]:
    """Upsert sources, facts and chunks; delete what left the corpus. Returns counts.

    The schema is shared, so a sync refuses to delete more than MAX_PRUNE_SHARE of any table (an empty,
    truncated or older corpus would otherwise wipe it) unless prune=True."""
    wanted = {"chunks": [c["id"] for c in corpus.chunks], "facts": [f["id"] for f in corpus.facts],
              "sources": [s["id"] for s in corpus.sources]}
    for table, ids in wanted.items():
        if not ids:
            raise ValueError(f"refusing to sync: the corpus has no {table}")
        existing, gone = conn.execute(f"SELECT count(*), count(*) FILTER (WHERE NOT (id = ANY(%s))) FROM finlit.{table}",
                                      (ids,)).fetchone()
        if existing and gone > MAX_PRUNE_SHARE * existing and not prune:
            raise ValueError(f"refusing to delete {gone} of {existing} rows from finlit.{table}; "
                             "pass --prune if the corpus really shrank")
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO finlit.sources (id, kind, name, publisher, tier, official, priority, age_bands, topics,
                                           licence_class, source_url, doc)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET kind = EXCLUDED.kind, name = EXCLUDED.name, publisher = EXCLUDED.publisher,
                   tier = EXCLUDED.tier, official = EXCLUDED.official, priority = EXCLUDED.priority,
                   age_bands = EXCLUDED.age_bands, topics = EXCLUDED.topics, licence_class = EXCLUDED.licence_class,
                   source_url = EXCLUDED.source_url, doc = EXCLUDED.doc, loaded_at = now()""",
            [(s["id"], s["kind"], s["name"] or s["name_en"], s["publisher"], s["tier"], s["official"], s["priority"],
              s["age_bands"], s["topics"], s["licence_class"], s["source_url"], json.dumps(s, ensure_ascii=False))
             for s in corpus.sources])
        cur.executemany(
            """INSERT INTO finlit.facts (id, source_id, tbl, period, value, unit, age_bands, topics, doc)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET source_id = EXCLUDED.source_id, tbl = EXCLUDED.tbl, period = EXCLUDED.period,
                   value = EXCLUDED.value, unit = EXCLUDED.unit, age_bands = EXCLUDED.age_bands, topics = EXCLUDED.topics,
                   doc = EXCLUDED.doc, loaded_at = now()""",
            [(f["id"], f["source_id"], f["table"], f["period"], f["value"], f["unit"], f["age_bands"], f["topics"],
              json.dumps(f, ensure_ascii=False)) for f in corpus.facts])
        cur.executemany(
            """INSERT INTO finlit.chunks (id, source_id, fact_id, kind, lang, title, body, topics, age_bands, lesson_keys,
                                          tier, official, priority, licence_class, source_url, attribution,
                                          retrieved_at, content_hash, tsv)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       to_tsvector(%s::regconfig, %s))
               ON CONFLICT (id) DO UPDATE SET source_id = EXCLUDED.source_id, fact_id = EXCLUDED.fact_id,
                   kind = EXCLUDED.kind, lang = EXCLUDED.lang, title = EXCLUDED.title, body = EXCLUDED.body,
                   topics = EXCLUDED.topics, age_bands = EXCLUDED.age_bands, lesson_keys = EXCLUDED.lesson_keys,
                   tier = EXCLUDED.tier, official = EXCLUDED.official, priority = EXCLUDED.priority,
                   licence_class = EXCLUDED.licence_class, source_url = EXCLUDED.source_url,
                   attribution = EXCLUDED.attribution, retrieved_at = EXCLUDED.retrieved_at,
                   content_hash = EXCLUDED.content_hash, tsv = EXCLUDED.tsv, loaded_at = now()""",
            [(c["id"], c["source_id"], c.get("fact_id"), c["kind"], c["lang"], c["title"], c["text"], c["topics"],
              c["age_bands"], c.get("lesson_keys") or [], c["tier"], c["official"], c["priority"], c["licence_class"],
              c["source_url"], c["attribution"], c["retrieved_at"], content_hash(c), TS_CONFIG[c["lang"]],
              embed_text(c)) for c in corpus.chunks])
        deleted = {}
        for table, ids in wanted.items():
            cur.execute(f"DELETE FROM finlit.{table} WHERE NOT (id = ANY(%s))", (ids,))
            deleted[table] = cur.rowcount
        cur.execute("""INSERT INTO finlit.meta (key, value) VALUES ('corpus', %s)
                       ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""",
                    (json.dumps({"version": corpus_version(corpus), "built_at": corpus.manifest.get("built_at"),
                                 "sources": len(corpus.sources), "facts": len(corpus.facts),
                                 "chunks": len(corpus.chunks)}),))
    conn.commit()
    return {"sources": len(corpus.sources), "facts": len(corpus.facts), "chunks": len(corpus.chunks),
            **{f"deleted_{k}": v for k, v in deleted.items()}}


def stale_embeddings(conn: psycopg.Connection, model: str) -> list[str]:
    """Chunk ids with no embedding for `model`, or one made from different content."""
    rows = conn.execute("""SELECT c.id FROM finlit.chunks c
                           LEFT JOIN finlit.chunk_embeddings e ON e.chunk_id = c.id AND e.model = %s
                           WHERE e.chunk_id IS NULL OR e.content_hash <> c.content_hash
                           ORDER BY c.id""", (model,)).fetchall()
    return [r[0] for r in rows]


def embedded_hashes(conn: psycopg.Connection, model: str) -> dict[str, str]:
    """chunk id -> content hash of the text its stored `model` embedding was made from."""
    return dict(conn.execute("SELECT chunk_id, content_hash FROM finlit.chunk_embeddings WHERE model = %s",
                             (model,)).fetchall())


def upsert_embeddings(conn: psycopg.Connection, model: str, rows: list[tuple[str, str, list[float]]]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO finlit.chunk_embeddings (chunk_id, model, content_hash, embedding)
               VALUES (%s, %s, %s, %s::vector)
               ON CONFLICT (chunk_id, model) DO UPDATE SET content_hash = EXCLUDED.content_hash,
                   embedding = EXCLUDED.embedding, embedded_at = now()""",
            [(cid, model, h, vector_literal(v)) for cid, h, v in rows])
    conn.commit()


def index_name(model: str) -> str:
    return "chunk_embeddings_hnsw_" + re.sub(r"[^a-z0-9]+", "_", model)


def ensure_vector_index(conn: psycopg.Connection, model: str) -> str:
    """An HNSW cosine index over one model's vectors (a partial index, so models never mix)."""
    if not MODEL_RE.match(model):
        raise ValueError(f"unexpected model name {model!r}")
    name = index_name(model)
    conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON finlit.chunk_embeddings "
                 f"USING hnsw (embedding vector_cosine_ops) WHERE model = '{model}'")
    conn.commit()
    return name


def counts(conn: psycopg.Connection) -> dict:
    out = {t: conn.execute(f"SELECT count(*) FROM finlit.{t}").fetchone()[0]
           for t in ("sources", "facts", "chunks", "chunk_embeddings")}
    out["embeddings_by_model"] = dict(conn.execute(
        "SELECT model, count(*) FROM finlit.chunk_embeddings GROUP BY model ORDER BY model").fetchall())
    out["size"] = conn.execute("""SELECT pg_size_pretty(sum(pg_total_relation_size(c.oid)))
                                  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                                  WHERE n.nspname = 'finlit' AND c.relkind = 'r'""").fetchone()[0]
    return out
