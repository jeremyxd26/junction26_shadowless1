"""The corpus files in core/knowledge/finlit and the invariants every load relies on."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from core.finlit.settings import CORPUS_DIR

# Sentti speaks English and Finnish, like S-Pankki; every chunk is in one of them.
APP_LANGS = ("en", "fi")
# The PostgreSQL text-search configuration for each chunk language.
TS_CONFIG = {"en": "english", "fi": "finnish"}
APP_BANDS = ("0-12", "13-17", "18-24", "25-34", "35-44", "45-54", "55-64", "65-74", "75+")
KINDS = ("source_card", "page_text", "fact")
CYRILLIC = re.compile(r"[Ѐ-ӿ]")


@dataclass(frozen=True)
class Corpus:
    sources: list[dict]
    facts: list[dict]
    chunks: list[dict]
    manifest: dict


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_corpus(directory: Path = CORPUS_DIR) -> Corpus:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    return Corpus(_jsonl(directory / "sources.jsonl"), _jsonl(directory / "facts.jsonl"),
                  _jsonl(directory / "chunks.jsonl"), manifest)


def embed_text(chunk: dict) -> str:
    """What a chunk is embedded as: its title, then its text."""
    return f"{chunk['title']}\n{chunk['text']}"


def content_hash(chunk: dict) -> str:
    return hashlib.sha256(embed_text(chunk).encode("utf-8")).hexdigest()


def corpus_version(corpus: Corpus) -> str:
    """A short hash over every chunk's id and content: changes whenever anything retrievable changes."""
    h = hashlib.sha256()
    for c in sorted(corpus.chunks, key=lambda c: c["id"]):
        h.update(f"{c['id']}\t{content_hash(c)}\n".encode("utf-8"))
    return h.hexdigest()[:16]


def check_corpus(corpus: Corpus) -> list[str]:
    """Problems that would make a load wrong; empty when the corpus is consistent."""
    errs: list[str] = []
    expected = corpus.manifest.get("counts", {})
    for name, rows in (("sources", corpus.sources), ("facts", corpus.facts), ("chunks", corpus.chunks)):
        if not rows:
            errs.append(f"no {name}")
        if name in expected and expected[name] != len(rows):
            errs.append(f"{name}: {len(rows)} rows, manifest says {expected[name]} (truncated or mixed files?)")
    for name, rows in (("source", corpus.sources), ("fact", corpus.facts), ("chunk", corpus.chunks)):
        for r in rows:
            if CYRILLIC.search(json.dumps(r, ensure_ascii=False)):
                errs.append(f"{name} {r['id']}: Cyrillic text (the corpus is English and Finnish only)")
    sids = [s["id"] for s in corpus.sources]
    fids = [f["id"] for f in corpus.facts]
    cids = [c["id"] for c in corpus.chunks]
    for name, ids in (("source", sids), ("fact", fids), ("chunk", cids)):
        if len(ids) != len(set(ids)):
            errs.append(f"duplicate {name} ids")
    sset, fset = set(sids), set(fids)
    for f in corpus.facts:
        if f["source_id"] not in sset:
            errs.append(f"fact {f['id']}: unknown source {f['source_id']}")
    for c in corpus.chunks:
        if c["source_id"] not in sset:
            errs.append(f"chunk {c['id']}: unknown source")
        if c.get("fact_id") and c["fact_id"] not in fset:
            errs.append(f"chunk {c['id']}: unknown fact")
        if c["lang"] not in APP_LANGS:
            errs.append(f"chunk {c['id']}: lang {c['lang']}")
        if c["kind"] not in KINDS:
            errs.append(f"chunk {c['id']}: kind {c['kind']}")
        if c["kind"] == "page_text" and c["licence_class"] != "open_attribution":
            errs.append(f"chunk {c['id']}: page text under {c['licence_class']}")
        if not set(c["age_bands"]) <= set(APP_BANDS) | {"all"}:
            errs.append(f"chunk {c['id']}: age_bands {c['age_bands']}")
        if not c["text"].strip() or not c["source_url"]:
            errs.append(f"chunk {c['id']}: empty text or source_url")
    return errs
