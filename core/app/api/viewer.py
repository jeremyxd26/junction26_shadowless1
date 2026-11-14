"""Viewer sessions (#144): every viewer of the public demo answers spike reviews in their own copy.

The first overview response without a valid cookie sets one:
- the value is random, has no personal data and is strictly functional;
- the cookie is HttpOnly, SameSite=Lax and Path=/, Secure by default (the VIEWER_COOKIE_SECURE
  setting turns that off for local development over http), and lives SESSION_TTL.
The app is served from the same origin, so it sends the cookie back without any change.

The server keeps only a SHA-256 of the value as the session key. The key selects the viewer's answer
rows (core.tools.reviews). It is never logged, never written into an evidence spec and never part of
a ref. Without a cookie the request sees the shared state: the eval set, the tests and cookie-less
API clients behave as before.

GET /api/viewer/reset gives the presenter a fresh state: it only issues a new cookie (nothing is
written or deleted) and sends the browser to the app. The old session's answers expire on their own.
"""

from __future__ import annotations

import hashlib
import re
import secrets

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from core.tools.reviews import SESSION_TTL

COOKIE = "sentti_viewer"
VALUE = re.compile(r"^[A-Za-z0-9_-]{32}$")
MAX_AGE_S = int(SESSION_TTL.total_seconds())

router = APIRouter()


def cookie_value(request: Request) -> str | None:
    """The viewer cookie if it is well formed, else None (a malformed one is replaced)."""
    value = request.cookies.get(COOKIE)
    return value if value and VALUE.fullmatch(value) else None


def new_value() -> str:
    return secrets.token_urlsafe(24)  # 32 characters, 192 random bits


def session_key(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def set_cookie(response: Response, value: str, secure: bool) -> None:
    response.set_cookie(COOKIE, value, max_age=MAX_AGE_S, path="/", secure=secure, httponly=True, samesite="lax")


def viewer_of(request: Request, response: Response, *, refresh: bool = False) -> str:
    """The viewer's session key. A request without a valid cookie gets a new one on `response`; its
    key has no answers yet, so it sees the shared state. With `refresh` (every label write) an existing
    cookie is set again with a new Max-Age, so an answer never outlives the cookie that owns it."""
    value = cookie_value(request)
    if value is None:
        value = new_value()
        set_cookie(response, value, request.app.state.settings.viewer_cookie_secure)
    elif refresh:
        set_cookie(response, value, request.app.state.settings.viewer_cookie_secure)
    return session_key(value)


def known_viewer(request: Request) -> str | None:
    """The viewer's session key from a valid cookie, or None; never sets a cookie. For a route that only
    reads labels and returns its own Response object (the /api/ask stream), where a cookie set on an
    injected Response would be dropped. None reads the shared state, which is exactly what a viewer
    without a cookie has: no answers."""
    value = cookie_value(request)
    return session_key(value) if value is not None else None


@router.get("/api/viewer/reset", include_in_schema=False)
def reset_viewer(request: Request) -> RedirectResponse:
    """A fresh viewer state for the presenter: a new cookie, nothing else. Not linked from the app."""
    response = RedirectResponse("/", status_code=303)
    set_cookie(response, new_value(), request.app.state.settings.viewer_cookie_secure)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response
