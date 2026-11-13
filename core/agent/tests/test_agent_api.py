"""POST /api/ask and GET /api/audit/{id} on the FastAPI app, with the scripted model. No database."""

from __future__ import annotations

import json

import pytest
from agent_fakes import AS_OF, FakeData, registry
from fastapi.testclient import TestClient

from core.agent.api import Agent, AskLimits
from core.agent.audit import AuditLog
from core.agent.model import FunctionCall, ScriptedModel
from core.agent.orchestrator import Pipeline
from core.app.main import create_app
from core.app.settings import Settings

SPEND = [FunctionCall("fake_spending", {}), FunctionCall("finish")]
GOOD = {"language": "en", "text": "In August 2026 you spent {{n1}}. That was {{n2}} visits.", "cited": ["n1", "n2"],
        "lesson_key": None}
BODY = {"customer_id": "CUST00860", "conversation_id": None, "message": "Restaurants in August 2026?", "language": "auto"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    for name in ("DATABASE_URL", "AUDIT_API", "ASK_RATE_LIMIT_PER_MIN", "TRUSTED_PROXIES"):
        monkeypatch.delenv(name, raising=False)
    app = create_app(Settings(_env_file=None))

    def install(plans=None, drafts=None, data=None, per_minute=0, global_=0, per_customer=0):
        audit = AuditLog(tmp_path / "audit")
        model = ScriptedModel(plans=plans if plans is not None else [SPEND], drafts=drafts if drafts is not None else [GOOD])
        data = data or FakeData()
        pipeline = Pipeline(registry(), model, data, as_of=AS_OF, audit=audit)
        app.state.agent = Agent(pipeline=pipeline, data=data, audit=audit,
                                limits=AskLimits(per_minute, global_, per_customer))
        return app.state.agent

    with TestClient(app) as c:
        c.install = install
        yield c


def sse_events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = [line for line in block.splitlines() if not line.startswith(":")]
        if lines:
            event = lines[0].removeprefix("event: ")
            out.append((event, json.loads(lines[1].removeprefix("data: "))))
    return out


def test_json_answer(client):
    client.install()
    r = client.post("/api/ask", json=BODY, headers={"Accept": "application/json"})
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "answered" and body["as_of"] == "2026-09-30" and body["language"] == "en"
    assert set(body["numbers"]) == {"n1", "n2"} and body["numbers"]["n1"]["display"] == "€147.64"
    assert body["text_rendered"] == "In August 2026 you spent €147.64. That was 10 visits."
    assert len(body["cards"]) == 1 and body["answer_id"].startswith("ans_")


def test_event_stream_in_contract_order(client):
    client.install()
    r = client.post("/api/ask", json=BODY, headers={"Accept": "text/event-stream"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = sse_events(r.text)
    names = [e for e, _ in events]
    assert names[0] == "meta" and names[-1] == "done" and names.count("done") == 1
    assert names.index("card") < names.index("numbers") < names.index("delta")
    done = events[-1][1]
    assert "".join(p["text"] for e, p in events if e == "delta") == done["text"]
    sent = {k for e, p in events if e == "numbers" for k in p["numbers"]}
    assert sent == set(done["cited"])


@pytest.mark.parametrize("body", [
    {**BODY, "message": ""}, {**BODY, "message": "x" * 501}, {**BODY, "language": "sv"},
    {**BODY, "extra": 1}, {"message": "hi"},
])
def test_bad_requests_are_plain_400(client, body):
    client.install()
    r = client.post("/api/ask", json=body, headers={"Accept": "text/event-stream"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"


def test_unknown_customer_is_404(client):
    client.install()
    r = client.post("/api/ask", json={**BODY, "customer_id": "CUST09999"}, headers={"Accept": "text/event-stream"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "customer_not_found"


def test_rate_limit_is_429_with_retry_after(client):
    client.install(plans=[SPEND, SPEND], drafts=[GOOD, GOOD], per_minute=1)
    assert client.post("/api/ask", json=BODY).status_code == 200
    r = client.post("/api/ask", json=BODY)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def test_a_new_customer_id_does_not_reset_the_address_limit(client):
    client.install(plans=[SPEND, SPEND], drafts=[GOOD, GOOD], per_minute=1)
    assert client.post("/api/ask", json=BODY).status_code == 200
    r = client.post("/api/ask", json={**BODY, "customer_id": "CUST00493"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


def test_a_spoofed_forwarded_header_from_a_non_proxy_peer_is_ignored(client):
    client.install(plans=[SPEND, SPEND], drafts=[GOOD, GOOD], per_minute=1)  # the test client is not a proxy
    assert client.post("/api/ask", json=BODY, headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 200
    assert client.post("/api/ask", json=BODY, headers={"X-Forwarded-For": "10.0.0.2"}).status_code == 429


def test_the_forwarded_address_counts_behind_a_trusted_proxy(client, monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "testclient")
    client.install(plans=[SPEND, SPEND, SPEND], drafts=[GOOD, GOOD, GOOD], per_minute=1)
    assert client.post("/api/ask", json=BODY, headers={"X-Forwarded-For": "6.6.6.6, 10.0.0.1"}).status_code == 200
    # the rightmost entry is the one the proxy wrote; a client-supplied left part cannot change it
    assert client.post("/api/ask", json=BODY, headers={"X-Forwarded-For": "7.7.7.7, 10.0.0.1"}).status_code == 429
    assert client.post("/api/ask", json=BODY, headers={"X-Forwarded-For": "10.0.0.2"}).status_code == 200


def test_the_global_cap_and_the_customer_limit(client):
    client.install(plans=[SPEND, SPEND], drafts=[GOOD, GOOD], global_=1)
    assert client.post("/api/ask", json=BODY).status_code == 200
    assert client.post("/api/ask", json={**BODY, "customer_id": "CUST00493"}).status_code == 429
    client.install(plans=[SPEND, SPEND], drafts=[GOOD, GOOD], per_customer=1)
    assert client.post("/api/ask", json=BODY).status_code == 200
    assert client.post("/api/ask", json=BODY).status_code == 429


def test_database_down_before_the_stream_is_503(client):
    client.install(data=FakeData(down=True))
    r = client.post("/api/ask", json=BODY, headers={"Accept": "text/event-stream"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "data_unavailable"


def test_audit_endpoint_is_off_by_default(client, monkeypatch):
    client.install()
    answer_id = client.post("/api/ask", json=BODY).json()["answer_id"]
    assert client.get(f"/api/audit/{answer_id}").status_code == 404
    monkeypatch.setenv("AUDIT_API", "1")
    r = client.get(f"/api/audit/{answer_id}")
    assert r.status_code == 200
    record = r.json()
    assert record["answer_id"] == answer_id and record["outcome"] == "answered"
    assert [c["name"] for c in record["planner_turns"][0]["calls"]] == ["fake_spending", "finish"]
    assert client.get("/api/audit/ans_unknown").status_code == 404


def test_the_real_wiring_without_a_database_answers_503(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit"))
    with TestClient(create_app(Settings(_env_file=None))) as c:
        r = c.post("/api/ask", json=BODY, headers={"Accept": "text/event-stream"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "data_unavailable"
