"""Typed settings for the core service.

Values come only from environment variables; for local runs the repository's `.env` is read as well
(real environment variables win). Empty values count as unset, so a copy of `.env.example` works as is.
Secrets are `SecretStr`, so they never show up in a repr, a log line or an error message.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field, SecretStr
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

# Local dev servers of the app (Next.js and Vite defaults). Production origins are set via CORS_ORIGINS.
DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def _split_commas(value: Any) -> Any:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


# "https://a.example, https://b.example" -> ["https://a.example", "https://b.example"]
CommaSeparated = Annotated[list[str], NoDecode, BeforeValidator(_split_commas)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",  # .env also holds keys for other tools
        # A validation error names the setting but never echoes its value, so a start-up error cannot
        # print a secret (#198).
        hide_input_in_errors=True,
    )

    database_url: SecretStr | None = None
    # Most connections the service's pool opens. The shared database allows 100 (about 94 for normal
    # users); 10 leaves room for the worker sessions, reviewers, tests and a few local runs. At most 20,
    # so one setting can never take most of the plan's connections.
    db_pool_max: int = Field(default=10, ge=1, le=20)
    # Interactive API docs (/docs, /redoc, /openapi.json): off unless API_DOCS=1, for local development.
    api_docs: bool = False
    demo_today: date = date(2026, 9, 30)
    gemini_api_key: SecretStr | None = None
    gemini_model: str | None = None
    cors_origins: CommaSeparated = Field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))
    # Which customers the API serves (#101): `personas`, only the ids of core/config/personas.yaml (the
    # demo and the dev service), or `all`, every customer of the data (local eval runs only).
    demo_customers: Literal["personas", "all"] = "personas"
    # Viewer sessions (#144): the cookie that keeps one viewer's review answers apart from everyone
    # else's. Secure is on by default; set VIEWER_COOKIE_SECURE=false only for local development over http.
    viewer_cookie_secure: bool = True
    # POST /api/baskets/label, sliding windows; 0 turns a limit off (#144). No window is shared by all
    # viewers of a customer: answers are per viewer, so such a window would protect nothing and would let
    # anyone block the presenter's tap (review of #144).
    # Sized for a room (security review): everyone on a venue's Wi-Fi arrives from one client address, so the
    # address-keyed limits are generous, and the per-viewer limit and the session cap are what protect.
    label_rate_limit_per_min: int = Field(default=120, ge=0)           # per client address
    label_rate_limit_customer_per_min: int = Field(default=60, ge=0)   # per client address and customer
    label_rate_limit_viewer_per_min: int = Field(default=10, ge=0)     # per viewer session
    # New viewer sessions per client address and hour. At 300, one attendee on the venue network could
    # stop the room's first answers for an hour with 5 requests a minute; the session cap with
    # least-recently-active eviction (core.tools.reviews.MAX_SESSIONS) is the real bound on storage.
    label_new_sessions_per_hour: int = Field(default=1000, ge=0)
