"""Guards from the review, checked without a database or network: the shared schema is never pruned by a
broken corpus, connection errors never echo DATABASE_URL, bad input is refused, metrics count right."""

import json
from types import SimpleNamespace

import psycopg
import pytest

from core.finlit import store
from core.finlit.corpus import Corpus, check_corpus, load_corpus
from core.finlit.embed import DIMS, Embedder
from core.finlit.evaluate import EVAL_SET, chunk_hit, first_hit, summarise
from core.finlit.retrieve import Hit, Result, Retriever, top, tsquery_text


class FakeConn:
    """Answers the prune pre-check with (rows in the table, rows the sync would delete)."""

    def __init__(self, existing: int, gone: int):
        self.answer = (existing, gone)
        self.sql: list[str] = []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        return SimpleNamespace(fetchone=lambda: self.answer)


def tiny_corpus(chunks=True) -> Corpus:
    src = {"id": "s1"}
    return Corpus([src], [{"id": "f1"}], [{"id": "c1"}] if chunks else [], {"counts": {}})


def test_sync_refuses_an_empty_list_before_touching_the_database():
    conn = FakeConn(10, 0)
    with pytest.raises(ValueError, match="no chunks"):
        store.sync_corpus(conn, tiny_corpus(chunks=False))
    assert conn.sql == []


def test_sync_refuses_to_delete_more_than_a_quarter_without_prune():
    with pytest.raises(ValueError, match="--prune"):
        store.sync_corpus(FakeConn(existing=100, gone=26), tiny_corpus())


def test_connection_errors_do_not_echo_the_url(monkeypatch):
    # A sentinel stands in for the URL (a real-looking one would trip the repository's secret scan).
    marker = "SENTINEL-CONNINFO-7f3a"

    def boom(conninfo, *a, **k):
        raise psycopg.OperationalError(f"connection failed for {conninfo}")
    monkeypatch.setattr(psycopg, "connect", boom)
    with pytest.raises(store.DatabaseUnavailable) as info:
        store.connect(marker)
    text = str(info.value) + repr(info.value.__cause__)
    assert marker not in text and info.value.__suppress_context__


def test_manifest_counts_and_cyrillic_are_checked():
    corpus = load_corpus()
    short = Corpus(corpus.sources, corpus.facts, corpus.chunks[:-1], corpus.manifest)
    assert any("manifest says" in e for e in check_corpus(short))
    russian = dict(corpus.sources[0], note="Привет")
    assert any("Cyrillic" in e for e in check_corpus(Corpus([russian] + corpus.sources[1:], corpus.facts,
                                                            corpus.chunks, corpus.manifest)))


def test_a_broken_cache_line_is_skipped(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    good = {"k": "a", "v": [0.0] * DIMS}
    (cache / f"m-{DIMS}.jsonl").write_text(json.dumps(good) + "\n" + '{"k": "b", "v": [0.1, 0.2')
    emb = Embedder(SimpleNamespace(models=None), "m", cache_dir=cache, ledger=None)
    assert "a" in emb.cache and emb.skipped_cache_lines == 1


def test_bad_language_or_band_is_refused():
    r = Retriever(FakeConn(0, 0), None, "m")
    with pytest.raises(ValueError):
        r.search("q", "sv", None, query_vec=[0.0] * DIMS)
    with pytest.raises(ValueError):
        r.search("q", "fi", "30-40", query_vec=[0.0] * DIMS)


def test_top_with_k_zero_and_nfd_input():
    assert top({"a": 1.0}, {"a": "s"}, 0, None) == []
    nfd = "säästöön"            # "säästöön" in decomposed form
    assert tsquery_text(nfd) == "säästöön:*"


def hit(chunk_id, source_id, fact_id=None):
    return Hit(chunk_id, source_id, "fact" if fact_id else "page_text", "", "", "", "", fact_id, 1.0, 0.0, None, None)


def test_scoring_uses_the_one_answering_fact_and_the_exact_chunk():
    fact_item = {"target_kind": "fact", "gold_fact_ids": ["f2"], "gold_source_ids": ["s"]}
    res = Result(texts=[], facts=[hit("f1:en", "s", "f1"), hit("f2:en", "s", "f2")])
    assert first_hit(fact_item, res) == 2
    text_item = {"target_kind": "page_text", "gold_source_ids": ["s"], "gold_fact_ids": [], "target_chunk_id": "c2"}
    res = Result(texts=[hit("c1", "s"), hit("c2", "s")], facts=[])
    assert first_hit(text_item, res) == 1 and chunk_hit(text_item, res) == 2
    assert summarise([1, 3, None, 2]) == {"n": 4, "recall@1": 0.25, "recall@3": 0.75, "recall@5": 0.75,
                                          "mrr@10": round((1 + 1 / 3 + 1 / 2) / 4, 3)}


def test_fact_items_have_one_gold_fact_for_their_age_group():
    facts = {f["id"]: f for f in load_corpus().facts}
    for line in EVAL_SET.read_text(encoding="utf-8").splitlines():
        it = json.loads(line)
        if it["target_kind"] != "fact":
            continue
        assert len(it["gold_fact_ids"]) == 1 and it["target_chunk_id"] == it["gold_fact_ids"][0]
        bands = facts[it["gold_fact_ids"][0]]["age_bands"]
        assert "all" in bands if it["age_band"] is None else (it["age_band"] in bands or "all" in bands)
