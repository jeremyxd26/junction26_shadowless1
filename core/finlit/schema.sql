-- Financial-literacy retrieval corpus (core/knowledge/finlit) in PostgreSQL with pgvector.
-- Everything lives in schema finlit; the only object outside it is the vector extension.
-- Safe to re-run: creates only what is missing and never drops anything. core/finlit/ingest.py runs it.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS finlit;

-- One row per source (course, guide, curriculum, dataset); doc is the full record from sources.jsonl.
CREATE TABLE IF NOT EXISTS finlit.sources (
    id             text PRIMARY KEY,
    kind           text        NOT NULL,          -- course | dataset
    name           text        NOT NULL,
    publisher      text        NOT NULL,
    tier           text        NOT NULL,
    official       boolean     NOT NULL,
    priority       real        NOT NULL,          -- ranking prior 0..1 (tier weight x verification confidence)
    age_bands      text[]      NOT NULL,          -- app bands 0-12 .. 75+, or all
    topics         text[]      NOT NULL,
    licence_class  text        NOT NULL,
    source_url     text        NOT NULL,
    doc            jsonb       NOT NULL,
    loaded_at      timestamptz NOT NULL DEFAULT now()
);

-- One row per Statistics Finland number; doc keeps the PxWeb query that re-fetches it.
CREATE TABLE IF NOT EXISTS finlit.facts (
    id         text PRIMARY KEY,
    source_id  text             NOT NULL REFERENCES finlit.sources (id),
    tbl        text             NOT NULL,         -- PxWeb table, e.g. StatFin/ktutk/14q4.px
    period     text             NOT NULL,
    value      double precision NOT NULL,
    unit       text             NOT NULL,
    age_bands  text[]           NOT NULL,
    topics     text[]           NOT NULL,
    doc        jsonb            NOT NULL,
    loaded_at  timestamptz      NOT NULL DEFAULT now()
);

-- The retrievable units, one language each. tsv is computed by the loader with the chunk's language.
CREATE TABLE IF NOT EXISTS finlit.chunks (
    id             text PRIMARY KEY,
    source_id      text        NOT NULL REFERENCES finlit.sources (id),
    fact_id        text        REFERENCES finlit.facts (id),
    kind           text        NOT NULL,          -- source_card | page_text | fact
    lang           text        NOT NULL,          -- en | fi (the app's languages)
    title          text        NOT NULL,
    body           text        NOT NULL,
    topics         text[]      NOT NULL,
    age_bands      text[]      NOT NULL,
    lesson_keys    text[]      NOT NULL,
    tier           text        NOT NULL,
    official       boolean     NOT NULL,
    priority       real        NOT NULL,
    licence_class  text        NOT NULL,
    source_url     text        NOT NULL,
    attribution    text        NOT NULL,
    retrieved_at   date        NOT NULL,
    content_hash   text        NOT NULL,          -- sha256 of the embedded text: a changed chunk is re-embedded
    tsv            tsvector    NOT NULL,
    loaded_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin   ON finlit.chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_bands_gin ON finlit.chunks USING gin (age_bands);
CREATE INDEX IF NOT EXISTS chunks_lang_kind ON finlit.chunks (lang, kind);

-- Embeddings per model, so a second model can be compared without touching the first.
CREATE TABLE IF NOT EXISTS finlit.chunk_embeddings (
    chunk_id      text        NOT NULL REFERENCES finlit.chunks (id) ON DELETE CASCADE,
    model         text        NOT NULL,
    content_hash  text        NOT NULL,
    embedding     vector(768) NOT NULL,
    embedded_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (chunk_id, model)
);

-- Corpus version and load bookkeeping.
CREATE TABLE IF NOT EXISTS finlit.meta (
    key         text PRIMARY KEY,
    value       jsonb       NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
