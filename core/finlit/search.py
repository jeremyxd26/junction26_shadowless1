"""Ask the finlit index one question and print what it retrieves.

Usage:
    python -m core.finlit.search "Kuinka paljon ikäiseni kuluttavat ruokaan?" --lang fi --age 25-34
    python -m core.finlit.search "..." --mode lexical          # no Gemini request at all
One Gemini embedding request per new question (cached afterwards); the lexical mode makes none.
"""

from __future__ import annotations

import argparse
import sys
import textwrap

from core.finlit.corpus import APP_BANDS
from core.finlit.embed import Embedder, gemini_client
from core.finlit.retrieve import MODES, Retriever
from core.finlit.settings import FinlitSettings
from core.finlit import store


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("question")
    ap.add_argument("--lang", default="en", choices=["en", "fi"])
    ap.add_argument("--age", choices=APP_BANDS, help="app age band, e.g. 25-34")
    ap.add_argument("--mode", default="hybrid_prior", choices=MODES)
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--model")
    a = ap.parse_args(argv)
    s = FinlitSettings()
    if s.database_url is None:
        sys.exit("DATABASE_URL is not set (environment or .env)")
    model = a.model or s.finlit_embed_model
    embedder = None
    if a.mode != "lexical":
        if s.gemini_api_key is None:
            sys.exit("GEMINI_API_KEY is not set (environment or .env)")
        embedder = Embedder(gemini_client(s.gemini_api_key.get_secret_value()), model)
    with store.connect(s.database_url.get_secret_value(), statement_timeout_s=30) as conn:
        res = Retriever(conn, embedder, model).search(a.question, a.lang, a.age, k_texts=a.k, k_facts=a.k, mode=a.mode)
    for name, hits in (("TEXTS", res.texts), ("FACTS", res.facts)):
        print(f"== {name}")
        for i, h in enumerate(hits, 1):
            print(f"{i}. [{h.kind}] {h.title}  (score {h.score:.4f}; dense #{h.dense_rank}, lexical #{h.lexical_rank}; "
                  f"priority {h.priority:.2f})")
            print(textwrap.indent(textwrap.shorten(h.text, 300), "     "))
            print(f"     {h.source_url}")
    if embedder:
        print(f"Gemini requests: {embedder.calls} (cache hits {embedder.cache_hits})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
