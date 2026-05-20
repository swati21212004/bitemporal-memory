"""
Bitemporal AI Memory System — FastAPI application entry point.

Configures the application, middleware, routers, and the background decay
scheduler using the FastAPI *lifespan* protocol.

Run with::

    uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import health_router, router
from src.jobs.decay import start_decay_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown events.

    Startup:
        * Start the APScheduler decay recalculation job.

    Shutdown:
        * Gracefully stop the scheduler.
    """
    logger.info("Starting Bitemporal AI Memory System …")

    # Start the background decay scheduler.
    scheduler = start_decay_scheduler()
    scheduler.start()
    logger.info("Decay scheduler started")

    yield

    # Shutdown: stop the scheduler gracefully.
    scheduler.shutdown(wait=False)
    logger.info("Decay scheduler stopped — application shutting down")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Bitemporal AI Memory System",
    description=(
        "Production-grade persistent memory layer for AI assistants with "
        "semantic retrieval, temporal decay, bitemporal history, and "
        "behavioral guardrails."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins in development; restrict in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers.
app.include_router(health_router)
app.include_router(router)
