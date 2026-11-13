"""Viewer sessions and the label rate limit without a database (#144)."""

from __future__ import annotations

import hashlib
from http.cookies import SimpleCookie

import pytest
from fastapi.testclient import TestClient

from core.app.api import viewer
from core.app.api.schemas import ErrorResponse
from core.app.main import create_app
from core.app.ratelimit import SlidingWindowLimiter
from core.app.settings import Settings


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


# ---- the limiter --------------------------------------------------------------------------------------

def test_sliding_window_admits_up_to_the_limit_then_says_when_to_retry():
    clock = Clock()
    lim = SlidingWindowLimiter({"address": 3}, window_s=60, clock=clock)
    assert [lim.allow({"address": "a"})[0] for _ in range(3)] == [True, True, True]
    clock.t += 20
    assert lim.allow({"address": "a"}) == (False, 40)                 # the first hit leaves at +60
    assert lim.allow({"address": "b"}) == (True, 0)                   # another address is not affected
    clock.t += 40
    assert lim.allow({"address": "a"}) == (True, 0)                   # the window slid


def test_every_limit_must_allow_and_only_admitted_requests_count():
    clock = Clock()
    lim = SlidingWindowLimiter({"address": 10, "customer": 2}, window_s=60, clock=clock)
    assert lim.allow({"address": "a", "customer": "CUST00860"})[0]
    assert lim.allow({"address": "b", "customer": "CUST00860"})[0]
    assert not lim.allow({"address": "c", "customer": "CUST00860"})[0]   # many addresses, one customer
    assert lim.allow({"address": "c", "customer": "CUST00493"})[0]       # the refusal did not count for "c"


def test_zero_turns_a_limit_off_and_memory_stays_bounded():
    clock = Clock()
    lim = SlidingWindowLimiter({"address": 0, "customer": 5}, window_s=60, clock=clock)
    for i in range(2000):
        clock.t += 1
        assert lim.allow({"address": "a", "customer": f"C{i}"})[0]
    assert lim.size() <= 61                                            # old keys are dropped


# ---- the cookie ---------------------------------------------------------------------------------------

def test_cookie_value_and_session_key():
    values = {viewer.new_value() for _ in range(100)}
    assert len(values) == 100 and all(viewer.VALUE.fullmatch(v) for v in values)
    v = next(iter(values))
    assert viewer.session_key(v) == hashlib.sha256(v.encode()).hexdigest() != v


def client(**settings) -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, database_url=None, **settings)),
                      base_url="https://testserver", raise_server_exceptions=False)


def cookie_of(response) -> SimpleCookie:
    jar = SimpleCookie()
    jar.load(response.headers["set-cookie"])
    return jar


def test_reset_link_only_issues_a_new_cookie():
    with client() as c:
        r = c.get("/api/viewer/reset", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/")
    assert r.headers["cache-control"] == "no-store" and "noindex" in r.headers["x-robots-tag"]
    morsel = cookie_of(r)[viewer.COOKIE]
    assert viewer.VALUE.fullmatch(morsel.value)
    assert (morsel["httponly"], morsel["secure"], morsel["samesite"], morsel["path"], morsel["max-age"]) == (
        True, True, "lax", "/", "7200")


def test_secure_can_be_turned_off_for_local_http():
    with client(viewer_cookie_secure=False) as c:
        r = c.get("/api/viewer/reset", follow_redirects=False)
    assert not cookie_of(r)[viewer.COOKIE]["secure"]


# ---- the label rate limit -------------------------------------------------------------------------------

def label(c, customer="CUST00860", **headers):
    return c.post("/api/baskets/label", headers=headers,
                  json={"customer_id": customer, "tx_ref": "txr_0000000000000000",
                        "basket": "unexpected_necessities", "language": "fi"})


def test_label_writes_are_limited_per_address_with_the_contract_envelope():
    with client(label_rate_limit_per_min=2, label_rate_limit_customer_per_min=0) as c:
        first = [label(c).status_code for _ in range(2)]               # admitted (no database: 503)
        third = label(c)
        other_customer = label(c, customer="CUST00493")
    assert first == [503, 503]
    assert third.status_code == 429 and int(third.headers["retry-after"]) >= 1
    body = ErrorResponse.model_validate(third.json()).error
    assert (body.code, body.retryable) == ("rate_limited", True)
    assert body.message == "Liian monta pyyntöä. Yritä pian uudelleen."   # the request's language
    assert other_customer.status_code == 429                           # the address limit holds


def test_label_writes_are_limited_per_customer():
    with client(label_rate_limit_per_min=0, label_rate_limit_customer_per_min=1) as c:
        assert label(c).status_code == 503
        assert label(c).status_code == 429
        assert label(c, customer="CUST00493").status_code == 503


class FakeRequest:
    def __init__(self, cookies: dict[str, str]) -> None:
        self.cookies = cookies


@pytest.mark.parametrize("bad", ["", "short", "x" * 31 + "!", "../" * 11, "x" * 33])
def test_a_malformed_cookie_counts_as_none(bad):
    assert viewer.cookie_value(FakeRequest({viewer.COOKIE: bad})) is None   # viewer_of then issues a new one
    good = viewer.new_value()
    assert viewer.cookie_value(FakeRequest({viewer.COOKIE: good})) == good
