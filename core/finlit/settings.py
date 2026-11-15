"""Settings for the finlit package, read like the service's own (core/agent/gemini.py GeminiSettings):
environment variables first, then .env in the repository root. Secrets stay SecretStr and are never logged.

- DATABASE_URL: the PostgreSQL database with the pgvector extension available.
- GEMINI_API_KEY: the service's Gemini key, used here for embeddings only.
- FINLIT_EMBED_MODEL: the embedding model (default gemini-embedding-001; 768 dimensions either way). Set it in
  the process environment, not in .env: the local pre-commit hook blocks commits that contain any .env value
  of 12+ characters, and the model name appears in code and docs.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = ROOT / "core" / "knowledge" / "finlit"
VAR_DIR = ROOT / "var"
DEFAULT_EMBED_MODEL = "gemini-embedding-001"


class FinlitSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", env_ignore_empty=True,
                                      extra="ignore")

    database_url: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    finlit_embed_model: str = DEFAULT_EMBED_MODEL
