"""Liveness and readiness checks."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .db import check_ready

router = APIRouter()


@router.get("/healthz")
async def healthz(request: Request) -> dict[str, str]:
    """The process is up. Never touches the database."""
    return {"status": "ok", "demo_today": request.app.state.settings.demo_today.isoformat()}


@router.get("/readyz")
def readyz(request: Request) -> JSONResponse:
    """The database answers `SELECT 1`. A plain `def`, so the blocking query runs in the thread pool."""
    reason = check_ready(request.app.state.pool, request.app.state.db_problem)
    if reason is None:
        return JSONResponse({"status": "ready"})
    return JSONResponse({"status": "unavailable", "reason": reason}, status_code=503)
