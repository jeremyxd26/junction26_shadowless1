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


OFF = {"label_rate_limit_per_min": 0, "label_rate_limit_customer_per_min": 0, "label_rate_limit_viewer_per_min": 0}


@pytest.fixture
def proxied(monkeypatch):
    """The test client is the trusted proxy, so X-Forwarded-For names the client's address (as behind
    Caddy); this is how other addresses are simulated."""
    monkeypatch.setenv("TRUSTED_PROXIES", "testclient")


def test_label_writes_are_limited_per_address_with_the_contract_envelope():
    with client(**{**OFF, "label_rate_limit_per_min": 2}) as c:
        first = [label(c).status_code for _ in range(2)]               # admitted (no database: 503)
        third = label(c)
        other_customer = label(c, customer="CUST00493")
    assert first == [503, 503]
    assert third.status_code == 429 and int(third.headers["retry-after"]) >= 1
    body = ErrorResponse.model_validate(third.json()).error
    assert (body.code, body.retryable) == ("rate_limited", True)
    assert body.message == "Liian monta pyyntöä. Yritä pian uudelleen."   # the request's language
    assert other_customer.status_code == 429                           # the address limit holds


def test_the_customer_window_is_per_address(proxied):
    """No window is shared by all viewers of a customer: one address cannot block another (review of #144)."""
    with client(**{**OFF, "label_rate_limit_customer_per_min": 1}) as c:
        assert label(c, **{"X-Forwarded-For": "198.51.100.1"}).status_code == 503
        assert label(c, **{"X-Forwarded-For": "198.51.100.1"}).status_code == 429
        assert label(c, "CUST00493", **{"X-Forwarded-For": "198.51.100.1"}).status_code == 503
        assert label(c, **{"X-Forwarded-For": "198.51.100.2"}).status_code == 503   # another address


def test_a_flood_from_other_addresses_never_blocks_a_fresh_presenter(proxied):
    with client() as c:                                                 # the default limits
        flood = []
        for n in range(1, 4):                                           # three addresses past their own limit
            for _ in range(130):
                flood.append(label(c, **{"X-Forwarded-For": f"203.0.113.{n}"}).status_code)
        presenter = label(c, **{"X-Forwarded-For": "192.0.2.10"})
    assert 429 in flood                                                 # the flooders are limited ...
    assert presenter.status_code == 503                                 # ... the presenter reaches the database step


def test_a_room_behind_one_address_is_not_limited_by_the_address(proxied):
    """Everyone on a venue's Wi-Fi is one client address (r-sec): twenty viewers tapping twice each in the
    same minute all get through with the default limits; only a single viewer is held to 10 a minute."""
    with client() as c:
        statuses = []
        for _ in range(20):
            c.cookies.clear()
            c.cookies.set(viewer.COOKIE, viewer.new_value(), domain="testserver.local")
            statuses += [label(c, **{"X-Forwarded-For": "198.51.100.7"}).status_code for _ in range(2)]
    assert statuses == [503] * 40                                       # no 429 for anyone in the room


def test_label_writes_are_limited_per_viewer():
    value = viewer.new_value()
    with client(**{**OFF, "label_rate_limit_viewer_per_min": 1}) as c:
        c.cookies.set(viewer.COOKIE, value, domain="testserver.local")
        assert label(c).status_code == 503
        assert label(c).status_code == 429                              # the same viewer
        c.cookies.clear()
        assert label(c).status_code == 503                              # another viewer


def test_a_subset_of_limits_and_check_then_record():
    clock = Clock()
    lim = SlidingWindowLimiter({"address": 1, "viewer": 1}, window_s=60, clock=clock)
    assert lim.allow({"viewer": "v1"}) == (True, 0)                     # the address limit is not named
    assert lim.allow({"address": "a"}) == (True, 0)
    assert lim.check({"address": "b"}) == (True, 0) and lim.check({"address": "b"}) == (True, 0)  # no count
    lim.record({"address": "b"})
    assert lim.check({"address": "b"})[0] is False


class FakeRequest:
    def __init__(self, cookies: dict[str, str]) -> None:
        self.cookies = cookies


@pytest.mark.parametrize("bad", ["", "short", "x" * 31 + "!", "../" * 11, "x" * 33])
def test_a_malformed_cookie_counts_as_none(bad):
    assert viewer.cookie_value(FakeRequest({viewer.COOKIE: bad})) is None   # viewer_of then issues a new one
    good = viewer.new_value()
    assert viewer.cookie_value(FakeRequest({viewer.COOKIE: good})) == good
