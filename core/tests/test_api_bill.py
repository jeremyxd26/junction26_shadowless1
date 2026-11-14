"""POST /api/bill/explain without a database (#242): validation, the persona allowlist, the reasons of a
422 invalid_bill in the body's language, and the wiring of a 200."""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.app.api import bill, deps, viewer
from core.app.api.errors import ApiError
from core.app.main import create_app
from core.app.settings import Settings

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "api.md"
BARCODE = "421123456000007850008124000000000000000000001232261001"
FIELDS = {"payee": "Esimerkki Remontti Oy", "iban": "FI71 1234 5600 0098 76", "reference": "12344",
          "amount": "145.00", "due_date": "2026-10-20"}
SANNA = "CUST00860"


def client() -> TestClient:
    return TestClient(create_app(Settings(_env_file=None)), raise_server_exceptions=False)


def post(body: dict, **kw):
    with client() as c:
        return c.post("/api/bill/explain", json=body, **kw)


def assert_refusal(response, reason: str, message: str | None = None):
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "invalid_bill" and error["reason"] == reason and error["retryable"] is False
    if message is not None:
        assert error["message"] == message


@pytest.mark.parametrize("body", [
    {"customer_id": SANNA},
    {"customer_id": SANNA, "barcode": None, "fields": None},
    {"customer_id": SANNA, "barcode": BARCODE, "fields": FIELDS},
])
def test_both_or_neither_is_a_422_with_its_reason(clean_env, body):
    assert_refusal(post(body), "one_of_barcode_or_fields", "Send the barcode or the bill's details, one of the two.")


def test_payee_beside_fields_is_a_422(clean_env):
    assert_refusal(post({"customer_id": SANNA, "fields": FIELDS, "payee": "X"}), "payee_with_fields")


@pytest.mark.parametrize("barcode, reason", [
    ("123", "barcode_length"),
    (BARCODE[:-10] + "1233" + BARCODE[-6:], "barcode_check"),
    (BARCODE[:17] + "00000000" + BARCODE[25:], "amount_missing"),
    (BARCODE[:-6] + "000000", "due_date_missing"),
])
def test_a_barcode_that_cannot_be_used_is_a_422_with_its_reason(clean_env, barcode, reason):
    assert_refusal(post({"customer_id": SANNA, "barcode": barcode}), reason)


def test_the_refusal_is_in_the_bodys_language(clean_env):
    response = post({"customer_id": SANNA, "barcode": BARCODE[:-10] + "1233" + BARCODE[-6:], "language": "fi"})
    assert_refusal(response, "barcode_check",
                   "Viivakoodi ei läpäise tarkistusta. Vertaa sitä paperilaskuun tai kirjoita tiedot.")


@pytest.mark.parametrize("body", [
    {"customer_id": SANNA, "fields": {**FIELDS, "due_date": 0}},
    {"customer_id": SANNA, "fields": {**FIELDS, "due_date": "2026-10-20T00:00:00"}},
    {"customer_id": SANNA, "fields": {**FIELDS, "amount": "0.00"}},
    {"customer_id": SANNA, "fields": {**FIELDS, "amount": 145}},
    {"customer_id": SANNA, "fields": {**FIELDS, "note": "x"}},
    {"customer_id": SANNA, "barcode": BARCODE, "surprise": 1},
    {"customer_id": SANNA, "barcode": "1" * 81},
    {"customer_id": "sanna", "barcode": BARCODE},
])
def test_a_body_that_does_not_validate_is_400(clean_env, body):
    response = post(body)
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_request"


def test_a_customer_that_is_not_served_is_404_before_anything_else(clean_env):
    response = post({"customer_id": "CUST00002", "barcode": "123"})
    assert response.status_code == 404 and response.json()["error"]["code"] == "customer_not_found"


class _Conn:
    """Enough of a connection for the request path before the tool runs (the evidence table check)."""

    def execute(self, sql, params=None):
        class _Res:
            def fetchone(self):
                return (1,)

        return _Res()


class _Pool:
    @contextmanager
    def connection(self, timeout=None):
        yield _Conn()


def test_a_valid_bill_is_answered_with_the_explanation(clean_env, monkeypatch):
    """The wiring: the context the endpoint builds, and the response model around the tool's output (the
    contract's example, so every field passes the model)."""
    example = json.loads(dict(re.findall(r"<!-- example: ([\w.]+) -->\s*```json\n(.*?)\n```",
                                         CONTRACT.read_text(encoding="utf-8"), re.S))["bill.response"])
    seen = {}

    def fake_explain(ctx, read):
        seen.update(customer=ctx.customer_id, language=ctx.language, payee=read.payee, amount=str(read.amount))
        return {k: v for k, v in example.items() if k not in ("customer_id", "as_of", "language")}

    monkeypatch.setattr(bill, "explain_bill", fake_explain)
    monkeypatch.setattr(deps, "require_customer", lambda conn, customer_id: None)
    with client() as c:
        c.app.state.pool = _Pool()
        response = c.post("/api/bill/explain", json={"customer_id": SANNA, "barcode": BARCODE,
                                                     "payee": "Esimerkki Asunnot Oy", "language": "fi"})
        c.app.state.pool = None
    assert response.status_code == 200, response.text
    assert seen == {"customer": SANNA, "language": "fi", "payee": "Esimerkki Asunnot Oy", "amount": "812.40"}
    body = response.json()
    assert body["customer_id"] == SANNA and body["language"] == "fi" and body["as_of"] == "2026-09-30"
    assert body["safe_to_spend"]["after"]["value"] == 169.56
    assert viewer.COOKIE in response.headers["set-cookie"]     # a new viewer, as on the overview


def test_the_bill_context_carries_the_viewer(clean_env, monkeypatch):
    """Like /api/whatif (#144): the ToolContext gets the viewer of the cookie, so a viewer's bill starts from
    their own spike-review answer, as their hero does (the numbers: test_viewer_sessions_db.py)."""
    seen: list[str | None] = []

    @contextmanager
    def no_database(request, customer_id):
        yield None

    def capture(ctx, read):
        seen.append(ctx.viewer)
        raise ApiError("invalid_request")

    monkeypatch.setattr(bill, "customer_connection", no_database)
    monkeypatch.setattr(bill, "explain_bill", capture)
    a, b = viewer.new_value(), viewer.new_value()
    with client() as c:
        for value in (a, b, None):
            c.cookies.clear()
            if value is not None:
                c.cookies.set(viewer.COOKIE, value, domain="testserver.local")
            assert c.post("/api/bill/explain", json={"customer_id": SANNA, "fields": FIELDS}).status_code == 400
    assert seen[:2] == [viewer.session_key(a), viewer.session_key(b)]
    assert seen[2] is not None and len(seen[2]) == 64 and seen[2] not in seen[:2]   # a new viewer, no answers
