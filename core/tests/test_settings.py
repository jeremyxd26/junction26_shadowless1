from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from core.app.settings import DEFAULT_CORS_ORIGINS, Settings


def test_defaults(clean_env):
    s = Settings(_env_file=None)
    assert s.database_url is None
    assert s.demo_today == date(2026, 9, 30)
    assert s.gemini_api_key is None
    assert s.gemini_model is None
    assert s.cors_origins == DEFAULT_CORS_ORIGINS


def test_reads_environment(clean_env):
    clean_env.setenv("DATABASE_URL", "postgresql://u:p@db.example:5432/coach")
    clean_env.setenv("DEMO_TODAY", "2026-06-30")
    clean_env.setenv("GEMINI_API_KEY", "test-key")
    clean_env.setenv("GEMINI_MODEL", "gemini-test-model")
    clean_env.setenv("CORS_ORIGINS", "https://app.example, https://dev.app.example ,")
    s = Settings(_env_file=None)
    assert s.database_url.get_secret_value() == "postgresql://u:p@db.example:5432/coach"
    assert s.demo_today == date(2026, 6, 30)
    assert s.gemini_api_key.get_secret_value() == "test-key"
    assert s.gemini_model == "gemini-test-model"
    assert s.cors_origins == ["https://app.example", "https://dev.app.example"]


def test_empty_values_count_as_unset(clean_env):
    # A plain copy of .env.example has empty values; the service must still start.
    for name in ("DATABASE_URL", "GEMINI_API_KEY", "GEMINI_MODEL", "CORS_ORIGINS"):
        clean_env.setenv(name, "")
    s = Settings(_env_file=None)
    assert s.database_url is None
    assert s.gemini_api_key is None
    assert s.gemini_model is None
    assert s.cors_origins == DEFAULT_CORS_ORIGINS


def test_reads_dotenv_file_and_ignores_other_keys(clean_env, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DEMO_TODAY=2026-01-31\nSOME_OTHER_TOOL_KEY=x\n", encoding="utf-8")
    s = Settings(_env_file=env_file)
    assert s.demo_today == date(2026, 1, 31)


def test_environment_wins_over_dotenv(clean_env, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DEMO_TODAY=2026-01-31\n", encoding="utf-8")
    clean_env.setenv("DEMO_TODAY", "2026-02-28")
    assert Settings(_env_file=env_file).demo_today == date(2026, 2, 28)


def test_invalid_demo_today_is_rejected(clean_env):
    clean_env.setenv("DEMO_TODAY", "30.09.2026")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_secrets_never_show_in_repr(clean_env):
    clean_env.setenv("DATABASE_URL", "postgresql://u:hunter2-secret@db.example/coach")
    clean_env.setenv("GEMINI_API_KEY", "gemini-secret-value")
    s = Settings(_env_file=None)
    for text in (repr(s), str(s), str(s.model_dump())):
        assert "hunter2-secret" not in text
        assert "gemini-secret-value" not in text
