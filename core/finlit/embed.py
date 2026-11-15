"""Gemini embeddings for the finlit corpus: batched, cached on disk, every API call recorded.

- One request embeds up to BATCH texts. Each text goes in as its own Content: gemini-embedding-2 joins plain
  strings in one request into a single embedding, gemini-embedding-001 accepts either form.
- Vectors are 768-dimensional and L2-normalised (the API returns unnormalised vectors below 3072 dimensions).
- The cache (var/finlit-embeddings/<model>.jsonl) is keyed by model, task type and text, so a re-run, an
  unchanged corpus or a repeated eval question costs no request. It holds vectors only, never the key.
- var/finlit-requests.jsonl gets one line per request (time, model, task, items), so the quota spent is visible.
- 429 and 5xx answers are retried with backoff; anything else raises.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from core.finlit.settings import VAR_DIR

DIMS = 768
BATCH = 100
DOCUMENT = "RETRIEVAL_DOCUMENT"
QUERY = "RETRIEVAL_QUERY"
RETRY_CODES = {429, 500, 502, 503, 504}


def normalise(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec))
    return [x / n for x in vec] if n else list(vec)


class Embedder:
    def __init__(self, client, model: str, cache_dir: Path | None = VAR_DIR / "finlit-embeddings",
                 ledger: Path | None = VAR_DIR / "finlit-requests.jsonl", sleep: Callable[[float], None] = time.sleep,
                 max_retries: int = 6, batch: int = BATCH) -> None:
        self.client = client
        self.model = model
        self.sleep = sleep
        self.max_retries = max_retries
        self.batch = batch
        self.calls = 0            # API requests made by this embedder
        self.cache_hits = 0
        self.skipped_cache_lines = 0
        self.ledger = ledger
        self.cache_path = (cache_dir / f"{model.replace('/', '_')}-{DIMS}.jsonl") if cache_dir else None
        self.cache: dict[str, list[float]] = {}
        if self.cache_path and self.cache_path.exists():
            for line in self.cache_path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    if len(row["v"]) == DIMS:
                        self.cache[row["k"]] = row["v"]
                except (ValueError, KeyError, TypeError):
                    self.skipped_cache_lines += 1   # e.g. a line cut short by an interrupted run

    def _key(self, text: str, task: str) -> str:
        return hashlib.sha256(f"{self.model}|{DIMS}|{task}|{text}".encode("utf-8")).hexdigest()

    def embed(self, texts: list[str], task: str) -> list[list[float]]:
        keys = [self._key(t, task) for t in texts]
        missing = [i for i, k in enumerate(keys) if k not in self.cache]
        self.cache_hits += len(texts) - len(missing)
        for start in range(0, len(missing), self.batch):
            idx = missing[start:start + self.batch]
            vecs = self._request([texts[i] for i in idx], task)
            fresh = {}
            for i, v in zip(idx, vecs):
                fresh[keys[i]] = [round(x, 7) for x in normalise(v)]
            self.cache.update(fresh)
            self._persist(fresh)
        return [self.cache[k] for k in keys]

    def _request(self, texts: list[str], task: str) -> list[list[float]]:
        from google.genai import errors, types

        contents = [types.Content(role="user", parts=[types.Part(text=t)]) for t in texts]
        config = types.EmbedContentConfig(task_type=task, output_dimensionality=DIMS)
        for attempt in range(self.max_retries + 1):
            try:
                self.calls += 1
                self._log(task, len(texts))
                resp = self.client.models.embed_content(model=self.model, contents=contents, config=config)
                break
            except errors.APIError as exc:
                if getattr(exc, "code", None) not in RETRY_CODES or attempt == self.max_retries:
                    raise
                self.sleep(min(60.0, 5.0 * 2 ** attempt))
        vecs = [list(e.values) for e in (resp.embeddings or [])]
        if len(vecs) != len(texts) or any(len(v) != DIMS for v in vecs):
            raise RuntimeError(f"{self.model} returned {len(vecs)} vectors for {len(texts)} texts")
        return vecs

    def _persist(self, rows: dict[str, list[float]]) -> None:
        if not self.cache_path or not rows:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_path.open("a", encoding="utf-8") as fh:
            for k, v in rows.items():
                fh.write(json.dumps({"k": k, "v": v}) + "\n")

    def _log(self, task: str, items: int) -> None:
        if not self.ledger:
            return
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": self.model,
                                 "task": task, "items": items}) + "\n")


def gemini_client(api_key: str):
    """A google-genai client; the key goes to the SDK and nowhere else."""
    from google import genai

    return genai.Client(api_key=api_key)
