"""Background schedulers: notification sweeper + sync worker lifecycle."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.services import note_service
from app.workers.sync_worker import sync_worker

logger = get_logger("app.workers")


async def notification_sweep() -> None:
    """Detect unanswered conversations older than the threshold and notify."""
    try:
        async with session_scope() as db:
            created = await note_service.notify_unanswered_conversations(
                db, older_than_seconds=settings.notification_unanswered_after_seconds
            )
            await db.commit()
            if created:
                logger.info("notification sweep created %d notification(s)", created)
    except Exception:  # noqa: BLE001
        logger.exception("notification sweep failed")


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    if settings.run_sync_worker:
        scheduler.add_job(
            sync_worker.sync_all,
            IntervalTrigger(seconds=settings.eitaa_sync_interval),
            id="eitaa_sync",
            max_instances=1,
            coalesce=True,
        )
    if settings.run_notification_worker:
        scheduler.add_job(
            notification_sweep,
            IntervalTrigger(seconds=settings.notification_worker_interval),
            id="notification_sweep",
            max_instances=1,
            coalesce=True,
        )
    return scheduler
