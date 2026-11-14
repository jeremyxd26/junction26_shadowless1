"""Contract endpoints backed by tools: personas, evidence, overview (#64) and what-if (#79).

`register(app)` adds the routers and the app-wide error envelope handlers (contracts/api.md section 4).
"""

from __future__ import annotations

from fastapi import FastAPI

from . import errors, evidence, labels, overview, personas, viewer, whatif


def register(app: FastAPI) -> None:
    errors.install(app)
    app.include_router(personas.router)
    app.include_router(evidence.router)
    app.include_router(overview.router)
    app.include_router(whatif.router)
    app.include_router(labels.router)  # POST /api/baskets/label (#68)
    app.include_router(viewer.router)  # GET /api/viewer/reset (#144)
