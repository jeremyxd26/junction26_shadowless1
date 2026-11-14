"""The interactive API docs and the schema are off unless API_DOCS=1 (#62)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.app.main import create_app
from core.app.settings import Settings

DOC_PATHS = ["/docs", "/redoc", "/openapi.json"]


@pytest.mark.parametrize("path", DOC_PATHS)
def test_api_docs_are_off_by_default(clean_env, path):
    settings = Settings(_env_file=None)
    assert settings.api_docs is False
    with TestClient(create_app(settings)) as client:
        response = client.get(path)
    assert response.status_code == 404
    body = response.json()   # the error envelope of every API error (contracts/api.md), nothing about the API
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "retryable"}
    assert body["error"]["retryable"] is False
    assert "openapi" not in response.text.lower() and "swagger" not in response.text.lower()


@pytest.mark.parametrize("path", DOC_PATHS)
def test_api_docs_are_served_when_the_setting_is_on(clean_env, path):
    clean_env.setenv("API_DOCS", "1")
    settings = Settings(_env_file=None)
    assert settings.api_docs is True
    with TestClient(create_app(settings)) as client:
        assert client.get(path).status_code == 200
