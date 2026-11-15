# finlit: retrieval over official Finnish financial-literacy sources

Retrieval (the R of RAG) for Sentti: given a customer's question, its language (`en` or `fi`, like S-Pankki)
and age band, return the most relevant official sources and Statistics Finland numbers. Nothing here writes
customer-facing text; a lesson or answer cites what comes back.

- **Corpus**: `core/knowledge/finlit/` (sources, chunks, facts; format in its README). English and Finnish only;
  page text only from open-licence sources (CC BY 4.0 or public-domain official guidance).
- **Store**: PostgreSQL with pgvector, schema `finlit` (`schema.sql`): `sources`, `facts`, `chunks` (with a
  per-language `tsvector`), `chunk_embeddings` (one row per chunk and model, `vector(768)`), `meta`.
  Nothing outside the schema except `CREATE EXTENSION IF NOT EXISTS vector`.
- **Embeddings**: Gemini `gemini-embedding-001`, 768 dimensions, L2-normalised; `RETRIEVAL_DOCUMENT` for chunks
  (title + text), `RETRIEVAL_QUERY` for questions. Batched 100 per request, cached in
  `var/finlit-embeddings/`, every request logged in `var/finlit-requests.jsonl`.

## Commands

```bash
python -m core.finlit.ingest --dry-run   # check the corpus, count what would be embedded; no writes, no API
python -m core.finlit.ingest             # schema, corpus sync, embed changed chunks, HNSW index
python -m core.finlit.search "Kuinka paljon ikäiseni kuluttavat ruokaan?" --lang fi --age 25-34
python -m core.finlit.evaluate --parity  # recall/MRR on eval_set.jsonl, HNSW vs exact check
```

They read `DATABASE_URL` and `GEMINI_API_KEY` like the service does (environment, then `.env`).
`FINLIT_EMBED_MODEL` switches the embedding model; vectors per model sit side by side.

A sync refuses to delete more than a quarter of any table unless `--prune` is given, and stale vectors are never
served (the dense query requires the vector's content hash to match the chunk).

Gemini requests: a full ingest of the 1,497 chunks is 15 requests; an unchanged corpus is 0; a new question
is 1 (cached afterwards); the whole eval set is 1. `search --mode lexical` makes none.

## Retrieval

`Retriever.search(question, lang, age_band)` returns two lists with separate quotas:

- `texts`: source cards and open page text, at most 2 chunks per source;
- `facts`: numbers, filtered strictly to the customer's band plus totals (`all`); without a band, totals only.

Each list fuses two legs by weighted reciprocal rank (k = 60):

1. dense: cosine distance in pgvector, filtered on language, kind and age band (band or `all`);
2. lexical: PostgreSQL full text with the language's configuration, the question's words ORed with prefix
   matching (an AND query matches almost nothing for a natural question), weight 0.15;

then multiplies by a source prior `0.75 + 0.25 × priority` (priority = tier weight × verification confidence,
so an official source outranks an equally similar bank page).

## Evaluation

`eval_set.jsonl`: 51 customer questions (28 Finnish, 23 English) across every age band, each written for a
known target (a source for page text and source cards, the fact ids for numbers) and kept only after an
adversarial review (31 kept, 20 rewritten, 6 dropped). Results with `gemini-embedding-001`:

| mode | R@1 | R@3 | R@5 | MRR@10 |
|---|---|---|---|---|
| dense | 0.706 | 0.902 | 0.961 | 0.816 |
| lexical | 0.314 | 0.529 | 0.608 | 0.454 |
| hybrid (lexical 0.15) | 0.745 | 0.863 | 0.961 | 0.823 |
| **hybrid_prior** (default) | **0.784** | **0.882** | **0.961** | **0.851** |

By target (hybrid_prior): facts MRR 0.797 (R@5 1.0; gold is the one fact that answers the question), source cards 0.81, page text 1.0 by source and 0.708 by exact chunk. The weights were chosen on this
same set (no held-out split), so treat the hybrid gain as indicative. Most remaining misses return another
plausible source for the same need. At this size the planner scans exactly instead of using the HNSW
index; `--parity` confirms the index and an exact scan give identical top-10 lists.
