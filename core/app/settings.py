"""Typed settings for the core service.

Values come only from environment variables; for local runs the repository's `.env` is read as well
(real environment variables win). Empty values count as unset, so a copy of `.env.example` works as is.
Secrets are `SecretStr`, so they never show up in a repr, a log line or an error message.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, Any

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
    )

    database_url: SecretStr | None = None
    demo_today: date = date(2026, 9, 30)
    gemini_api_key: SecretStr | None = None
    gemini_model: str | None = None
    cors_origins: CommaSeparated = Field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))
