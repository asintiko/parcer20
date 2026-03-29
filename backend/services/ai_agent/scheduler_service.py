from __future__ import annotations

import logging
import os
from threading import Lock

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from celery import Celery

logger = logging.getLogger(__name__)


class AgentSchedulerService:
    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler | None = None
        self._lock = Lock()
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        self._celery = Celery("ai_agent_scheduler", broker=redis_url, backend=redis_url)

    def start(self) -> None:
        with self._lock:
            if self._scheduler and self._scheduler.running:
                return
            timezone = os.getenv("APP_TIMEZONE", "Asia/Tashkent")
            scheduler = AsyncIOScheduler(timezone=timezone)
            scheduler.add_job(
                self._enqueue_weekly_report,
                trigger=CronTrigger(day_of_week="mon", hour=12, minute=0, timezone=timezone),
                id="agent-weekly-report",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
            scheduler.add_job(
                self._enqueue_thread_cleanup,
                trigger=CronTrigger(hour=3, minute=15, timezone=timezone),
                id="agent-thread-cleanup",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
            scheduler.start()
            self._scheduler = scheduler
            logger.info("AI agent scheduler started: weekly report + thread cleanup (%s)", timezone)

    def stop(self) -> None:
        with self._lock:
            if not self._scheduler:
                return
            try:
                self._scheduler.shutdown(wait=False)
            finally:
                self._scheduler = None
                logger.info("AI agent scheduler stopped")

    def _enqueue_weekly_report(self) -> None:
        if str(os.getenv("AI_AGENT_WEEKLY_REPORTS_ENABLED", "true")).strip().lower() not in {"1", "true", "yes", "on"}:
            logger.info("AI weekly reports disabled by env flag")
            return
        try:
            self._celery.send_task("generate_weekly_agent_report")
            logger.info("Queued weekly AI agent report task")
        except Exception:
            logger.exception("Failed to enqueue weekly AI agent report")

    def _enqueue_thread_cleanup(self) -> None:
        try:
            self._celery.send_task("cleanup_ai_agent_threads")
            logger.info("Queued AI agent thread cleanup task")
        except Exception:
            logger.exception("Failed to enqueue AI agent thread cleanup")


_scheduler_service: AgentSchedulerService | None = None


def get_agent_scheduler_service() -> AgentSchedulerService:
    global _scheduler_service
    if _scheduler_service is None:
        _scheduler_service = AgentSchedulerService()
    return _scheduler_service
