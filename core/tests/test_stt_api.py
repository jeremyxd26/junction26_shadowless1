"""POST /api/stt (#735), without a database, a key or a real request: the ears are an SttService on a fake
transport, with its ledger in a temporary directory. The SDK transport refuses to be built."""

from __future__ import annotations

import io
import json
import logging
import wave
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from core.agent import stt
from core.agent.gemini_client import CallUsage, Ledger
from core.app.main import create_app
from core.app.settings import Settings

CUSTOMER = "CUST00860"
SPOKEN = "How much did I spend on groceries in September?"
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00opus-frames" * 200   # an opaque clip: only its size and type matter


def wav(seconds: float, rate: int = 16000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return out.getvalue()


@pytest.fixture(autouse=True)
def no_real_transport(monkeypatch):
    """No test reaches the Gemini API: building the SDK transport fails the test."""
    def refuse(*args, **kwargs):
        raise AssertionError("tests never build the real STT transport")
    monkeypatch.setattr(stt, "SdkSttTransport", refuse)


class FakeTransport:
    def __init__(self, *steps, prompt_tokens=120):
        self.steps = list(steps) or [SPOKEN]
        self.prompt_tokens = prompt_tokens
        self.calls: list[tuple[str, int, str, str]] = []

    def __call__(self, model, audio, mime_type, prompt, timeout_s):
        self.calls.append((model, len(audio), mime_type, prompt))
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, Exception):
            raise step
        return step, CallUsage(prompt_tokens=self.prompt_tokens, output_tokens=12)


def service(tmp_path, transport, budget=100, off=None):
    ledger = Ledger(tmp_path / "stt-requests.jsonl", budget, off or tmp_path / "model-off", max_in_flight=2)
    return stt.SttService(transport, ledger=ledger)


@pytest.fixture()
def app():
    return create_app(Settings(_env_file=None, database_url=None))


def post(app, body=WEBM, content_type="audio/webm;codecs=opus", customer=CUSTOMER, language="en", headers=None):
    with TestClient(app, raise_server_exceptions=False) as c:
        return c.post("/api/stt", params={"customer_id": customer, "language": language}, content=body,
                      headers={"Content-Type": content_type, **(headers or {})})


def test_clip_comes_back_as_text(app, tmp_path):
    transport = FakeTransport()
    app.state.stt_service = service(tmp_path, transport)
    r = post(app)
    assert r.status_code == 200
    assert r.json() == {"text": SPOKEN, "language": "en"}
    model, size, mime, prompt = transport.calls[0]
    assert (model, size, mime) == (stt.DEFAULT_STT_MODEL, len(WEBM), "audio/webm")   # codecs dropped
    assert "Transcribe" in prompt and "English" in prompt


@pytest.mark.parametrize(("content_type", "sent"), [("audio/mp4", "audio/m4a"), ("audio/ogg;codecs=opus", "audio/ogg"),
                                                    ("video/webm", "audio/webm")])
def test_browser_types_map_to_the_documented_ones(app, tmp_path, content_type, sent):
    transport = FakeTransport()
    app.state.stt_service = service(tmp_path, transport)
    assert post(app, content_type=content_type).status_code == 200
    assert transport.calls[0][2] == sent


def test_compressed_clip_over_about_17_seconds_by_its_tokens_is_413_and_counted(app, tmp_path):
    # 20 s of audio at the documented 32 tokens a second, plus the prompt: refused, its text never returned
    transport = FakeTransport(prompt_tokens=32 * 20 + 140)
    app.state.stt_service = service(tmp_path, transport)
    r = post(app)
    assert r.status_code == 413 and r.json()["error"]["code"] == "invalid_request"
    assert SPOKEN not in r.text
    entry = json.loads((tmp_path / "stt-requests.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert entry["result"] == "too_long"
    # a real 15 s clip (about 620 tokens in all with the prompt since #858) passes
    app.state.stt_service = service(tmp_path, FakeTransport(prompt_tokens=32 * 15 + 140))
    assert post(app).status_code == 200


def test_finnish_prompt_names_finnish(app, tmp_path):
    transport = FakeTransport("Paljonko käytin ruokaan syyskuussa?")
    app.state.stt_service = service(tmp_path, transport)
    r = post(app, language="fi")
    assert r.json() == {"text": "Paljonko käytin ruokaan syyskuussa?", "language": "fi"}
    assert "Finnish" in transport.calls[0][3]


def test_the_app_language_never_forces_the_spoken_one(app, tmp_path):
    """Finnish speech with the app in English (and English with it in Finnish) is written as spoken (#858)."""
    transport = FakeTransport("Mihin rahani menivät?")
    app.state.stt_service = service(tmp_path, transport)
    assert post(app, language="en").json()["text"] == "Mihin rahani menivät?"
    app.state.stt_service = service(tmp_path, FakeTransport("Where did my money go?"))
    english = app.state.stt_service.transport
    assert post(app, language="fi").json()["text"] == "Where did my money go?"
    for prompt in (transport.calls[0][3], english.calls[0][3]):
        assert "Finnish or English" in prompt and "either is possible" in prompt
        assert "never translate" in prompt and "decide from the audio alone" in prompt
        assert "most likely" not in prompt
    assert "screen happens to be in English" in transport.calls[0][3]
    assert "screen happens to be in Finnish" in english.calls[0][3]


def test_too_large_is_413_before_any_request(app, tmp_path):
    transport = FakeTransport()
    app.state.stt_service = service(tmp_path, transport)
    big = b"\x00" * (stt.MAX_BYTES + 1)
    r = post(app, body=big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "invalid_request"
    # a chunked body (no Content-Length) is cut by the running cap
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/api/stt", params={"customer_id": CUSTOMER}, headers={"Content-Type": "audio/webm"},
                   content=iter([b"\x00" * 600_000, b"\x00" * 600_000]))
    assert r.status_code == 413
    assert transport.calls == []
    assert not (tmp_path / "stt-requests.jsonl").exists()


def test_service_refuses_too_large_also_without_the_route(tmp_path):
    with pytest.raises(stt.SttError) as err:
        service(tmp_path, FakeTransport()).transcribe(b"\x00" * (stt.MAX_BYTES + 1), "audio/webm", "en")
    assert err.value.code == "too_large"


def test_wav_over_15_seconds_is_413_and_a_short_one_passes(app, tmp_path):
    transport = FakeTransport()
    app.state.stt_service = service(tmp_path, transport)
    long_clip = wav(20, rate=8000)
    assert len(long_clip) < stt.MAX_BYTES            # small enough: refused for its length
    r = post(app, body=long_clip, content_type="audio/wav")
    assert r.status_code == 413 and r.json()["error"]["code"] == "invalid_request"
    assert transport.calls == []
    assert post(app, body=wav(3), content_type="audio/wav").status_code == 200
    assert stt.wav_seconds(wav(3)) == pytest.approx(3.0)


@pytest.mark.parametrize(("body", "content_type"), [(WEBM, "text/plain"), (WEBM, "application/json"), (b"", "audio/webm"),
                                                    (b"RIFFnot-a-wav", "audio/wav")])
def test_unknown_type_empty_or_broken_clip_is_400(app, tmp_path, body, content_type):
    transport = FakeTransport()
    app.state.stt_service = service(tmp_path, transport)
    r = post(app, body=body, content_type=content_type)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    assert transport.calls == []


def test_customer_outside_the_allowlist_is_refused_first(app, tmp_path):
    transport = FakeTransport()
    app.state.stt_service = service(tmp_path, transport)
    r = post(app, customer="CUST00001")
    assert r.status_code == 404 and r.json()["error"]["code"] == "customer_not_found"
    bad = post(app, customer="CUST1")
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_request"
    assert post(app, language="sv").status_code == 400
    assert transport.calls == []


def test_budget_refusal_is_429_with_retry_after(app, tmp_path):
    transport = FakeTransport()
    app.state.stt_service = service(tmp_path, transport, budget=1)
    assert post(app).status_code == 200
    r = post(app)
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert 60 <= int(r.headers["Retry-After"]) <= 24 * 3600
    assert len(transport.calls) == 1


def test_per_address_window_is_429(app, tmp_path):
    transport = FakeTransport()
    app.state.stt_service = service(tmp_path, transport)
    codes = [post(app).status_code for _ in range(12)]
    assert codes[:10] == [200] * 10 and codes[10:] == [429, 429]


def test_own_ledger_not_the_chat_ledger(tmp_path):
    s = stt.make_stt_service(stt.SttSettings(_env_file=None), ledger_path=tmp_path / "s.jsonl",
                             off_switch=tmp_path / "off")
    assert s.ledger.path.name == "s.jsonl" and s.ledger.daily_cap == stt.DEFAULT_STT_BUDGET
    assert stt.DEFAULT_LEDGER.name == "stt-requests.jsonl"
    assert s.transport is None                     # no key: no transport


@pytest.mark.parametrize("failure", [TimeoutError("slow"), ConnectionError("down"), RuntimeError("x")])
def test_api_error_or_timeout_is_503(app, tmp_path, failure):
    app.state.stt_service = service(tmp_path, FakeTransport(failure))
    r = post(app)
    assert r.status_code == 503 and r.json()["error"]["code"] == "model_unavailable"
    entry = json.loads((tmp_path / "stt-requests.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert entry["kind"] == "stt" and entry["result"] != "ok"     # a failed request is counted too


@pytest.mark.parametrize("heard", ["", "   ", "[silence]", "No speech detected.", "(inaudible)",
                                   "There is no speech in this audio.", "Ei puhetta."])
def test_no_speech_is_200_with_an_empty_text(app, tmp_path, heard):
    """#759: no speech is not a failure: the app asks the user to try again, and nothing goes in the box."""
    app.state.stt_service = service(tmp_path, FakeTransport(heard))
    r = post(app, language="fi")
    assert r.status_code == 200 and r.json() == {"text": "", "language": "fi", "empty": True}


@pytest.mark.parametrize("spoken", ["Is silence on my statement a problem?", "No speech today, just groceries?",
                                    "Empty fridge, how much did I spend?"])
def test_a_question_that_mentions_silence_is_kept(app, tmp_path, spoken):
    app.state.stt_service = service(tmp_path, FakeTransport(spoken))
    r = post(app)
    assert r.status_code == 200 and r.json() == {"text": spoken, "language": "en"}


def test_switch_file_budget_zero_and_missing_key_are_503(app, tmp_path):
    transport = FakeTransport()
    (tmp_path / "model-off").write_text("", encoding="utf-8")
    app.state.stt_service = service(tmp_path, transport)
    assert post(app).json()["error"]["code"] == "model_unavailable"
    (tmp_path / "model-off").unlink()
    app.state.stt_service = service(tmp_path, transport, budget=0)
    assert post(app).status_code == 503
    app.state.stt_service = service(tmp_path, None)
    r = post(app, language="fi")
    assert r.status_code == 503 and r.json()["error"]["code"] == "model_unavailable"
    assert transport.calls == []


def test_nothing_but_the_ledger_is_written_and_no_text_or_audio_is_logged(app, tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    marker = b"AUDIO-MARKER-735"
    transport = FakeTransport()
    app.state.stt_service = service(tmp_path / "var", transport)
    caplog.set_level(logging.DEBUG)
    r = post(app, body=WEBM + marker)
    assert r.status_code == 200 and r.json()["text"] == SPOKEN
    files = [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()]
    assert files == ["var/stt-requests.jsonl"]
    ledger = (tmp_path / "var" / "stt-requests.jsonl").read_text(encoding="utf-8")
    entry = json.loads(ledger)
    assert set(entry) == {"ts", "kind", "model", "result", "latency_ms", "tokens"}
    for blob in (ledger, caplog.text):
        assert SPOKEN not in blob and "groceries" not in blob
        assert "AUDIO-MARKER" not in blob and "QVVESU8tTUFSS0VS" not in blob   # nor its base64


def test_transcript_is_one_line_within_the_composer_limit():
    assert stt.clean_transcript('  "How much\n did I spend?"  ') == "How much did I spend?"
    long = "word " * 200
    cut = stt.clean_transcript(long)
    assert len(cut) <= stt.MAX_TEXT and not cut.endswith(" ")


def test_retry_after_follows_the_oldest_request(tmp_path):
    s = service(tmp_path, FakeTransport(), budget=1)
    old = datetime.now(timezone.utc) - timedelta(hours=23)
    (tmp_path / "stt-requests.jsonl").write_text(json.dumps({"ts": old.isoformat(timespec="seconds"),
                                                             "kind": "stt"}) + "\n", encoding="utf-8")
    assert 3000 <= s.retry_after() <= 3700
