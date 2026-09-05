"""FastAPI application entry point.

Phase 1: health endpoint + Razorpay webhook ingestion.
Phase 2+: additional routers registered under /api.

See CLAUDE.md sections 9, 42, 50.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.analytics import router as analytics_router
from backend.api.recovery import router as recovery_router
from backend.api.transactions import router as transactions_router
from backend.api.webhooks import router as webhooks_router
from backend.db.database import (
    describe_database_url,
    get_engine,
    get_settings,
    init_db,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database on startup.

    For production we will swap ``init_db`` for Alembic migrations. We keep the
    simple call here so the hackathon demo boots without extra steps.
    """
    settings = get_settings()
    logger.info(
        "Starting RazorRecover (env=%s, db=%s)",
        settings.app_env,
        describe_database_url(settings.database_url),
    )
    init_db()
    yield
    logger.info("Shutting down RazorRecover")


app = FastAPI(
    title="RazorRecover",
    version="0.1.0",
    description="AI-powered revenue recovery for Razorpay (hackathon MVP).",
    lifespan=lifespan,
)

# CORS is permissive on purpose — the demo dashboard runs on a different port.
# Tighten before any real production exposure.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhooks_router)
app.include_router(transactions_router)
app.include_router(recovery_router)
app.include_router(analytics_router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Liveness probe. Reports DB connectivity."""
    db_status = "ok"
    try:
        with get_engine().connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception as exc:  # noqa: BLE001 — health endpoint must never raise
        db_status = f"error: {exc.__class__.__name__}"
    return {"status": "ok", "database": db_status}


__all__ = ["app"]
