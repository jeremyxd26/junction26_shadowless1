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
    for name in ("DATABASE_URL", "AUDIT_API", "ASK_RATE_LIMIT_PER_MIN", "ASK_HARD_LIMIT_PER_MIN", "TRUSTED_PROXIES"):
        monkeypatch.delenv(name, raising=False)
    app = create_app(Settings(_env_file=None))

    def install(plans=None, drafts=None, data=None, per_minute=0, global_=0, per_customer=0, hard=0, hard_global=0):
        audit = AuditLog(tmp_path / "audit")
        model = ScriptedModel(plans=plans if plans is not None else [SPEND], drafts=drafts if drafts is not None else [GOOD])
        data = data or FakeData()
        pipeline = Pipeline(registry(), model, data, as_of=AS_OF, audit=audit)
        app.state.agent = Agent(pipeline=pipeline, data=data, audit=audit,
                                limits=AskLimits(per_minute, global_, per_customer, hard, hard_global))
        model.calls = []  # every plan and compose request the model receives (#232: none when it may not be used)
        plan, compose = model.plan, model.compose
        model.plan = lambda request: model.calls.append("plan") or plan(request)
        model.compose = lambda request: model.calls.append("compose") or compose(request)
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


def test_the_hard_ceiling_is_429_with_retry_after(client):
    client.install(plans=[SPEND, SPEND], drafts=[GOOD, GOOD], hard=1)
    assert client.post("/api/ask", json=BODY).status_code == 200
    r = client.post("/api/ask", json=BODY)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0 and r.json()["error"]["code"] == "rate_limited"


def test_a_used_up_model_window_answers_without_the_model(client):
    # Issue #232: one Wi-Fi address for a whole room. The second question is still answered, by the rule
    # planner and the template, with the "model unavailable" warning, and the model gets no request.
    agent = client.install(plans=[SPEND, SPEND], drafts=[GOOD, GOOD], per_minute=1)
    first = client.post("/api/ask", json=BODY)
    assert first.status_code == 200 and first.json()["outcome"] == "answered"
    calls = list(agent.pipeline.model.calls)
    second = client.post("/api/ask", json=BODY)
    assert second.status_code == 200
    assert second.json()["outcome"] != "answered" and "llm_unavailable" in second.json()["warnings"]
    assert agent.pipeline.model.calls == calls          # no model request for the second question


@pytest.mark.parametrize("window", [{"per_minute": 1}, {"global_": 1}, {"per_customer": 1}])
def test_every_model_window_degrades_and_never_refuses(client, window):
    agent = client.install(plans=[SPEND] * 3, drafts=[GOOD] * 3, **window)
    statuses = [client.post("/api/ask", json=BODY).status_code for _ in range(3)]
    assert statuses == [200, 200, 200]
    assert agent.pipeline.model.calls.count("plan") == 1


def test_a_burst_of_thirty_questions_from_one_address_all_answer(client):
    # The default windows: 10 a minute per address for the model, 120 before any 429.
    from core.agent.api import AskLimits as Limits

    agent = client.install(plans=[SPEND] * 30, drafts=[GOOD] * 30)
    agent.limits = Limits(10, 60, 10, 120, 600)
    statuses = [client.post("/api/ask", json=BODY).status_code for _ in range(30)]
    assert statuses == [200] * 30
    assert agent.pipeline.model.calls.count("plan") == 10


def test_a_new_customer_id_does_not_reset_the_address_ceiling(client):
    client.install(plans=[SPEND, SPEND], drafts=[GOOD, GOOD], hard=1)
    assert client.post("/api/ask", json=BODY).status_code == 200
    r = client.post("/api/ask", json={**BODY, "customer_id": "CUST00493"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


def test_a_spoofed_forwarded_header_from_a_non_proxy_peer_is_ignored(client):
    client.install(plans=[SPEND, SPEND], drafts=[GOOD, GOOD], hard=1)  # the test client is not a proxy
    assert client.post("/api/ask", json=BODY, headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 200
    assert client.post("/api/ask", json=BODY, headers={"X-Forwarded-For": "10.0.0.2"}).status_code == 429


def test_the_forwarded_address_counts_behind_a_trusted_proxy(client, monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "testclient")
    client.install(plans=[SPEND, SPEND, SPEND], drafts=[GOOD, GOOD, GOOD], hard=1)
    assert client.post("/api/ask", json=BODY, headers={"X-Forwarded-For": "6.6.6.6, 10.0.0.1"}).status_code == 200
    # the rightmost entry is the one the proxy wrote; a client-supplied left part cannot change it
    assert client.post("/api/ask", json=BODY, headers={"X-Forwarded-For": "7.7.7.7, 10.0.0.1"}).status_code == 429
    assert client.post("/api/ask", json=BODY, headers={"X-Forwarded-For": "10.0.0.2"}).status_code == 200


def test_the_global_ceiling(client):
    client.install(plans=[SPEND, SPEND], drafts=[GOOD, GOOD], hard_global=1)
    assert client.post("/api/ask", json=BODY).status_code == 200
    assert client.post("/api/ask", json={**BODY, "customer_id": "CUST00493"}).status_code == 429


def test_the_allowlist_and_the_body_checks_run_before_any_limit(client):
    client.install(plans=[SPEND], drafts=[GOOD], hard=1)
    assert client.post("/api/ask", json={**BODY, "message": ""}).status_code == 400            # not counted
    assert client.post("/api/ask", json={**BODY, "customer_id": "CUST00002"}).status_code == 404  # not counted
    assert client.post("/api/ask", json=BODY).status_code == 200
    assert client.post("/api/ask", json={**BODY, "customer_id": "CUST00002"}).status_code == 404  # still 404, not 429


def test_one_address_cannot_use_up_a_persona_for_everyone(client, monkeypatch):
    # Review of PR #104: the customer window is per address and customer, so the presenter still gets
    # an answer about the lead persona after another visitor has used up their own window for it.
    monkeypatch.setenv("TRUSTED_PROXIES", "testclient")
    client.install(plans=[SPEND, SPEND, SPEND], drafts=[GOOD, GOOD, GOOD], per_customer=1)
    first = client.post("/api/ask", json=BODY, headers={"X-Forwarded-For": "10.0.0.1"})
    again = client.post("/api/ask", json=BODY, headers={"X-Forwarded-For": "10.0.0.1"})
    other = client.post("/api/ask", json=BODY, headers={"X-Forwarded-For": "10.0.0.2"})
    assert [r.status_code for r in (first, again, other)] == [200, 200, 200]
    assert first.json()["outcome"] == other.json()["outcome"] == "answered"
    assert "llm_unavailable" in again.json()["warnings"]


def test_database_down_before_the_stream_is_503(client):
    client.install(data=FakeData(down=True))
    r = client.post("/api/ask", json=BODY, headers={"Accept": "text/event-stream"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "data_unavailable"


def test_the_audit_route_does_not_exist_when_it_is_off(client):
    # Issue #189: with AUDIT_API off the route is not registered, so /api/audit/<id> answers exactly
    # like any unknown path and nobody can tell that it exists.
    client.install()
    answer_id = client.post("/api/ask", json=BODY).json()["answer_id"]
    audit, unknown = client.get(f"/api/audit/{answer_id}"), client.get("/api/no-such-route")
    assert audit.status_code == unknown.status_code == 404
    assert audit.content == unknown.content and audit.headers["content-type"] == unknown.headers["content-type"]


def test_the_audit_route_with_audit_api_on(tmp_path, monkeypatch):
    for name in ("DATABASE_URL", "ASK_RATE_LIMIT_PER_MIN", "TRUSTED_PROXIES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AUDIT_API", "1")  # read once, when the app is created
    app = create_app(Settings(_env_file=None))
    audit = AuditLog(tmp_path / "audit")
    data = FakeData()
    app.state.agent = Agent(pipeline=Pipeline(registry(), ScriptedModel(plans=[SPEND], drafts=[GOOD]), data,
                                              as_of=AS_OF, audit=audit),
                            data=data, audit=audit, limits=AskLimits(0, 0, 0))
    with TestClient(app) as c:
        answer_id = c.post("/api/ask", json=BODY).json()["answer_id"]
        r = c.get(f"/api/audit/{answer_id}")
        assert r.status_code == 200
        record = r.json()
        assert record["answer_id"] == answer_id and record["outcome"] == "answered"
        assert [call["name"] for call in record["planner_turns"][0]["calls"]] == ["fake_spending", "finish"]
        assert c.get("/api/audit/ans_unknown").status_code == 404


@pytest.mark.parametrize("body,code", [
    ({**BODY, "message": "", "language": "fi"}, "invalid_request"),
    ({**BODY, "customer_id": "CUST00002", "language": "fi"}, "customer_not_found"),       # not a persona
    ({**BODY, "customer_id": "CUST00002", "message": "Paljonko kulutin viime kuussa?"}, "customer_not_found"),
])
def test_errors_are_in_the_language_of_the_request(client, body, code):
    # Review of PR #186: the body's language, else the question's detected language, as /api/whatif does.
    client.install()
    r = client.post("/api/ask", json=body)
    assert r.json()["error"]["code"] == code
    assert r.json()["error"]["message"] in ("Pyyntö ei ole kelvollinen.", "Asiakasta ei löytynyt.")


def test_a_finnish_rate_limit_answer(client):
    client.install(plans=[SPEND, SPEND], drafts=[GOOD, GOOD], hard=1)
    assert client.post("/api/ask", json={**BODY, "language": "fi"}).status_code == 200
    r = client.post("/api/ask", json={**BODY, "language": "fi"})
    assert r.status_code == 429 and r.json()["error"]["message"].startswith("Liian monta")
    assert int(r.headers["Retry-After"]) > 0 and r.json()["error"]["retryable"] is True


def test_the_real_wiring_without_a_database_answers_503(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit"))
    with TestClient(create_app(Settings(_env_file=None))) as c:
        r = c.post("/api/ask", json=BODY, headers={"Accept": "text/event-stream"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "data_unavailable"


def test_a_huge_auto_message_is_refused_before_any_detection(client, monkeypatch):
    # Review of PR #195: the length is checked first; the detector never sees more than MAX_MESSAGE.
    import time

    from core.agent import api as ask_api

    seen = []
    monkeypatch.setattr(ask_api.guard, "detect_language", lambda text: seen.append(len(text)) or "en")
    client.install()
    started = time.perf_counter()
    r = client.post("/api/ask", json={**BODY, "message": "x" * 3_000_000, "language": "auto"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    assert seen == [] and time.perf_counter() - started < 2.0
    client.post("/api/ask", json={**BODY, "message": "y" * ask_api.MAX_MESSAGE, "language": "auto"})
    assert seen and max(seen) <= ask_api.MAX_MESSAGE


def test_one_finnish_data_unavailable_text_before_and_inside_the_stream(client):
    from core.agent.orchestrator import error_envelope

    client.install(data=FakeData(down=True))
    r = client.post("/api/ask", json={**BODY, "language": "fi"})
    assert r.status_code == 503
    assert r.json()["error"]["message"] == error_envelope("data_unavailable", "fi")["message"]


def test_a_recognised_question_past_the_model_window_is_an_answer_with_the_warning(client):
    # The rule agreed for #232 and #244: the rules planned, the tools ran, the template wrote -> "answered",
    # with `llm_unavailable`, and no model request; a rules decline stays a refusal without the warning.
    from agent_fakes import fake_spending

    from core.agent.registry import ToolSpec
    from core.tools.models import Args

    class NoArgs(Args):
        pass

    agent = client.install(plans=[SPEND], drafts=[GOOD], per_minute=1)
    agent.pipeline.registry.register(ToolSpec("get_safe_to_spend", "safe to spend", NoArgs,
                                              lambda ctx, args: fake_spending(ctx, args), ("x", "x")))
    assert client.post("/api/ask", json=BODY).json()["outcome"] == "answered"       # the model's window
    calls = list(agent.pipeline.model.calls)
    r = client.post("/api/ask", json={**BODY, "message": "What can I safely spend this week?"})
    body = r.json()
    assert r.status_code == 200 and body["outcome"] == "answered" and "llm_unavailable" in body["warnings"]
    assert agent.pipeline.model.calls == calls
    refused = client.post("/api/ask", json={**BODY, "message": "Should I put my savings into tech stocks?"}).json()
    assert refused["outcome"] == "refused" and "llm_unavailable" not in refused["warnings"]


def test_the_answer_reads_the_labels_of_the_requests_viewer(client):
    # Issue #253: the viewer cookie's session key reaches every tool call's context, never the audit.
    from agent_fakes import fake_spending

    from core.agent.registry import ToolSpec
    from core.app.api import viewer as viewer_api

    seen = []

    def spy(ctx, args):
        seen.append(ctx.viewer)
        return fake_spending(ctx, args)

    agent = client.install(plans=[SPEND, SPEND], drafts=[GOOD, GOOD])
    agent.pipeline.registry.tools["fake_spending"] = ToolSpec("fake_spending", "t", agent.pipeline.registry.tools[
        "fake_spending"].args_model, spy, ("x", "x"))
    value = viewer_api.new_value()
    client.cookies.set(viewer_api.COOKIE, value, domain="testserver.local")
    answer_id = client.post("/api/ask", json=BODY).json()["answer_id"]
    client.cookies.clear()
    client.post("/api/ask", json=BODY)
    assert seen == [viewer_api.session_key(value), None]   # without a cookie: the shared state
    audit = agent.audit.find(answer_id)
    assert value not in json.dumps(audit) and viewer_api.session_key(value) not in json.dumps(audit)
