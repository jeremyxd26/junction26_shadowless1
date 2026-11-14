"""scripts/demo_check.py (issue #130) against a standard-library stub of the service: every stage
passes, one wrong number fails, a missing route is NOT DEPLOYED, and the spike review is left pending
even when a step fails. No database, no network beyond 127.0.0.1."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("demo_check", ROOT / "scripts" / "demo_check.py")
demo_check = importlib.util.module_from_spec(_spec)
sys.modules["demo_check"] = demo_check  # dataclasses look the module up while it loads
_spec.loader.exec_module(demo_check)

LEAD = demo_check.LEAD
TX_REF = "txr_abcdefghijklmnop"


def num(value, ref="ev_000000000001"):
    return {"value": value, "unit": "eur", "evidence_ref": ref, "display": f"€{value}"}


class Stub:
    """The service's demo path, with switches for the failure cases."""

    def __init__(self, saving=45.91, off=(), hero_after_needed=180.26):
        self.saving = saving
        self.off = set(off)
        self.hero_after_needed = hero_after_needed
        self.state = "pending"
        self.paths: list[str] = []

    def overview(self):
        pending = self.state == "pending"
        items = [{"key": "regular_essentials", "amount": num(1889.04, "ev_000000000002")},
                 {"key": "unexpected_necessities", "amount": num(341.08 if pending else 521.15, "ev_000000000003")},
                 {"key": "everyday_spending", "amount": num(600.41, "ev_000000000004")}]
        if pending:
            items.append({"key": "unclassified", "amount": num(180.07, "ev_000000000005")})
        reviews = [{"type": "review", "tx_ref": TX_REF, "amount": num(1080.42, "ev_000000000006"),
                    "current_basket": {"key": "unclassified"}}] if pending else []
        hero_value = 221.58 if pending else self.hero_after_needed
        return {"customer_id": LEAD, "hero": {"type": "metric", "primary": num(hero_value, "ev_000000000001")},
                "cards": [{"type": "breakdown", "evidence_ref": "ev_000000000007", "items": items}],
                "reviews": reviews}

    def handle(self, method, path, query, body):
        self.paths.append(f"{method} {path}")
        not_found = (404, {"error": {"code": "not_found", "message": "No such route."}})
        if path == "/healthz":
            return 200, {"status": "ok"}
        if path == "/readyz":
            return 200, {"status": "ready"}
        if path == "/api/personas":
            return 200, {"personas": [{"customer_id": c} for c in demo_check.ref("personas")]}
        if path == f"/api/overview/{LEAD}":
            return 200, self.overview()
        if path.startswith("/api/overview/"):
            return 404, {"error": {"code": "customer_not_found", "message": "We couldn't find this customer."}}
        if path.startswith("/api/evidence/"):
            if query.get("customer_id") == [LEAD]:
                return 200, {"evidence_ref": path.rsplit("/", 1)[1], "rows": []}
            return 403, {"error": {"code": "evidence_forbidden", "message": "Not yours."}}
        if path == "/api/whatif" and method == "POST":
            return 200, {"saving_per_month": num(self.saving)}
        if path == "/api/baskets/label" and method == "POST" and "label" not in self.off:
            if body.get("tx_ref") != TX_REF:
                return 404, {"error": {"code": "tx_ref_not_found", "message": "No such purchase."}}
            if body.get("basket") is None:
                self.state = "pending"
                return 200, {"review_state": "pending", "changes": []}
            self.state = "answered"
            return 200, {"review_state": "answered",
                         "changes": [{"key": "safe_to_spend", "before": num(221.58), "after": num(180.26)}]}
        if path == "/api/ask" and method == "POST" and "ask" not in self.off:
            return 200, {"outcome": "answered", "warnings": [], "cited": ["n1"],
                         "numbers": {"n1": num(180.26, "ev_000000000008")}}
        return not_found


@pytest.fixture
def serve():
    servers = []

    def start(stub: Stub) -> str:
        class Handler(BaseHTTPRequestHandler):
            def _reply(self, method):
                url = urlparse(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                status, payload = stub.handle(method, url.path, parse_qs(url.query), body)
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self._reply("GET")

            def do_POST(self):
                self._reply("POST")

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def run(url, *args):
    lines: list[str] = []
    code = demo_check.main(["--base-url", url, *args], out=lines.append)
    return code, lines


def line(lines, name):
    return next(row for row in lines if row.startswith(name))


def test_every_stage_passes(serve):
    stub = Stub()
    code, lines = run(serve(stub))
    assert code == 0, "\n".join(lines)
    stages = [row for row in lines if not row.startswith("--")]
    assert len(stages) == 11 and all(" PASS " in row for row in stages), "\n".join(lines)
    assert stub.state == "pending"
    assert stub.paths.count("POST /api/ask") == 4


def test_one_wrong_number_fails_with_expected_and_received(serve):
    code, lines = run(serve(Stub(saving=45.92)), "--no-ask")
    row = line(lines, "what-if")
    assert code == 1 and " FAIL " in row and "expected 45.91" in row and "got 45.92" in row
    assert sum(" FAIL " in row for row in lines) == 1


def test_a_stage_that_is_not_deployed(serve):
    stub = Stub(off={"label", "ask"})
    stub.state = "answered"  # no review card: the route is probed with an unknown tx_ref, nothing written
    url = serve(stub)
    code, lines = run(url)
    assert code == 0
    assert " NOT DEPLOYED " in line(lines, "spike review")
    assert all(" NOT DEPLOYED " in row for row in lines if row.startswith("ask:"))
    assert run(url, "--require-all")[0] == 1


def test_the_review_is_left_pending_when_a_step_fails(serve):
    stub = Stub(hero_after_needed=999.0)
    code, lines = run(serve(stub), "--no-ask")
    row = line(lines, "spike review")
    assert code == 1 and " FAIL " in row and "hero after Needed" in row
    assert stub.state == "pending"
    assert stub.paths.count("POST /api/baskets/label") == 2  # the answer and its undo


def test_no_ask_and_ask_limit(serve):
    stub = Stub()
    url = serve(stub)
    code, lines = run(url, "--no-ask")
    assert code == 0 and "POST /api/ask" not in stub.paths
    assert all(" SKIPPED " in row for row in lines if row.startswith("ask:"))
    code, lines = run(url, "--ask-limit", "1")
    assert code == 0 and stub.paths.count("POST /api/ask") == 1
