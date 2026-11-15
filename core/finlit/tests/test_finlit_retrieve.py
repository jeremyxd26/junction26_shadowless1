"""finlit retrieval helpers that need no database: query building, fusion, the priority prior, quotas."""

from core.finlit.retrieve import rrf, top, tsquery_text, with_prior
from core.finlit.store import index_name, vector_literal


def test_tsquery_ors_words_and_prefixes_long_ones():
    assert tsquery_text("How much do people spend on food?") == "how | much:* | do | people:* | spend:* | on | food:*"


def test_tsquery_drops_operators_and_repeats():
    q = tsquery_text("ruoka & !vuokra | (ruoka) <-> 'x'")
    assert q == "ruoka:* | vuokra:*"
    assert not set("&!()<>'") & set(q)


def test_tsquery_keeps_finnish_letters_and_years():
    assert tsquery_text("Kuinka paljon säästöön 2025?") == "kuinka:* | paljon:* | säästöön:* | 2025:*"


def test_tsquery_empty():
    assert tsquery_text("?? !") is None


def test_rrf_rewards_agreement():
    scores = rrf([["a", "b", "c"], ["b", "a"]])
    assert scores["a"] == scores["b"] > scores["c"]
    assert set(scores) == {"a", "b", "c"}


def test_prior_reorders_equal_scores():
    scores = with_prior({"bank": 1.0, "official": 1.0}, {"bank": 0.6, "official": 1.0})
    assert scores["official"] == 1.0 and scores["bank"] == 0.8


def test_top_caps_chunks_per_source_but_not_when_none():
    scores = {"s1-a": 0.9, "s1-b": 0.8, "s1-c": 0.7, "s2-a": 0.6}
    source = {"s1-a": "s1", "s1-b": "s1", "s1-c": "s1", "s2-a": "s2"}
    assert top(scores, source, 3, per_source=2) == ["s1-a", "s1-b", "s2-a"]
    assert top(scores, source, 3, per_source=None) == ["s1-a", "s1-b", "s1-c"]


def test_top_breaks_ties_by_id():
    assert top({"b": 0.5, "a": 0.5}, {"a": "x", "b": "y"}, 2, None) == ["a", "b"]


def test_vector_literal_and_index_name():
    assert vector_literal([0.5, -0.25]) == "[0.5000000,-0.2500000]"
    assert index_name("gemini-embedding-001") == "chunk_embeddings_hnsw_gemini_embedding_001"
