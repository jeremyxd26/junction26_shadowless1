"""GET /api/bill/samples and the sample images (#249), without a database."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core.app.api.schemas import ErrorResponse
from core.app.main import create_app
from core.app.settings import Settings
from core.bills import gallery


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(Settings(_env_file=None, database_url=None)), raise_server_exceptions=False) as c:
        yield c


def test_the_list_has_id_title_language_and_image_only(client):
    r = client.get("/api/bill/samples?lang=fi")
    assert r.status_code == 200
    samples = r.json()["samples"]
    assert [s["sample_id"] for s in samples] == ["sample_1", "sample_2", "sample_3", "sample_4"]
    assert all(set(s) == {"sample_id", "title", "language", "image_url"} for s in samples)
    assert [s["title"] for s in samples][:2] == ["Vuokralasku", "Sähkölasku"]
    assert [s["language"] for s in samples] == ["fi", "fi", "fi", "en"]
    english = client.get("/api/bill/samples").json()["samples"]
    assert english[0]["title"] == "Rent bill" and english[3]["language"] == "en"


def test_the_true_fields_are_never_in_the_list(client):
    text = client.get("/api/bill/samples?lang=en").text + client.get("/api/bill/samples?lang=fi").text
    for s in gallery.answer_key()["samples"]:
        for key in ("payee", "iban", "reference", "amount", "due_date", "barcode"):
            value = s["truth"][key]
            assert value is None or value not in text, (s["sample_id"], key)
    assert "truth" not in text and "signals" not in text


def test_an_image_is_served_with_a_long_cache_lifetime(client):
    first = client.get("/api/bill/samples").json()["samples"][0]
    r = client.get(first["image_url"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert r.content == (gallery.SAMPLES_DIR / "sample_1.png").read_bytes()
    stale = client.get("/api/bill/samples/sample_1.png?v=000000000000")
    assert stale.status_code == 200 and stale.headers["cache-control"] == "no-cache"   # not the current image
    assert client.get("/api/bill/samples/sample_1.png").headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", ["sample_9.png", "samples.json", "sample_1.pdf", "README.md", "..%2Fsamples.json",
                                  "%2E%2E%2Fparse.py"])
def test_nothing_else_is_served(client, path):
    r = client.get(f"/api/bill/samples/{path}")
    assert r.status_code == 404
    assert ErrorResponse.model_validate(r.json()).error.code == "not_found"


def test_a_bad_language_is_a_400(client):
    r = client.get("/api/bill/samples?lang=sv")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
