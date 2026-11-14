"""The deploy step that reads the sample bills (#250): each sample twice, the second from the cache, scored
against the answer key, counts only, and never a failure. No key, no database, no real request: the client
is a GeminiClient on a fake transport that answers each image with fields from the answer key."""

from __future__ import annotations

import hashlib
import json

from core.agent.gemini_client import GeminiClient, Ledger
from core.bills import gallery, warmup

MODEL = "gemini-3.5-flash-lite"
TRUTH = {s["sample_id"]: s["truth"] for s in gallery.answer_key()["samples"]}
BY_HASH = {hashlib.sha256(s.png.read_bytes()).hexdigest(): s.sample_id for s in gallery.gallery()}


def _answer(fields: dict) -> dict:
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(fields)}]},
                            "finish_reason": "STOP"}],
            "usage_metadata": {"prompt_token_count": 1200, "candidates_token_count": 60}}


class ByImage:
    """Answers each sample image with its answer-key fields (one field changed for `wrong`)."""

    def __init__(self, wrong: str | None = None):
        self.wrong, self.requests = wrong, 0

    def __call__(self, model, contents, config, timeout_s):
        self.requests += 1
        data = next(p["inline_data"]["data"] for c in contents for p in c["parts"] if "inline_data" in p)
        sample_id = BY_HASH[hashlib.sha256(data).hexdigest()]
        t = TRUTH[sample_id]
        fields = {k: t[k] for k in warmup.FIELDS if t.get(k)}
        if sample_id == self.wrong:
            fields["payee"] = "Somebody Else Oy"
        return _answer(fields)


def client(tmp_path, transport):
    ledger = Ledger(tmp_path / "ledger.jsonl", daily_cap=100, kind_caps={"extract": 50})
    return GeminiClient(MODEL, transport, cache="on", cache_dir=tmp_path / "cache", ledger=ledger,
                        sleep=lambda s: None)


def test_each_sample_is_read_once_with_the_model_and_once_from_the_cache(tmp_path):
    transport, lines = ByImage(), []
    assert warmup.run(client(tmp_path, transport), lines.append) == (24, 24)
    assert transport.requests == 4
    assert len(lines) == 5 and lines[-1] == "bill readings: 24/24 fields match the answer key"
    for line in lines[:4]:
        assert "6/6 fields match the answer key" in line and "first reading 1 request(s)" in line
        assert line.endswith("second reading 0 request(s) (cache)")
    # A second deploy on the same cache sends nothing.
    again = ByImage()
    warmup.run(client(tmp_path, again), lines.append)
    assert again.requests == 0 and "first reading 0 request(s)" in lines[5]


def test_a_misread_field_is_counted_and_no_value_is_printed(tmp_path):
    lines = []
    assert warmup.run(client(tmp_path, ByImage(wrong="sample_2")), lines.append) == (23, 24)
    assert "bill reading sample_2: 5/6 fields match" in lines[1]
    text = "\n".join(lines)
    assert "Somebody" not in text and "Esimerkki" not in text and TRUTH["sample_1"]["iban"] not in text


def test_the_model_unavailable_is_one_line_per_sample_and_no_failure(tmp_path):
    """The readings' share of the daily budget used up: nothing is sent, the deploy goes on."""
    transport, lines = ByImage(), []
    ledger = Ledger(tmp_path / "ledger.jsonl", daily_cap=100, kind_caps={"extract": 0})
    capped = GeminiClient(MODEL, transport, cache="on", cache_dir=tmp_path / "cache", ledger=ledger,
                          sleep=lambda s: None)
    assert warmup.run(capped, lines.append) == (0, 0) and transport.requests == 0
    assert len(lines) == 4 and all("first reading: model unavailable (budget)" in line for line in lines)


def test_without_a_key_the_step_is_skipped(monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(warmup, "reading_client", lambda: None)
    assert warmup.main() == 0 and "skipped: no model key" in capsys.readouterr().out


def test_the_sample_without_a_barcode_scores_its_empty_barcode_as_correct():
    t = TRUTH["sample_4"]
    fields = {k: {"value": t[k], "status": "unchecked"} for k in ("payee", "iban", "reference", "amount", "due_date")}
    assert not t.get("barcode") and warmup.score(fields, t) == (6, 6, 0)



# ---- #511: the step's own failures and an unwritable cache ---------------------------------------------------

def test_a_missing_gallery_file_returns_zero_and_says_so(tmp_path, monkeypatch):
    def missing():
        raise FileNotFoundError("samples.json")

    monkeypatch.setattr(gallery, "answer_key", missing)
    lines = []
    assert warmup.run(client(tmp_path, ByImage()), lines.append) == (0, 0)
    assert lines == ["bill readings skipped: the sample gallery could not be read (FileNotFoundError)"]


def test_a_missing_sample_file_skips_that_sample_only(tmp_path, monkeypatch):
    first = gallery.gallery()[0]
    gone = [type(first)(first.sample_id, first.title, first.language, tmp_path / "gone.png", first.version),
            *gallery.gallery()[1:]]
    monkeypatch.setattr(gallery, "gallery", lambda: tuple(gone))
    lines = []
    assert warmup.run(client(tmp_path, ByImage()), lines.append) == (18, 18)
    assert lines[0] == f"bill reading {first.sample_id}: its image could not be read (FileNotFoundError)"


def test_a_raising_client_is_one_line_per_sample_and_main_returns_zero(tmp_path, monkeypatch, capsys):
    class Broken:
        ledger = None

        def extract(self, *args, **kwargs):
            raise RuntimeError("boom")

    lines = []
    assert warmup.run(Broken(), lines.append) == (0, 0)
    assert len(lines) == 4 and all("first reading failed (RuntimeError)" in line for line in lines)
    monkeypatch.setattr(warmup, "reading_client", lambda: Broken())
    assert warmup.main() == 0 and "bill reading" in capsys.readouterr().out

    def no_setup():
        raise ImportError("no SDK")

    monkeypatch.setattr(warmup, "reading_client", no_setup)
    assert warmup.main() == 0 and "could not be set up (ImportError)" in capsys.readouterr().out


def test_an_unwritable_cache_folder_costs_at_most_one_request_per_sample(tmp_path, monkeypatch):
    from core.agent import gemini_client

    monkeypatch.setattr(gemini_client.GeminiClient, "_write_cache", lambda self, *args, **kwargs: None)
    transport, lines = ByImage(), []
    warmup.run(client(tmp_path, transport), lines.append)
    assert transport.requests == 4                                # one per sample, never two
    assert all("second reading: not in the cache" in line for line in lines[:4])
