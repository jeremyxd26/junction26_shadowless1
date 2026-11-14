"""The sample bills of the demo gallery (#249): core/bills/samples/samples.json and its images.

The demo reads only these synthetic bills; a visitor's own bill is never sent anywhere. The files are
made by scripts/make_sample_bills.py.

Two views of samples.json:
- `gallery()`: what a client may see, the id, the title in both languages, the bill's language and
  its image with a content hash (for a cache-busting URL);
- `answer_key()`: the true fields of each bill, for tests and for checking a reading (#250). No
  endpoint returns them: a reading result must come from reading the image.
"""

from __future__ import annotations

import functools
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
KEY_FILE = SAMPLES_DIR / "samples.json"


@dataclass(frozen=True)
class SampleImage:
    sample_id: str
    title: dict[str, str]      # {"en": ..., "fi": ...}
    language: str              # the bill's own language
    png: Path
    version: str               # the first 12 hex digits of the image's SHA-256


def _key() -> dict[str, Any]:
    return json.loads(KEY_FILE.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def gallery() -> tuple[SampleImage, ...]:
    """The public view, in gallery order. Read once per process (the files ship with the code)."""
    out = []
    for s in _key()["samples"]:
        png = SAMPLES_DIR / s["files"]["png"]
        out.append(SampleImage(sample_id=s["sample_id"], title=dict(s["title"]), language=s["language"], png=png,
                               version=hashlib.sha256(png.read_bytes()).hexdigest()[:12]))
    return tuple(out)


def image(name: str) -> SampleImage | None:
    """The sample whose image file is `name` (for example "sample_1.png"), or None."""
    return next((s for s in gallery() if s.png.name == name), None)


def answer_key() -> dict[str, Any]:
    """samples.json as written: with the true fields. Tests and reading checks only (#250)."""
    return _key()
