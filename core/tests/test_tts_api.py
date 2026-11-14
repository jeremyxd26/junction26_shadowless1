"""POST /api/tts (#730), without a database, a key or a real request: the voice is a TtsService on a fake
transport, the answers are audit records in a temporary directory. The SDK transport refuses to be built."""

from __future__ import annotations

import io
import json
import wave
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from core.agent import tts
from core.agent.audit import AuditLog
from core.agent.gemini_client import Ledger
from core.app.main import create_app
from core.app.settings import Settings

CUSTOMER = "CUST00860"
OTHER = "CUST00493"
TEXT_EN = "You spent 412.30 EUR on groceries in September."
TEXT_FI = "Käytit syyskuussa ruokaan 412,30 EUR."
PCM = b"\x01\x00\x02\x00" * 240


@pytest.fixture(autouse=True)
def no_real_transport(monkeypatch):
    """No test reaches the Gemini API: building the SDK transport fails the test."""
    def refuse(*args, **kwargs):
        raise AssertionError("tests never build the real TTS transport")
    monkeypatch.setattr(tts, "SdkTtsTransport", refuse)


class FakeTransport:
    def __init__(self, *steps):
        self.steps = list(steps) or [(PCM, "audio/L16;codec=pcm;rate=24000")]
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, model, text, voice, timeout_s):
        self.calls.append((model, text, voice))
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, Exception):
            raise step
        return step


def service(tmp_path, transport, budget=100, off=None):
    ledger = Ledger(tmp_path / "tts-requests.jsonl", budget, off or tmp_path / "model-off", max_in_flight=2)
    return tts.TtsService(transport, ledger=ledger, cache_dir=tmp_path / "tts-cache")


@pytest.fixture()
def app(tmp_path):
    app = create_app(Settings(_env_file=None, database_url=None))
    audit = AuditLog(tmp_path / "audit")
    audit.write({"answer_id": "ans_aaaa1111", "customer_id": CUSTOMER, "language": {"resolved": "en"},
                 "text": "You spent {{n1}} on groceries in September.", "text_rendered": TEXT_EN})
    audit.write({"answer_id": "ans_bbbb2222", "customer_id": CUSTOMER, "language": {"resolved": "fi"},
                 "text": "Käytit syyskuussa ruokaan {{n1}}.", "text_rendered": TEXT_FI})
    audit.write({"answer_id": "ans_cccc3333", "customer_id": OTHER, "language": {"resolved": "en"},
                 "text": "Another customer's answer.", "text_rendered": "Another customer's answer."})
    audit.write({"answer_id": "ans_dddd4444", "customer_id": CUSTOMER, "language": {"resolved": "en"},
                 "text": None, "text_rendered": None})
    app.state.tts_audit = audit
    return app


def post(app, answer_id="ans_aaaa1111", customer=CUSTOMER, **extra):
    with TestClient(app, raise_server_exceptions=False) as c:
        return c.post("/api/tts", json={"customer_id": customer, "answer_id": answer_id, **extra})


def wav_info(data: bytes) -> tuple[int, int, int, int]:
    with wave.open(io.BytesIO(data)) as w:
        return w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()


def test_answer_id_reads_the_rendered_text_and_returns_wav(app, tmp_path):
    transport = FakeTransport()
    app.state.tts_service = service(tmp_path, transport)
    r = post(app)
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert r.content[:4] == b"RIFF"
    assert transport.calls == [(tts.DEFAULT_TTS_MODEL, TEXT_EN, tts.DEFAULT_TTS_VOICE)]   # numbers filled in
    assert "{{" not in transport.calls[0][1]


def test_finnish_answer_is_spoken_in_finnish_text(app, tmp_path):
    transport = FakeTransport()
    app.state.tts_service = service(tmp_path, transport)
    assert post(app, "ans_bbbb2222").status_code == 200
    assert transport.calls[0][1] == TEXT_FI


def test_body_never_takes_a_text(app, tmp_path):
    transport = FakeTransport()
    app.state.tts_service = service(tmp_path, transport)
    r = post(app, text="Say something else")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    assert post(app, answer_id="ans_aaaa1111\"").status_code == 400   # the id is checked before the lookup
    assert transport.calls == []


def test_another_customers_answer_is_not_found(app, tmp_path):
    transport = FakeTransport()
    app.state.tts_service = service(tmp_path, transport)
    other = post(app, "ans_cccc3333")             # CUST00860 asks for CUST00493's answer
    unknown = post(app, "ans_zzzz9999")
    no_text = post(app, "ans_dddd4444")
    for r in (other, unknown, no_text):
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert other.json() == unknown.json()        # one answer for both: nothing tells them apart
    assert transport.calls == []


def test_customer_outside_the_allowlist_is_refused_first(app, tmp_path):
    transport = FakeTransport()
    app.state.tts_service = service(tmp_path, transport)
    r = post(app, customer="CUST00001")
    assert r.status_code == 404 and r.json()["error"]["code"] == "customer_not_found"
    assert transport.calls == []


def test_cache_hit_sends_no_request_also_after_a_restart(app, tmp_path):
    transport = FakeTransport()
    app.state.tts_service = service(tmp_path, transport)
    first = post(app)
    second = post(app)
    assert first.content == second.content and len(transport.calls) == 1
    # a new process (new service on the same directories), with the budget used up and no key: still served
    app.state.tts_service = service(tmp_path, None, budget=0)
    assert post(app).content == first.content
    lines = (tmp_path / "tts-requests.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["kind"] == "tts"


def test_budget_refusal_is_429_with_retry_after(app, tmp_path):
    transport = FakeTransport()
    app.state.tts_service = service(tmp_path, transport, budget=1)
    assert post(app).status_code == 200
    r = post(app, "ans_bbbb2222")
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert 60 <= int(r.headers["Retry-After"]) <= 24 * 3600
    assert len(transport.calls) == 1


def test_own_ledger_not_the_chat_ledger(tmp_path):
    s = tts.make_tts_service(tts.TtsSettings(_env_file=None), ledger_path=tmp_path / "t.jsonl",
                             off_switch=tmp_path / "off", cache_dir=tmp_path / "c")
    assert s.ledger.path.name == "t.jsonl" and s.ledger.daily_cap == tts.DEFAULT_TTS_BUDGET
    assert tts.DEFAULT_LEDGER.name == "tts-requests.jsonl"
    assert s.transport is None                     # no key: no transport, cache hits only


@pytest.mark.parametrize("failure", [TimeoutError("slow"), ConnectionError("down"), RuntimeError("x"),
                                     tts.TtsError("empty")])
def test_api_error_or_timeout_is_503(app, tmp_path, failure):
    app.state.tts_service = service(tmp_path, FakeTransport(failure))
    r = post(app)
    assert r.status_code == 503 and r.json()["error"]["code"] == "model_unavailable"
    entry = json.loads((tmp_path / "tts-requests.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert entry["result"] != "ok"                 # a failed request is counted too


def test_switch_file_and_missing_key_are_503(app, tmp_path):
    transport = FakeTransport()
    (tmp_path / "model-off").write_text("", encoding="utf-8")
    app.state.tts_service = service(tmp_path, transport)
    assert post(app).json()["error"]["code"] == "model_unavailable"
    assert transport.calls == []
    (tmp_path / "model-off").unlink()
    app.state.tts_service = service(tmp_path, None)
    r = post(app, language="fi")
    assert r.status_code == 503 and r.json()["error"]["code"] == "model_unavailable"


def test_pcm_is_wrapped_as_wav_and_wav_passes_through():
    wav = tts.as_wav(PCM, "audio/L16;codec=pcm;rate=24000")
    assert wav[:4] == b"RIFF" and wav_info(wav) == (1, 2, 24000, len(PCM) // 2)
    assert wav_info(tts.as_wav(PCM, "audio/l16"))[2] == tts.PCM_RATE
    assert wav_info(tts.as_wav(PCM, "audio/L16;rate=16000"))[2] == 16000
    assert tts.as_wav(wav, "audio/wav") == wav


def test_cache_key_covers_model_voice_language_and_text():
    base = tts.cache_key("m", "v", "en", "t")
    assert len({base, tts.cache_key("m2", "v", "en", "t"), tts.cache_key("m", "v2", "en", "t"),
                tts.cache_key("m", "v", "fi", "t"), tts.cache_key("m", "v", "en", "t2")}) == 5


def test_retry_after_follows_the_oldest_request(tmp_path):
    s = service(tmp_path, FakeTransport(), budget=1)
    old = datetime.now(timezone.utc) - timedelta(hours=23)
    (tmp_path / "tts-requests.jsonl").write_text(json.dumps({"ts": old.isoformat(timespec="seconds"),
                                                             "kind": "tts"}) + "\n", encoding="utf-8")
    assert 3000 <= s.retry_after() <= 3700
