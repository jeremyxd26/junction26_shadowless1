"""Answers read aloud with a Gemini TTS voice (#730): one request per new text, a disk cache, an own budget.

- The model and the voice come from the Gemini API speech-generation docs (checked 2026-11-14):
  `gemini-3.8-flash-tts` (130 languages, Finnish among them) with the prebuilt voice `Sulafat` ("Warm").
  TTS_MODEL and TTS_VOICE override them as process variables (a model id in .env blocks commits).
- The request goes through the SDK transport the chat already uses (core/agent/gemini_client.py), with
  the same key (GEMINI_API_KEY) passed to the SDK client only: never logged, cached or put in a ledger.
- Cache: one WAV file per text under var/tts-cache, keyed by the SHA-256 of model, voice, language and
  text. A hit sends no request, also while the budget is used up or the model is switched off.
- Budget: TTS_DAILY_BUDGET (default 100) requests in any rolling 24 hours, counted in its own ledger,
  var/tts-requests.jsonl, never in the chat's var/gemini-requests.jsonl. The switch file var/model-off
  stops these requests too, and so does a missing key.
- The API answers WAV, or headerless 16-bit PCM (audio/L16): PCM is wrapped as a WAV file here.
Every refusal raises TtsError with a short code; no text or key is ever in an error or a log line.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import os
import re
import time
import wave
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.agent.gemini import OFF_SWITCH
from core.agent.gemini_client import (
    LEDGER_WINDOW, MIN_SERVER_DEADLINE_S, CallUsage, Ledger, _error_code,
)

ops_log = logging.getLogger("uvicorn.error")

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TTS_MODEL = "gemini-3.8-flash-tts"
DEFAULT_TTS_VOICE = "Sulafat"
DEFAULT_TTS_BUDGET = 100
# Long enough for a cold request to finish and fill the cache after the app gave up at about 8 s.
DEFAULT_TTS_TIMEOUT_S = 25.0
DEFAULT_CACHE_DIR = ROOT / "var" / "tts-cache"
DEFAULT_LEDGER = ROOT / "var" / "tts-requests.jsonl"
MAX_IN_FLIGHT = 2
MAX_TEXT = 2000           # an answer is far shorter; a longer text is refused before any request
PCM_RATE = 24000          # the API's default sample rate for headerless PCM
API_VERSION = "v1beta"    # the speech-generation docs call the TTS models on v1beta


class TtsError(RuntimeError):
    """`code`: no_key, disabled, busy, budget, too_long, timeout, network, server, rate_limited,
    http_<status>, empty, error. `retry_after`: seconds, for budget and busy."""

    def __init__(self, code: str, retry_after: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


class TtsSettings(BaseSettings):
    """GEMINI_API_KEY (the chat's key), TTS_MODEL, TTS_VOICE, TTS_DAILY_BUDGET (0 turns voice requests off),
    TTS_TIMEOUT_S. Read from the environment and the repository's .env, like core/agent/gemini.py."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", env_ignore_empty=True,
                                      extra="ignore")

    gemini_api_key: SecretStr | None = None
    tts_model: str = DEFAULT_TTS_MODEL
    tts_voice: str = DEFAULT_TTS_VOICE
    tts_daily_budget: int = Field(default=DEFAULT_TTS_BUDGET, ge=0)
    tts_timeout_s: float = Field(default=DEFAULT_TTS_TIMEOUT_S, gt=0, le=60)


# (model, text, voice, timeout_s) -> (audio bytes, mime type)
TtsTransport = Callable[[str, str, str, float], tuple[bytes, str]]


class SdkTtsTransport:
    """The real transport: google-genai's generate_content with an AUDIO response, on v1beta. The SDK's
    own retries stay off; the server deadline is never below the API's minimum."""

    def __init__(self, api_key: str) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key, http_options={"api_version": API_VERSION})

    def __call__(self, model: str, text: str, voice: str, timeout_s: float) -> tuple[bytes, str]:
        from google.genai import types

        server_deadline = max(MIN_SERVER_DEADLINE_S, math.ceil(timeout_s))
        config = types.GenerateContentConfig.model_validate({
            "response_modalities": ["AUDIO"],
            "speech_config": {"voice_config": {"prebuilt_voice_config": {"voice_name": voice}}},
            "http_options": {"timeout": int(timeout_s * 1000), "headers": {"X-Server-Timeout": str(server_deadline)}},
        })
        response = self._client.models.generate_content(model=model, contents=text, config=config)
        for candidate in response.candidates or []:
            for part in (candidate.content.parts if candidate.content else None) or []:
                blob = part.inline_data
                if blob is not None and blob.data:
                    return bytes(blob.data), blob.mime_type or ""
        raise TtsError("empty")


def as_wav(data: bytes, mime_type: str) -> bytes:
    """A WAV file: the bytes as they are when they already are one (RIFF), else headerless 16-bit mono
    PCM wrapped at the rate the mime type names (audio/L16;codec=pcm;rate=24000), 24 kHz by default."""
    if data[:4] == b"RIFF":
        return data
    match = re.search(r"rate=(\d+)", mime_type or "")
    rate = int(match.group(1)) if match else PCM_RATE
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data[: len(data) - len(data) % 2])
    return out.getvalue()


def cache_key(model: str, voice: str, language: str, text: str) -> str:
    return hashlib.sha256(json.dumps([model, voice, language, text], ensure_ascii=False).encode("utf-8")).hexdigest()


class TtsService:
    def __init__(self, transport: TtsTransport | None, *, model: str = DEFAULT_TTS_MODEL,
                 voice: str = DEFAULT_TTS_VOICE, ledger: Ledger, cache_dir: Path,
                 timeout_s: float = DEFAULT_TTS_TIMEOUT_S, clock: Callable[[], float] = time.monotonic) -> None:
        self.transport = transport        # None: no key, only cache hits are served
        self.model = model
        self.voice = voice
        self.ledger = ledger
        self.cache_dir = Path(cache_dir)
        self.timeout_s = timeout_s
        self._clock = clock

    def _cache_file(self, language: str, text: str) -> Path:
        return self.cache_dir / f"{cache_key(self.model, self.voice, language, text)}.wav"

    def cached(self, text: str, language: str) -> bytes | None:
        try:
            return self._cache_file(language, text).read_bytes()
        except OSError:
            return None

    def retry_after(self) -> int:
        """Seconds until the oldest request of the rolling 24 hours leaves the window (at least 60)."""
        since = datetime.now(timezone.utc) - LEDGER_WINDOW
        oldest = None
        try:
            with self.ledger.path.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        ts = datetime.fromisoformat(json.loads(line)["ts"])
                    except (ValueError, KeyError, TypeError):
                        continue
                    if ts >= since and (oldest is None or ts < oldest):
                        oldest = ts
        except OSError:
            pass
        if oldest is None:
            return 3600
        return max(60, int((oldest + LEDGER_WINDOW - datetime.now(timezone.utc)).total_seconds()) + 1)

    def speak(self, text: str, language: str) -> tuple[bytes, bool]:
        """(WAV bytes, cached). Raises TtsError when there is no audio to give."""
        text = text.strip()
        if not text:
            raise TtsError("empty")
        if len(text) > MAX_TEXT:
            raise TtsError("too_long")
        hit = self.cached(text, language)
        if hit is not None:
            return hit, True
        if self.transport is None:
            raise TtsError("no_key")
        if self.ledger.daily_cap == 0:
            raise TtsError("disabled")
        refusal = self.ledger.reserve("tts")
        if refusal == "budget":
            raise TtsError("budget", self.retry_after())
        if refusal == "busy":
            raise TtsError("busy", 5)
        if refusal is not None:
            raise TtsError(refusal)
        started = self._clock()
        result = "ok"
        try:
            data, mime = self.transport(self.model, text, self.voice, self.timeout_s)
            wav = as_wav(data, mime)
        except Exception as exc:  # noqa: BLE001 - only a short code leaves this method
            result = exc.code if isinstance(exc, TtsError) else _error_code(exc)[0]
            raise TtsError(result) from None
        finally:
            latency_ms = int((self._clock() - started) * 1000)
            used = self.ledger.add("tts", self.model, result, latency_ms, CallUsage())
            ops_log.info("tts request %s (%s ms), %d of %s in 24 h", result, latency_ms, used, self.ledger.daily_cap)
        try:
            path = self._cache_file(language, text)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_bytes(wav)
            tmp.replace(path)
        except OSError:
            ops_log.warning("tts cache not written")
        return wav, False


def make_tts_service(settings: TtsSettings | None = None, *, ledger_path: Path = DEFAULT_LEDGER,
                     off_switch: Path = OFF_SWITCH, cache_dir: Path = DEFAULT_CACHE_DIR,
                     transport: TtsTransport | None = None) -> TtsService:
    """The service's voice. Without GEMINI_API_KEY there is no transport: cache hits only."""
    s = settings or TtsSettings()
    if transport is None and s.gemini_api_key is not None and s.gemini_api_key.get_secret_value().strip():
        transport = SdkTtsTransport(s.gemini_api_key.get_secret_value().strip())
    ledger = Ledger(ledger_path, s.tts_daily_budget, off_switch, max_in_flight=MAX_IN_FLIGHT)
    return TtsService(transport, model=(s.tts_model or DEFAULT_TTS_MODEL).strip(),
                      voice=(s.tts_voice or DEFAULT_TTS_VOICE).strip(), ledger=ledger, cache_dir=cache_dir,
                      timeout_s=s.tts_timeout_s)
