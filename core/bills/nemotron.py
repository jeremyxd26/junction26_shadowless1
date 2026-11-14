"""The bill photo read by Nemotron Super VL through Verda's inference API (#573): the model reads the fields,
the code checks them (core/bills/read.py), the user confirms. The composer and the planner stay on Gemini;
Nemotron never writes an answer.

The reader is a GeminiClient over NemotronTransport. The transport sends the extract request as an
OpenAI-compatible chat completion (the image as a base64 data URL, READ_SCHEMA as a json_schema response
format) and returns the answer in the shape of a GenerateContentResponse. So the adapter's cache (the image's
SHA-256 in the key, never its bytes), single flight, cache-only reading, request ledger (its own file and
daily cap), pauses and off-switch (the same switch file as Gemini) work unchanged, and read_bill takes it like
the Gemini client.

FallbackReader tries Nemotron first. When Nemotron fails, is refused, paused, out of budget or gives no usable
answer, the Gemini extract role reads instead, so the demo never waits for the new provider. Without a Gemini
key, an unusable Nemotron answer gets one more Nemotron request, then the "could not read" path.

Settings, from the environment (and the repository's .env, like the Gemini settings), names in .env.example:
- VERDA_INFERENCE_KEY: the inference endpoint's key (never logged, never in an error, never in a cache entry).
  Separate from VERDA_CLIENT_ID / VERDA_CLIENT_SECRET (the instance API), which this module never reads.
- VERDA_INFERENCE_URL: the endpoint's base URL (default PROVIDER.default_url, the provider's own).
- NEMOTRON_VL_MODEL: the model id (default PROVIDER.default_model, the provider's own).
- BILL_READER: auto (default: Nemotron when the key is set, else Gemini), gemini, or nemotron (the same as auto,
  said explicitly).
- NEMOTRON_TIMEOUT_S: seconds for the whole reading, from the request to the last byte of the answer (default 30,
  at most 30), so a slow provider falls back in time. The real check on #616 read warm in 6.5 to 24.5 s (#637).
- NEMOTRON_DAILY_BUDGET: Nemotron requests in any rolling 24 hours (default 30; 0 turns the reader off),
  counted in var/nemotron-requests.jsonl.
A bad value is the default, with one log line; nothing fails at start-up.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import string
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.agent.gemini_client import GeminiClient, GeminiError, Ledger, Reply

log = logging.getLogger("core.bills.nemotron")
ops_log = logging.getLogger("uvicorn.error")   # the service log: what the operator sees (a fallback, a bad setting)
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = ROOT / "var" / "nemotron-requests.jsonl"
# The real check on #616 read the samples warm in 6.5 to 24.5 s; 12 s sent the slowest to Gemini every time (#637).
MAX_TIMEOUT_S = 30.0
DEFAULT_TIMEOUT_S = MAX_TIMEOUT_S
DEFAULT_DAILY_BUDGET = 30
# The answer is six short strings (max_tokens 4096): a larger body is no reading, and is never read further (#594).
MAX_RESPONSE_BYTES = 32 * 1024
CHUNK_BYTES = 4096
_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


@dataclass(frozen=True)
class Provider:
    """The provider's details in one place, so another answer is a one-line change (#573). From Verda (relayed on
    14 Nov): an OpenAI-compatible chat API at default_url, model id default_model, text and image input; the
    reasoning comes back in `reasoning_content`, which is never read (only `content` is); `max_tokens` limits the
    length. NVIDIA's guide for Nemotron-3.5-Super-VL turns the reasoning off per request with
    chat_template_kwargs.enable_thinking=false; the "/no_think" system line is what #169 needed on the same model."""

    default_url: str = "https://containers.datacrunch.io/nemotron-3-5-super-vl-b300/v1"
    chat_path: str = "/chat/completions"
    default_model: str = "nemotron-3.5-super-vl"
    image: str = "data_url"            # an OpenAI image_url part holding data:<mime>;base64,<bytes>
    response_format: str = "json_schema"   # "json_object" if the endpoint takes no schema
    reasoning_off: bool = True         # "/no_think" and chat_template_kwargs.enable_thinking=false


PROVIDER = Provider()
FINISH = {"stop": "STOP", "length": "MAX_TOKENS", "content_filter": "SAFETY", "tool_calls": "STOP"}
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S | re.I)


# ---- errors the adapter maps to short codes (gemini_client._error_code) -----------------------------------

class ProviderStatus(Exception):
    """An HTTP status from the provider. Only the status: never the body, never the key."""

    def __init__(self, code: int) -> None:
        super().__init__(f"status {code}")
        self.code = code


class ProviderTimeout(TimeoutError):
    pass


class ProviderNetwork(ConnectionError):
    pass


class ProviderBadResponse(Exception):
    pass


# ---- the request and the answer ------------------------------------------------------------------------------

def image_part(mime_type: str, data: bytes, provider: Provider = PROVIDER) -> dict[str, Any]:
    if provider.image != "data_url":
        raise ValueError("unknown image encoding")
    return {"type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"}}


def request_body(model: str, contents: list[dict[str, Any]], config: dict[str, Any],
                 provider: Provider = PROVIDER) -> dict[str, Any]:
    """The adapter's extract request (one user turn: the text and one inline image) as a chat completion."""
    content: list[dict[str, Any]] = []
    for turn in contents:
        for part in turn.get("parts") or []:
            if part.get("text"):
                content.append({"type": "text", "text": part["text"]})
            elif part.get("inline_data"):
                content.append(image_part(part["inline_data"]["mime_type"], part["inline_data"]["data"], provider))
    system = str(config.get("system_instruction") or "")
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": ("/no_think\n" + system) if provider.reasoning_off else system},
                     {"role": "user", "content": content}],
        "max_tokens": int(config.get("max_output_tokens") or 1024),
        "temperature": 0.0,
        "stream": False,
    }
    if provider.reasoning_off:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    schema = config.get("response_json_schema")
    if schema is not None:
        body["response_format"] = (
            {"type": "json_schema", "json_schema": {"name": "bill_read", "schema": schema}}
            if provider.response_format == "json_schema" else {"type": "json_object"})
    return body


def without_think(text: str) -> str:
    """The text without <think>…</think> blocks, in one linear pass (a lazy regex is quadratic on unclosed tags,
    #594). An unclosed block drops the rest: it is reasoning, not the reading. The case fold is ASCII only, so an
    index in the folded text is the same index in the text ("İ".lower() is two characters, #637)."""
    lower, out, i = text.translate(_ASCII_LOWER), [], 0
    while True:
        start = lower.find("<think>", i)
        if start < 0:
            out.append(text[i:])
            break
        out.append(text[i:start])
        end = lower.find("</think>", start + 7)
        if end < 0:
            break
        i = end + 8
    return "".join(out)


def answer_text(text: str) -> str:
    """The content without a reasoning block or a Markdown code fence around the JSON."""
    text = without_think(text or "").strip()
    fenced = _FENCE.match(text)
    return fenced.group(1).strip() if fenced else text


def response_as_gemini(model: str, data: dict[str, Any]) -> dict[str, Any]:
    """A chat completion in the shape of a GenerateContentResponse, for the adapter's parse()."""
    choices = data.get("choices") or []
    if not choices:
        return {"candidates": [], "model_version": model}
    choice = choices[0]
    text = answer_text(str((choice.get("message") or {}).get("content") or ""))
    usage = data.get("usage") or {}
    return {
        "candidates": [{"content": {"role": "model", "parts": [{"text": text}]},
                        "finish_reason": FINISH.get(str(choice.get("finish_reason") or "stop"), "STOP")}],
        "usage_metadata": {"prompt_token_count": int(usage.get("prompt_tokens") or 0),
                           "candidates_token_count": int(usage.get("completion_tokens") or 0)},
        "model_version": model,
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would send a POST's 301/302/303 on as a GET to the new place, to another host
    or to http, with the Authorization header (#594). Every 3xx becomes an HTTPError, so a short code."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001 - urllib's signature
        return None


def _default_opener() -> Callable[..., Any]:
    """The transport's opener: urllib's, without redirects. Tests replace it (core/conftest.py refuses it)."""
    return urllib.request.build_opener(_NoRedirect).open


def valid_url(url: str | None) -> bool:
    """An https URL with a host and no user or password in it (#594). Only the server's environment sets it, and no
    user input reaches it, so a private or loopback host is not refused."""
    if not url or any(ch.isspace() for ch in url):
        return False
    try:
        parts = urllib.parse.urlsplit(url)
        parts.port              # a port that is not a number from 0 to 65535 raises ValueError (#637)
    except ValueError:
        return False
    return parts.scheme == "https" and bool(parts.hostname) and parts.username is None and parts.password is None


def _read_body(response: Any, deadline: float) -> bytes:
    """The answer's body, at most MAX_RESPONSE_BYTES + 1 bytes, read by the deadline of the whole reading (#637).
    The socket's timeout holds for each wait alone, so an answer that trickles in a few bytes at a time would run
    on far past it: each read takes what one network read gives (read1), and no read starts after the deadline.
    A wait that started before the deadline still ends by the socket's timeout."""
    read = getattr(response, "read1", None) or response.read
    chunks: list[bytes] = []
    size = 0
    while size <= MAX_RESPONSE_BYTES:
        if time.monotonic() > deadline:
            raise ProviderTimeout()
        chunk = read(min(CHUNK_BYTES, MAX_RESPONSE_BYTES + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


class NemotronTransport:
    """A gemini_client Transport: (model, contents, config, timeout_s) -> a GenerateContentResponse as JSON."""

    def __init__(self, base_url: str, api_key: str, provider: Provider = PROVIDER,
                 opener: Callable[..., Any] | None = None) -> None:
        if not valid_url(base_url):
            raise ValueError("VERDA_INFERENCE_URL must be an https URL with a host and no credentials")
        self.url = base_url.rstrip("/") + provider.chat_path
        self._key = api_key
        self.provider = provider
        self._open = opener or _default_opener()

    def __repr__(self) -> str:   # never the key
        return f"NemotronTransport({self.provider.chat_path})"

    def __call__(self, model: str, contents: list[dict[str, Any]], config: dict[str, Any],
                 timeout_s: float) -> dict[str, Any]:
        body = request_body(model, contents, config, self.provider)
        request = urllib.request.Request(
            self.url, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Authorization": "Bearer " + self._key, "Content-Type": "application/json",
                     "Accept": "application/json"})
        deadline = time.monotonic() + timeout_s     # the whole reading, not each wait (#637)
        try:
            with self._open(request, timeout=timeout_s) as response:
                raw = _read_body(response, deadline)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ProviderBadResponse()
            data = json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()                      # the body is neither held nor reachable through the chain
            raise ProviderStatus(status) from None
        except TimeoutError:
            raise ProviderTimeout() from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise ProviderTimeout() from None
            raise ProviderNetwork() from None
        except (ValueError, UnicodeDecodeError):
            raise ProviderBadResponse() from None
        if not isinstance(data, dict):
            raise ProviderBadResponse()
        return response_as_gemini(model, data)


# ---- settings -----------------------------------------------------------------------------------------------

_BAD_LOGGED: set[str] = set()


def _bad(name: str, default: Any, wanted: str) -> Any:
    if name not in _BAD_LOGGED:
        _BAD_LOGGED.add(name)
        log.warning("%s must be %s; using the default", name, wanted)
    return default


class NemotronSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", env_ignore_empty=True,
                                      extra="ignore")

    bill_reader: str = "auto"
    verda_inference_url: str | None = None
    verda_inference_key: SecretStr | None = None
    nemotron_vl_model: str | None = None
    nemotron_timeout_s: float = DEFAULT_TIMEOUT_S
    nemotron_daily_budget: int = DEFAULT_DAILY_BUDGET

    @field_validator("bill_reader", mode="before")
    @classmethod
    def _reader(cls, value: Any) -> str:
        choice = str(value).strip().lower() if value is not None else ""
        return choice if choice in ("auto", "gemini", "nemotron") else _bad("BILL_READER", "auto",
                                                                             "auto, gemini or nemotron")

    @field_validator("nemotron_timeout_s", mode="before")
    @classmethod
    def _timeout(cls, value: Any) -> float:
        try:
            seconds = float(str(value).strip())
        except (TypeError, ValueError):
            seconds = -1.0
        return seconds if 0 < seconds <= MAX_TIMEOUT_S else _bad("NEMOTRON_TIMEOUT_S", DEFAULT_TIMEOUT_S,
                                                                 "seconds, more than 0, at most 30")

    @field_validator("nemotron_daily_budget", mode="before")
    @classmethod
    def _budget(cls, value: Any) -> int:
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            number = -1
        return number if number >= 0 else _bad("NEMOTRON_DAILY_BUDGET", DEFAULT_DAILY_BUDGET,
                                               "a whole number of requests, 0 or more")


def model_id(s: NemotronSettings) -> str:
    return (s.nemotron_vl_model or "").strip() or PROVIDER.default_model


def base_url(s: NemotronSettings) -> str:
    return (s.verda_inference_url or "").strip() or PROVIDER.default_url


def reader_choice(s: NemotronSettings) -> tuple[str, str]:
    """("nemotron", "") or ("gemini", why): the reader the service uses."""
    if s.bill_reader == "gemini":
        return "gemini", "BILL_READER=gemini"
    if not s.verda_inference_key:
        return "gemini", "no VERDA_INFERENCE_KEY"
    if not valid_url(base_url(s)):
        return "gemini", "VERDA_INFERENCE_URL is not an https URL with a host and no credentials"   # never echoed
    if s.nemotron_daily_budget == 0:
        return "gemini", "NEMOTRON_DAILY_BUDGET=0"
    return "nemotron", ""


def reader_state(settings: NemotronSettings | None = None, *, gemini_on: bool = True,
                 ledger_path: Path = DEFAULT_LEDGER) -> str:
    """One start-up line: which reader reads bill photos, and its fallback. No key, no URL."""
    s = settings or NemotronSettings()
    reader, why = reader_choice(s)
    if reader == "gemini":
        return f"bill reader: the Gemini extract role ({why})" + ("" if gemini_on else "; off: no GEMINI_API_KEY")
    used = Ledger(ledger_path, s.nemotron_daily_budget).count()
    fallback = "the Gemini extract role" if gemini_on else "none (no GEMINI_API_KEY)"
    return (f"bill reader: Nemotron {model_id(s)} on the Verda inference API ({s.nemotron_timeout_s:g} s, daily "
            f"budget {s.nemotron_daily_budget} requests, {used} sent in the last 24 h); fallback {fallback}")


# ---- the reader ---------------------------------------------------------------------------------------------

def make_nemotron_client(s: NemotronSettings, *, cache: str = "on", cache_dir: Path | None = None,
                         ledger_path: Path = DEFAULT_LEDGER, off_switch: Path | None = None,
                         opener: Callable[..., Any] | None = None) -> GeminiClient | None:
    """The Nemotron reader as a GeminiClient over NemotronTransport, or None when BILL_READER or the settings
    say Gemini. Its own ledger file and daily cap; the same off-switch file as Gemini."""
    if reader_choice(s)[0] != "nemotron":
        return None
    model = model_id(s)
    key = s.verda_inference_key.get_secret_value() if s.verda_inference_key is not None else ""
    transport = None if cache == "replay" else NemotronTransport(base_url(s), key, opener=opener)
    return GeminiClient(model, transport, cache=cache, cache_dir=None if cache == "off" else cache_dir,
                        ledger=Ledger(ledger_path, s.nemotron_daily_budget, off_switch,
                                      kind_caps={"extract": s.nemotron_daily_budget}),
                        extract_model=model, extract_timeout_s=s.nemotron_timeout_s)


class _Ledgers:
    """The request count of both readers, for the deploy's warm-up (core/bills/warmup.py)."""

    def __init__(self, ledgers: list[Any]) -> None:
        self.ledgers = ledgers

    def count(self, kind: str | None = None) -> int:
        return sum(ledger.count(kind) for ledger in self.ledgers)


class FallbackReader:
    """Nemotron first; the Gemini extract role when Nemotron gives nothing usable (#573). The same extract()
    as GeminiClient, so read_bill takes it. The reply's model says which model read."""

    def __init__(self, primary: Any, fallback: Any | None) -> None:
        self.primary = primary
        self.fallback = fallback
        self.ledger = _Ledgers([c.ledger for c in (primary, fallback)
                                if c is not None and getattr(c, "ledger", None) is not None])

    def extract(self, system: str, text: str, image: bytes, mime_type: str, schema: dict[str, Any],
                accept: Callable[[Reply], bool] | None = None, cache_only: bool = False) -> Reply:
        def read(client: Any) -> Reply:
            return client.extract(system, text, image, mime_type, schema, accept=accept, cache_only=cache_only)

        def usable(reply: Reply) -> bool:
            return not reply.blocked and (accept is None or accept(reply))

        reply: Reply | None = None
        try:
            reply = read(self.primary)
            if usable(reply):
                return reply
            why = "blocked" if reply.blocked else "unusable"
        except GeminiError as exc:
            if exc.code == "image" or self.fallback is None:
                raise                       # the fallback would refuse the same image; or there is none
            why = exc.code
        if self.fallback is None:
            if why == "unusable" and not cache_only:
                return read(self.primary)   # one more request (an unusable answer is not cached), then read_bill
            return reply                    # read_bill turns it into "could not read"
        ops_log.info("bill reader: Nemotron gave no usable reading (%s); the Gemini extract role reads", why)
        return read(self.fallback)


def make_reader(gemini_client: Any | None, settings: NemotronSettings | None = None, **client_options: Any) -> Any:
    """The client read_bill uses: FallbackReader(Nemotron, Gemini) when Nemotron is set up, the Gemini client
    alone when it is not, None when neither is. A Nemotron client that cannot be built is logged by class
    name and leaves the Gemini reader on."""
    s = settings or NemotronSettings()
    try:
        if "cache_dir" not in client_options or "cache" not in client_options:
            from core.agent.gemini import GeminiSettings, OFF_SWITCH
            env = GeminiSettings()
            client_options.setdefault("cache", env.gemini_cache)
            client_options.setdefault("cache_dir", Path(env.gemini_cache_dir))
            client_options.setdefault("off_switch", OFF_SWITCH)
        nemotron = make_nemotron_client(s, **client_options)
    except Exception as exc:  # noqa: BLE001 - the class name only; the Gemini reader stays on
        log.error("bill reader: Nemotron could not be set up (%s); the Gemini extract role reads", type(exc).__name__)
        nemotron = None
    if nemotron is None:
        return gemini_client
    return FallbackReader(nemotron, gemini_client)
