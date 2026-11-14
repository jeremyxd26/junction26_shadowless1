"""Application factory for the core service.

Run from the repository root:
    uvicorn core.app.main:create_app --factory --port 8000
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from core.agent.api import audit_api_enabled, audit_router
from core.agent.api import router as ask_router

from . import api, health, secret_mask
from .db import MALFORMED, NOT_SET, create_pool, valid_database_url
from .settings import Settings

log = logging.getLogger("uvicorn.error")

# Mask secret setting values in every log record of the process (#198), as early as the app module is
# imported: before the settings are validated, so even a start-up error cannot print a secret.
secret_mask.install()


def create_app(settings: Settings | None = None) -> FastAPI:
    secret_mask.install()   # again: the environment may have changed since the import (tests, reloads)
    settings = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = None
        app.state.db_problem = NOT_SET
        if settings.database_url is None:
            log.warning("DATABASE_URL is not set: the service runs without a database and /readyz returns 503")
        elif not valid_database_url(settings.database_url.get_secret_value()):
            app.state.db_problem = MALFORMED
            log.warning("DATABASE_URL is malformed: the service runs without a database and /readyz returns 503")
        else:
            pool = create_pool(settings.database_url.get_secret_value(), max_size=settings.db_pool_max)
            pool.open(wait=False)  # start even if the database is down; /readyz reports it
            log.info("database pool opened (max %d connections)", settings.db_pool_max)
        app.state.pool = pool
        try:
            yield
        finally:
            if pool is not None:
                await run_in_threadpool(pool.close)

    # The interactive docs and the schema are off unless API_DOCS=1 (local development only): the
    # deployed service does not describe itself to everyone, whatever the proxy forwards.
    docs = settings.api_docs
    app = FastAPI(title="shadowless1 core", version="0.1.0", lifespan=lifespan,
                  docs_url="/docs" if docs else None, redoc_url="/redoc" if docs else None,
                  openapi_url="/openapi.json" if docs else None)
    app.state.settings = settings
    app.state.pool = None
    app.state.db_problem = NOT_SET
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    api.register(app)  # /api/personas, /api/evidence, /api/overview and the error envelope (#64)
    app.include_router(ask_router)  # POST /api/ask (core/agent)
    if audit_api_enabled():  # GET /api/audit/{id} exists only for local eval runs (#189)
        app.include_router(audit_router)
    return app
