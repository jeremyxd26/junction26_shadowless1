"""The embedder with a fake Gemini client: batching, one Content per text, normalisation, cache, retries."""

import json
import math
from types import SimpleNamespace

import pytest
from google.genai import errors

from core.finlit.embed import DIMS, DOCUMENT, QUERY, Embedder


class FakeModels:
    def __init__(self, fail_first: int = 0, code: int = 429):
        self.calls = []
        self.fail_first = fail_first
        self.code = code

    def embed_content(self, model, contents, config):
        self.calls.append((model, len(contents), config.task_type, config.output_dimensionality))
        if self.fail_first:
            self.fail_first -= 1
            raise errors.ClientError(self.code, {"error": {"code": self.code, "message": "slow down", "status": "X"}})
        assert all(len(c.parts) == 1 for c in contents)     # one Content per text, never joined
        vecs = [[float(len(c.parts[0].text))] + [1.0] * (DIMS - 1) for c in contents]
        return SimpleNamespace(embeddings=[SimpleNamespace(values=v) for v in vecs])


def make(tmp_path, models, batch=100):
    client = SimpleNamespace(models=models)
    return Embedder(client, "fake-embed", cache_dir=tmp_path / "cache", ledger=tmp_path / "ledger.jsonl",
                    sleep=lambda s: None, batch=batch)


def test_batches_normalises_and_logs(tmp_path):
    models = FakeModels()
    emb = make(tmp_path, models, batch=100)
    vecs = emb.embed([f"text {i}" for i in range(250)], DOCUMENT)
    assert [c[1] for c in models.calls] == [100, 100, 50]
    assert all(c[2] == DOCUMENT and c[3] == DIMS for c in models.calls)
    assert len(vecs) == 250 and all(abs(math.sqrt(sum(x * x for x in v)) - 1) < 1e-6 for v in vecs)
    assert emb.calls == 3
    ledger = [json.loads(x) for x in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert [r["items"] for r in ledger] == [100, 100, 50] and "key" not in json.dumps(ledger).lower()


def test_cache_spares_requests_across_instances_and_separates_tasks(tmp_path):
    models = FakeModels()
    make(tmp_path, models).embed(["a", "bb"], DOCUMENT)
    again = make(tmp_path, models)
    again.embed(["bb", "a"], DOCUMENT)
    assert len(models.calls) == 1 and again.cache_hits == 2
    again.embed(["a"], QUERY)            # same text, other task: a new request
    assert len(models.calls) == 2


def test_retries_rate_limit_then_succeeds(tmp_path):
    models = FakeModels(fail_first=2, code=429)
    emb = make(tmp_path, models)
    assert len(emb.embed(["x"], QUERY)) == 1
    assert emb.calls == 3


def test_other_errors_raise(tmp_path):
    emb = make(tmp_path, FakeModels(fail_first=1, code=400))
    with pytest.raises(errors.ClientError):
        emb.embed(["x"], QUERY)


def test_wrong_vector_count_raises(tmp_path):
    class Joining(FakeModels):
        def embed_content(self, model, contents, config):
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0] * DIMS)])
    with pytest.raises(RuntimeError):
        make(tmp_path, Joining()).embed(["a", "b"], DOCUMENT)
