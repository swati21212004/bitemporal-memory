"""
Bitemporal AI Memory System — Decay recalculation background job.

Periodically recalculates ``decay_score`` for every active memory using a
logarithmic decay function based on time since last access::

    decay_score = importance × 1 / (1 + ln(1 + age_in_days))

Decay behaviour:
    ├── Just accessed:  decay_score ≈ importance
    ├── 1 day old:      decay_score ≈ importance × 0.59
    ├── 7 days old:     decay_score ≈ importance × 0.34
    └── 30 days old:    decay_score ≈ importance × 0.23

The job is scheduled via APScheduler ``AsyncIOScheduler`` and runs at the
interval configured by ``settings.decay_job_interval_minutes``.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text

from src.config import settings
from src.database import engine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL statement
# ---------------------------------------------------------------------------

_DECAY_UPDATE_SQL = text(
    """
    UPDATE memories
    SET decay_score = importance * (
        1.0 / (1.0 + LN(1.0 + EXTRACT(EPOCH FROM (now() - last_accessed_at)) / 86400.0))
    )
    WHERE is_deleted = false
      AND superseded_at IS NULL;
    """
)


# ---------------------------------------------------------------------------
# Core job function
# ---------------------------------------------------------------------------

async def recalculate_decay_scores() -> None:
    """Recalculate decay scores for all active (non-deleted, non-superseded) memories.

    Uses a logarithmic decay function that smoothly decreases the score as a
    memory ages since its last access.  The function is monotonically
    decreasing but never reaches zero, which means even very old memories
    retain a non-zero score proportional to their importance.

    The function creates its own async connection from the shared engine so it
    is safe to call from APScheduler without an existing session context.
    """
    try:
        async with engine.begin() as conn:
            result = await conn.execute(_DECAY_UPDATE_SQL)
            logger.info(
                "Decay recalculation complete — %d memories updated",
                result.rowcount,
            )
    except Exception:
        logger.exception("Decay recalculation failed")
        raise


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------

def start_decay_scheduler() -> AsyncIOScheduler:
    """Create and configure an APScheduler ``AsyncIOScheduler`` for decay jobs.

    The scheduler is configured but **not started** — the caller is
    responsible for calling ``scheduler.start()``.

    Returns
    -------
    AsyncIOScheduler
        A scheduler instance with the decay recalculation job registered.
    """
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        recalculate_decay_scores,
        trigger="interval",
        minutes=settings.decay_job_interval_minutes,
        id="decay_recalculation",
        name="Recalculate memory decay scores",
        replace_existing=True,
    )
    logger.info(
        "Decay scheduler configured — job will run every %d minute(s)",
        settings.decay_job_interval_minutes,
    )
    return scheduler
