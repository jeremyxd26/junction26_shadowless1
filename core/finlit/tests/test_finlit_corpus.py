"""The committed corpus (core/knowledge/finlit) and eval set are consistent: what the loader relies on."""

import json
from pathlib import Path

from core.finlit.corpus import APP_BANDS, check_corpus, content_hash, corpus_version, load_corpus

EVAL_SET = Path(__file__).resolve().parents[1] / "eval_set.jsonl"


def test_corpus_is_consistent():
    corpus = load_corpus()
    assert check_corpus(corpus) == []
    assert len(corpus.chunks) > 1000 and len(corpus.facts) > 400 and len(corpus.sources) > 200


def test_page_text_only_from_open_sources():
    corpus = load_corpus()
    open_ids = {s["id"] for s in corpus.sources if s["licence_class"] == "open_attribution"}
    stored = {c["source_id"] for c in corpus.chunks if c["kind"] == "page_text"}
    assert stored and stored <= open_ids


def test_every_fact_has_a_query_and_both_languages():
    for f in load_corpus().facts:
        # (no module of core/ may name the statistics API host: test_tools_national_pure)
        assert f["query"]["query"] and f["api_url"].startswith("https://") and f["table"] in f["api_url"]
        assert f["text_en"] and f["text_fi"] and isinstance(f["value"], (int, float))


def test_hash_and_version_are_stable():
    corpus = load_corpus()
    c = corpus.chunks[0]
    assert content_hash(c) == content_hash(dict(c))
    assert corpus_version(corpus) == corpus_version(load_corpus())


def test_eval_set_points_at_the_corpus():
    corpus = load_corpus()
    sids = {s["id"] for s in corpus.sources}
    fids = {f["id"] for f in corpus.facts}
    items = [json.loads(x) for x in EVAL_SET.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(items) >= 40
    for it in items:
        assert it["lang"] in ("en", "fi") and it["question"].strip()
        assert it["age_band"] is None or it["age_band"] in APP_BANDS
        assert set(it["gold_source_ids"]) <= sids
        assert set(it["gold_fact_ids"]) <= fids
        assert it["gold_fact_ids"] if it["target_kind"] == "fact" else it["gold_source_ids"]
