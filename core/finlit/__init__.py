"""Financial-literacy retrieval (RAG) over official Finnish sources and Statistics Finland numbers.

The corpus is data in core/knowledge/finlit (sources, chunks, facts; see its README). This package loads it
into PostgreSQL with pgvector (schema finlit), embeds the chunks with a Gemini embedding model and retrieves
them for a question in the request's language and the customer's age band:

    python -m core.finlit.ingest                     # schema, corpus sync, embeddings, vector index
    python -m core.finlit.search "..." --lang fi --age 25-34
    python -m core.finlit.evaluate                   # recall and MRR on core/finlit/eval_set.jsonl

Retrieval only: nothing here writes customer-facing text. Numbers reach a lesson from facts (value, unit,
period, source), never from model output.
"""
