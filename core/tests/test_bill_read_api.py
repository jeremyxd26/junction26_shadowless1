"""POST /api/bill/read (#250), without a database, a key or a real model request: the reading client is a
GeminiClient on a fake transport that answers like the model, with the real parser of #241 and the sample
bills' answer key (#249)."""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from core.agent.gemini_client import GeminiClient, Ledger
from core.app.main import create_app
from core.app.settings import Settings
from core.bills import gallery

MODEL = "gemini-3.5-flash-lite"
TRUTH = {s["sample_id"]: s["truth"] for s in gallery.answer_key()["samples"]}


def answer(fields: dict) -> dict:
    """A model response holding one JSON text part, as the SDK returns it."""
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(fields)}]},
                            "finish_reason": "STOP"}],
            "usage_metadata": {"prompt_token_count": 1200, "candidates_token_count": 60}}


def printed(sample_id: str, **change) -> dict:
    t = TRUTH[sample_id]
    fields = {"payee": t["payee"], "iban": t["iban"], "reference": t["reference"], "amount": t["amount"],
              "due_date": t["due_date"], "barcode": t["barcode"]}
    fields.update(change)
    return {k: v for k, v in fields.items() if v is not None}


class Transport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, model, contents, config, timeout_s):
        self.requests.append(model)
        step = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture()
def app():
    return create_app(Settings(_env_file=None, database_url=None))


def read(app, transport, sample_id="sample_1", language="fi", cache_dir=None, ledger=None, customer="CUST00860"):
    app.state.bill_read_client = GeminiClient(MODEL, transport, cache="on" if cache_dir else "off", cache_dir=cache_dir,
                                              ledger=ledger, sleep=lambda s: None)
    with TestClient(app, raise_server_exceptions=False) as c:
        return c.post("/api/bill/read", json={"customer_id": customer, "language": language, "sample_id": sample_id})


def test_a_barcode_bill_read_correctly_checks_only_the_iban_and_the_reference(app):
    from core.app.api.schemas import BillReadResponse

    r = read(app, Transport(answer(printed("sample_1"))))
    assert r.status_code == 200
    body = r.json()
    BillReadResponse.model_validate(body)                      # the contract's shape (section 11.4)
    assert body["sample_id"] == "sample_1" and body["needs_confirmation"] is True and body["language"] == "fi"
    f = body["fields"]
    assert f["iban"]["value"] == TRUTH["sample_1"]["iban"] and f["iban"]["status"] == "checked"
    assert f["iban"]["source"] == "barcode" and f["amount"]["value"] == "836.65"
    assert f["amount"]["status"] == f["due_date"]["status"] == f["barcode"]["status"] == "unchecked"   # decision A
    assert f["due_date"]["value"] == "2026-10-08" and f["payee"]["status"] == "unchecked"
    assert "numbers" not in body and "cited" not in body       # a reading holds no Number object


def test_a_barcode_with_one_misread_iban_digit_is_dropped_and_the_printed_fields_stay_unconfirmed(app):
    barcode = TRUTH["sample_2"]["barcode"]
    misread = barcode[:5] + ("1" if barcode[5] != "1" else "2") + barcode[6:]
    r = read(app, Transport(answer(printed("sample_2", barcode=misread))), sample_id="sample_2")
    f = r.json()["fields"]
    assert f["barcode"] is None or f["barcode"]["status"] == "unchecked"
    assert f["iban"]["source"] == "printed" and f["amount"]["status"] == "unchecked"


def test_barcode_and_printed_amount_disagree(app):
    r = read(app, Transport(answer(printed("sample_1", amount="863.65"))))
    f = r.json()["fields"]
    assert f["amount"]["value"] == "836.65" and f["amount"]["status"] == "unchecked" and f["amount"]["note"]


def test_no_barcode_and_a_wrong_reference_check_digit(app):
    reference = TRUTH["sample_4"]["reference"]
    wrong = reference[:-1] + str((int(reference[-1]) + 1) % 10)
    r = read(app, Transport(answer(printed("sample_4", reference=wrong))), sample_id="sample_4", language="en")
    f = r.json()["fields"]
    assert f["reference"]["status"] == "unchecked" and f["reference"]["note"]
    assert f["iban"]["status"] == "checked" and f["amount"]["status"] == "unchecked"   # no barcode: confirm it


@pytest.mark.parametrize("response", [
    {"candidates": [{"content": {"role": "model", "parts": [{"text": "not json"}]}, "finish_reason": "STOP"}]},
    {"candidates": [{"content": {"parts": []}, "finish_reason": "SAFETY"}]},
])
def test_an_answer_that_does_not_fit_or_is_blocked_is_model_unavailable(app, response):
    r = read(app, Transport(response))
    assert r.status_code == 503 and r.json()["error"]["code"] == "model_unavailable"
    assert r.json()["error"]["retryable"] is False


def test_a_failed_request_is_model_unavailable_with_one_request_and_no_retry(app):
    transport = Transport(TimeoutError())
    r = read(app, transport)
    assert r.status_code == 503 and transport.requests == [MODEL]


@pytest.mark.parametrize("state", ["off", "budget"])
def test_the_model_switched_off_or_out_of_budget_sends_nothing(app, tmp_path, state):
    switch = tmp_path / "model-off"
    if state == "off":
        switch.touch()
    ledger = Ledger(tmp_path / "requests.jsonl", 0 if state == "budget" else 10, switch)
    transport = Transport(answer(printed("sample_1")))
    r = read(app, transport, ledger=ledger)
    assert r.status_code == 503 and transport.requests == []


def test_without_a_key_the_service_answers_model_unavailable(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/api/bill/read", json={"customer_id": "CUST00860", "language": "en", "sample_id": "sample_1"})
    assert r.status_code == 503 and r.json()["error"]["message"].startswith("The bill cannot be read")


@pytest.mark.parametrize("body", [
    {"sample_id": "../samples/sample_1"}, {"sample_id": "sample_1.png"}, {"sample_id": "https://example.com/a.png"},
    {"sample_id": "SAMPLE_1"}, {"sample_id": "sample_1", "image": "aGVsbG8="},
    {"sample_id": "sample_1", "url": "https://example.com/bill.png"}, {"sample_id": ""},
])
def test_a_crafted_sample_or_an_extra_field_never_calls_the_model(app, body):
    """Review of #250: only the repository's own samples reach the model; anything else is 400 with no request."""
    transport = Transport(answer(printed("sample_1")))
    app.state.bill_read_client = GeminiClient(MODEL, transport, cache="off", sleep=lambda s: None)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/api/bill/read", json={"customer_id": "CUST00860", "language": "en", **body})
    assert r.status_code == 400 and transport.requests == []


def test_a_multipart_upload_never_calls_the_model(app):
    transport = Transport(answer(printed("sample_1")))
    app.state.bill_read_client = GeminiClient(MODEL, transport, cache="off", sleep=lambda s: None)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/api/bill/read", data={"customer_id": "CUST00860", "language": "en", "sample_id": "sample_1"},
                   files={"file": ("bill.png", b"\x89PNG fake", "image/png")})
    assert r.status_code in (400, 415, 422) and transport.requests == []


@pytest.mark.parametrize("entry", ["[]", "{}", '{"response": 5}', "not json"])
def test_a_cache_entry_of_another_shape_is_a_miss_not_a_500(app, tmp_path, entry):
    """Review of #250: a broken entry costs one new request and answers normally."""
    first = Transport(answer(printed("sample_1")))
    assert read(app, first, cache_dir=tmp_path).status_code == 200
    for path in tmp_path.glob("*.json"):
        path.write_text(entry, encoding="utf-8")
    second = Transport(answer(printed("sample_1")))
    r = read(app, second, cache_dir=tmp_path)
    assert r.status_code == 200 and len(second.requests) == 1


def test_any_failure_of_the_read_is_503_with_the_class_name_only(app, monkeypatch, caplog):
    from core.app.api import bill_read

    def broken(*args, **kwargs):
        raise KeyError("FI0912345600001001")

    monkeypatch.setattr(bill_read, "read_bill", broken)
    r = read(app, Transport(answer(printed("sample_1"))))
    assert r.status_code == 503 and r.json()["error"]["code"] == "model_unavailable"
    assert any("KeyError" in rec.getMessage() for rec in caplog.records)
    assert not any("FI09" in rec.getMessage() for rec in caplog.records)


def test_a_cached_reading_is_served_while_the_model_may_not_be_used(app, tmp_path):
    """Decision D: the budget used up, the switch file or a pause: a cached reading costs no request and is
    served; only a miss answers 503."""
    assert read(app, Transport(answer(printed("sample_1"))), cache_dir=tmp_path).status_code == 200
    spent = Ledger(tmp_path / "ledger.jsonl", daily_cap=0)
    none = Transport(answer(printed("sample_1")))
    assert read(app, none, cache_dir=tmp_path, ledger=spent).status_code == 200 and none.requests == []
    miss = read(app, none, sample_id="sample_2", cache_dir=tmp_path, ledger=spent)
    assert miss.status_code == 503 and none.requests == []


def test_an_unknown_sample_or_customer_and_the_rate_window(app):
    transport = Transport(answer(printed("sample_1")))
    assert read(app, transport, sample_id="my_own_upload").status_code == 400
    assert read(app, transport, customer="CUST99999").status_code == 404
    with TestClient(app, raise_server_exceptions=False) as c:
        codes = [c.post("/api/bill/read", json={"customer_id": "CUST00860", "language": "en",
                                                "sample_id": "sample_1"}).status_code for _ in range(8)]
    assert 429 in codes


def test_the_reading_is_cached_by_the_image_hash_across_a_restart(app, tmp_path):
    """A second service (a new client on the same cache folder) reads the same sample with no request, and
    the budget counter does not move."""
    ledger_path = tmp_path / "requests.jsonl"
    first = Transport(answer(printed("sample_1")))
    assert read(app, first, cache_dir=tmp_path / "cache", ledger=Ledger(ledger_path, 10)).status_code == 200
    second = Transport(answer({"iban": "FI0000000000000000"}))
    fresh = create_app(Settings(_env_file=None, database_url=None))
    r = read(fresh, second, cache_dir=tmp_path / "cache", ledger=Ledger(ledger_path, 10))
    assert r.status_code == 200 and second.requests == [] and len(first.requests) == 1
    assert r.json()["fields"]["iban"]["value"] == TRUTH["sample_1"]["iban"]
    assert Ledger(ledger_path, 10).count() == 1
    assert not any(b"PNG" in p.read_bytes() for p in (tmp_path / "cache").rglob("*.json"))   # never the bytes


def test_an_obeyed_injection_on_a_barcode_bill_loses_to_the_barcode(app):
    """The image says to report another IBAN and amount and the model obeyed: the barcode still decides, the
    printed values are flagged, and the user confirms; nothing reaches an answer."""
    other_iban = TRUTH["sample_4"]["iban"]   # structurally valid, check digits pass
    r = read(app, Transport(answer(printed("sample_1", iban=other_iban, amount="9999.00"))))
    f = r.json()["fields"]
    assert f["iban"]["value"] == TRUTH["sample_1"]["iban"] and f["iban"]["status"] == "unchecked" and f["iban"]["note"]
    assert f["amount"]["value"] == "836.65" and r.json()["needs_confirmation"] is True


def test_an_obeyed_injection_without_a_barcode_is_a_field_to_confirm(app):
    """The residual risk, stated in docs/security/bill-reading.md: on a bill without a barcode, an injected
    IBAN with valid check digits is shown as checked by its check digit, and still needs the user's
    confirmation; an injected one that fails its check digit is unchecked with the reason."""
    valid = read(app, Transport(answer(printed("sample_4", iban=TRUTH["sample_1"]["iban"]))), sample_id="sample_4",
                 language="en").json()
    assert valid["fields"]["iban"]["value"] == TRUTH["sample_1"]["iban"] and valid["needs_confirmation"] is True
    bad_iban = TRUTH["sample_1"]["iban"][:-1] + ("0" if TRUTH["sample_1"]["iban"][-1] != "0" else "1")
    bad = read(create_app(Settings(_env_file=None, database_url=None)),
               Transport(answer(printed("sample_4", iban=bad_iban))), sample_id="sample_4", language="en").json()
    assert bad["fields"]["iban"] is None or bad["fields"]["iban"]["status"] == "unchecked"


def test_the_log_holds_counts_only(app, caplog):
    caplog.set_level(logging.INFO)
    read(app, Transport(answer(printed("sample_1"))))
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "fields found" in text
    for value in TRUTH["sample_1"].values():
        if value:
            assert value not in text
