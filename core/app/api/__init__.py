"""Contract endpoints backed by tools (issue #64): personas, evidence, overview.

`register(app)` adds the routers and the app-wide error envelope handlers (contracts/api.md section 4).
"""

from __future__ import annotations

from fastapi import FastAPI

from . import errors, evidence, overview, personas


def register(app: FastAPI) -> None:
    errors.install(app)
    app.include_router(personas.router)
    app.include_router(evidence.router)
    app.include_router(overview.router)
