"""A spoken question turned into text with Gemini audio understanding (#735): one request per clip, an own budget.

- The model comes from the Gemini API audio-understanding docs (checked 2026-11-14): `gemini-3.8-flash`, the
  chat's flash model, takes audio inline (WAV, WebM, OGG, M4A, AAC, MP3 and more) next to a text prompt.
  STT_MODEL overrides it as a process variable (a model id in .env blocks commits).
- The request goes through the SDK the chat already uses, with the same key (GEMINI_API_KEY) passed to the
  SDK client only: never logged or put in a ledger. Thinking is "low": Gemini 3 models think by default.
- Nothing is stored: no cache, no file, no audit record. The audio stays in memory for the one request and
  the transcript goes back to the caller only. The ledger line holds the time, kind, model, result, latency
  and token counts, never the audio or the text; the log line holds the result, the size and the latency.
- Budget: STT_DAILY_BUDGET (default 100) requests in any rolling 24 hours, counted in its own ledger,
  var/stt-requests.jsonl, apart from the chat's var/gemini-requests.jsonl. The switch file var/model-off
  stops these requests too, and so does a missing key.
- Limits before any request: at most MAX_BYTES of audio, a known audio type, and for WAV (whose header
  names its length) at most MAX_SECONDS. A compressed clip (WebM, MP4, OGG) carries no reliable length
  while it is recorded (the app stops recording at 15 s), so its length is checked from the answer: the API
  counts audio at a fixed 32 tokens a second (audio docs, checked 2026-11-14), and a request whose prompt
  took more than MAX_PROMPT_TOKENS is refused as too long, its text dropped. It is counted in the ledger.
Every refusal raises SttError with a short code; no audio, text or key is ever in an error or a log line.
"""

from __future__ import annotations

import io
import json
import logging
import math
import re
import time
import wave
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.agent.gemini import OFF_SWITCH, ROOT
from core.agent.gemini_client import LEDGER_WINDOW, MIN_SERVER_DEADLINE_S, CallUsage, Ledger, _error_code

ops_log = logging.getLogger("uvicorn.error")

DEFAULT_STT_MODEL = "gemini-3.8-flash"
DEFAULT_STT_BUDGET = 100
DEFAULT_STT_TIMEOUT_S = 15.0
DEFAULT_LEDGER = ROOT / "var" / "stt-requests.jsonl"
MAX_IN_FLIGHT = 2
MAX_BYTES = 1_000_000      # about 1 MB: 15 s of browser audio is far smaller
MAX_SECONDS = 15.5         # the app stops at 15 s; a little room for the recorder's last chunk
AUDIO_TOKENS_PER_SECOND = 32
# 17 s of audio plus the prompt (about 35 tokens measured before #858, about 140 since): a 15 s clip is about
# 620 tokens in all
MAX_PROMPT_TOKENS = AUDIO_TOKENS_PER_SECOND * 17 + 180
MAX_TEXT = 500             # the composer's limit (MAX_QUESTION in the app)
API_VERSION = "v1beta"

# The type the browser names (parameters stripped) -> the type Gemini's docs list. Safari's MediaRecorder
# gives audio/mp4 (AAC in an MP4 file), which the docs call M4A.
MIME_TYPES = {
    "audio/webm": "audio/webm",
    "video/webm": "audio/webm",     # some Chrome versions name an audio-only recording video/webm
    "audio/ogg": "audio/ogg",
    "audio/mp4": "audio/m4a",
    "audio/x-m4a": "audio/m4a",
    "audio/m4a": "audio/m4a",
    "audio/aac": "audio/aac",
    "audio/mpeg": "audio/mpeg",
    "audio/mp3": "audio/mp3",
    "audio/wav": "audio/wav",
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
}

LANGUAGE_NAMES = {"en": "English", "fi": "Finnish"}

# The spoken language is never forced (Renat, 15.11): the speaker may use Finnish or English whatever the app's
# language is, so the app's language is only a weak hint, and the words come back in the language spoken.
PROMPT = (
    "Transcribe the speech in this audio clip word for word. The speaker is asking a personal finance app a "
    "question and may speak Finnish or English; either is possible. The app's screen happens to be in {language}, "
    "which says little about the spoken language: decide from the audio alone. Write the words in the language "
    "actually spoken, exactly as said: never translate, never switch to the other language, never guess English "
    "words for Finnish speech. Return only the spoken words as plain text: no quotes, no labels, no timestamps, no "
    "commentary, and do not answer the question. Write numbers and amounts as digits. If there is no speech, "
    "return an empty response."
)


class SttError(RuntimeError):
    """`code`: no_key, disabled, busy, budget, too_large, too_long, unsupported, empty, no_speech, timeout,
    network, server, rate_limited, http_<status>, error. `retry_after`: seconds, for budget and busy."""

    def __init__(self, code: str, retry_after: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


class SttSettings(BaseSettings):
    """GEMINI_API_KEY (the chat's key), STT_MODEL, STT_DAILY_BUDGET (0 turns these requests off),
    STT_TIMEOUT_S. Read from the environment and the repository's .env, like core/agent/tts.py."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", env_ignore_empty=True,
                                      extra="ignore")

    gemini_api_key: SecretStr | None = None
    stt_model: str = DEFAULT_STT_MODEL
    stt_daily_budget: int = Field(default=DEFAULT_STT_BUDGET, ge=0)
    stt_timeout_s: float = Field(default=DEFAULT_STT_TIMEOUT_S, gt=0, le=60)


# (model, audio, mime type, prompt, timeout_s) -> (text, usage)
SttTransport = Callable[[str, bytes, str, str, float], tuple[str, CallUsage]]


class SdkSttTransport:
    """The real transport: google-genai's generate_content with the prompt and the audio inline, on v1beta.
    The SDK's own retries stay off; the server deadline is never below the API's minimum."""

    def __init__(self, api_key: str) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key, http_options={"api_version": API_VERSION})

    def __call__(self, model: str, audio: bytes, mime_type: str, prompt: str,
                 timeout_s: float) -> tuple[str, CallUsage]:
        from google.genai import types

        server_deadline = max(MIN_SERVER_DEADLINE_S, math.ceil(timeout_s))
        config = types.GenerateContentConfig.model_validate({
            "temperature": 0,
            "max_output_tokens": 512,
            "thinking_config": {"thinking_level": "low"},
            "http_options": {"timeout": int(timeout_s * 1000), "headers": {"X-Server-Timeout": str(server_deadline)}},
        })
        contents = [prompt, types.Part.from_bytes(data=audio, mime_type=mime_type)]
        response = self._client.models.generate_content(model=model, contents=contents, config=config)
        meta = response.usage_metadata
        usage = CallUsage(prompt_tokens=getattr(meta, "prompt_token_count", None) or 0,
                          thought_tokens=getattr(meta, "thoughts_token_count", None) or 0,
                          output_tokens=getattr(meta, "candidates_token_count", None) or 0)
        parts = []
        for candidate in (response.candidates or [])[:1]:
            for part in (candidate.content.parts if candidate.content else None) or []:
                if part.text and not getattr(part, "thought", False):
                    parts.append(part.text)
        return "".join(parts), usage


def gemini_mime(content_type: str | None) -> str | None:
    """The Gemini type for a request's Content-Type (parameters such as codecs dropped), or None."""
    base = (content_type or "").split(";", 1)[0].strip().lower()
    return MIME_TYPES.get(base)


def wav_seconds(audio: bytes) -> float | None:
    """The length of a WAV clip from its header, or None when it cannot be read as WAV."""
    try:
        with wave.open(io.BytesIO(audio)) as w:
            rate = w.getframerate()
            return w.getnframes() / rate if rate else None
    except (wave.Error, EOFError, ValueError):
        return None


# What the model may answer instead of an empty text when it hears no speech (#759). Only a whole answer
# matches, after surrounding brackets and punctuation are dropped, so a real question is never taken for one.
NO_SPEECH = re.compile(
    r"(?:there is |there's )?no (?:speech|audio|words?|voice)(?: (?:was |is )?(?:detected|heard|spoken|found))?"
    r"(?: in (?:this|the) (?:audio|clip|recording))?"
    r"|silence|silent|inaudible|empty|blank|ei puhetta|hiljaisuus|hiljaista"
)


def is_no_speech(text: str) -> bool:
    """Whether a cleaned transcript is empty or only says that there was no speech."""
    return not text or NO_SPEECH.fullmatch(text.strip(" .!*_[](){}<>").lower()) is not None


def clean_transcript(text: str) -> str:
    """One line of plain text, at most MAX_TEXT characters, cut at a word break when one is near."""
    line = " ".join((text or "").split()).strip().strip('"\u201c\u201d').strip()
    if len(line) <= MAX_TEXT:
        return line
    cut = line[:MAX_TEXT]
    space = cut.rfind(" ")
    return cut[:space] if space > MAX_TEXT - 40 else cut


class SttService:
    def __init__(self, transport: SttTransport | None, *, model: str = DEFAULT_STT_MODEL, ledger: Ledger,
                 timeout_s: float = DEFAULT_STT_TIMEOUT_S, clock: Callable[[], float] = time.monotonic) -> None:
        self.transport = transport        # None: no key, every clip is refused
        self.model = model
        self.ledger = ledger
        self.timeout_s = timeout_s
        self._clock = clock

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

    def check(self, audio: bytes, content_type: str | None) -> str:
        """The Gemini type of a clip that may be sent, else SttError (empty, too_large, unsupported, too_long)."""
        if not audio:
            raise SttError("empty")
        if len(audio) > MAX_BYTES:
            raise SttError("too_large")
        mime = gemini_mime(content_type)
        if mime is None:
            raise SttError("unsupported")
        if mime == "audio/wav":
            seconds = wav_seconds(audio)
            if seconds is None:
                raise SttError("unsupported")
            if seconds > MAX_SECONDS:
                raise SttError("too_long")
        return mime

    def transcribe(self, audio: bytes, content_type: str | None, language: str) -> str:
        """The spoken words as one line of text. Raises SttError when there is no text to give."""
        mime = self.check(audio, content_type)
        if self.transport is None:
            raise SttError("no_key")
        if self.ledger.daily_cap == 0:
            raise SttError("disabled")
        refusal = self.ledger.reserve("stt")
        if refusal == "budget":
            raise SttError("budget", self.retry_after())
        if refusal == "busy":
            raise SttError("busy", 5)
        if refusal is not None:
            raise SttError(refusal)
        prompt = PROMPT.format(language=LANGUAGE_NAMES.get(language, "English"))
        started = self._clock()
        result = "ok"
        usage = CallUsage()
        try:
            raw, usage = self.transport(self.model, audio, mime, prompt, self.timeout_s)
            if usage.prompt_tokens > MAX_PROMPT_TOKENS:
                raise SttError("too_long")
        except Exception as exc:  # noqa: BLE001 - only a short code leaves this method
            result = exc.code if isinstance(exc, SttError) else _error_code(exc)[0]
            raise SttError(result) from None
        finally:
            latency_ms = int((self._clock() - started) * 1000)
            used = self.ledger.add("stt", self.model, result, latency_ms, usage)
            ops_log.info("stt request %s, %d bytes (%s ms), %d of %s in 24 h", result, len(audio), latency_ms,
                         used, self.ledger.daily_cap)
        text = clean_transcript(raw)
        if is_no_speech(text):
            raise SttError("no_speech")
        return text


def make_stt_service(settings: SttSettings | None = None, *, ledger_path: Path = DEFAULT_LEDGER,
                     off_switch: Path = OFF_SWITCH, transport: SttTransport | None = None) -> SttService:
    """The service's ears. Without GEMINI_API_KEY there is no transport: every clip is refused (503)."""
    s = settings or SttSettings()
    if transport is None and s.gemini_api_key is not None and s.gemini_api_key.get_secret_value().strip():
        transport = SdkSttTransport(s.gemini_api_key.get_secret_value().strip())
    ledger = Ledger(ledger_path, s.stt_daily_budget, off_switch, max_in_flight=MAX_IN_FLIGHT)
    return SttService(transport, model=(s.stt_model or DEFAULT_STT_MODEL).strip(), ledger=ledger,
                      timeout_s=s.stt_timeout_s)
