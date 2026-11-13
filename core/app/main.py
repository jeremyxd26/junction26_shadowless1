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

from . import health
from .db import MAX_CONNECTIONS, create_pool
from .settings import Settings

log = logging.getLogger("uvicorn.error")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = None
        if settings.database_url is not None:
            pool = create_pool(settings.database_url.get_secret_value())
            pool.open(wait=False)  # start even if the database is down; /readyz reports it
            log.info("database pool opened (max %d connections)", MAX_CONNECTIONS)
        else:
            log.warning("DATABASE_URL is not set: the service runs without a database and /readyz returns 503")
        app.state.pool = pool
        try:
            yield
        finally:
            if pool is not None:
                await run_in_threadpool(pool.close)

    app = FastAPI(title="shadowless1 core", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.pool = None
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    return app
