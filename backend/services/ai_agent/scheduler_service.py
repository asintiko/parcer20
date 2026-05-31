from __future__ import annotations

import asyncio
import logging
import os
from threading import Lock
from typing import Any, Dict, List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from celery import Celery

logger = logging.getLogger(__name__)


def _flag_truthy(name: str, default: str = "true") -> bool:
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}


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
            scheduler.add_job(
                self._enqueue_run_watchdog,
                trigger=CronTrigger(minute="*/2", timezone=timezone),
                id="agent-run-watchdog",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
            scheduler.add_job(
                self._enqueue_receipt_watchdog,
                trigger=CronTrigger(minute="*/3", timezone=timezone),
                id="receipt-task-watchdog",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
            scheduler.add_job(
                self._enqueue_receipt_retention,
                trigger=CronTrigger(hour=4, minute=0, timezone=timezone),
                id="receipt-task-retention",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
            scheduler.add_job(
                self._run_monitored_chat_sync,
                trigger=CronTrigger(minute="*/5", timezone=timezone),
                id="agent-monitored-chat-sync",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
            scheduler.add_job(
                self._enqueue_weekly_publish,
                trigger=CronTrigger(day_of_week="sun", hour=18, minute=0, timezone=timezone),
                id="agent-weekly-publish",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
            scheduler.start()
            self._scheduler = scheduler
            logger.info(
                "AI agent scheduler started: weekly report + cleanup + watchdog + "
                "monitored sync + weekly publish (%s)",
                timezone,
            )
        # Seed built-in routines + default chat commands, then register
        # user-defined routines (all outside the lock — they do their own work).
        try:
            self.ensure_builtins()
        except Exception:
            logger.exception("Failed to seed built-in routines/commands on startup")
        try:
            self.sync_routines()
        except Exception:
            logger.exception("Failed to register agent routines on startup")

    def stop(self) -> None:
        with self._lock:
            if not self._scheduler:
                return
            try:
                # wait=True so an in-flight monitored-chat-sync job (which
                # writes tg_chat_messages rows) finishes cleanly instead of
                # being interrupted mid-batch.
                self._scheduler.shutdown(wait=True)
            finally:
                self._scheduler = None
                logger.info("AI agent scheduler stopped")

    def ensure_builtins(self) -> None:
        """Seed the built-in receipt-audit routine and default chat commands.

        Idempotent: each seeder checks for existing rows before inserting.
        """
        try:
            from database.connection import SessionLocal
            from services.ai_agent.routine_service import ensure_builtin_routines
            from services.ai_agent.chat_command_service import ensure_builtin_commands
            with SessionLocal() as db:
                ensure_builtin_routines(db)
                ensure_builtin_commands(db)
        except Exception:
            logger.exception("ensure_builtins failed")

    def sync_routines(self) -> None:
        """Re-register all enabled user routines as cron jobs.

        Idempotent: removes existing routine:* jobs and re-adds from DB. Called on
        startup and whenever a routine is created/updated/deleted via the API.
        """
        if not _flag_truthy("AGENT_ROUTINES_ENABLED", "true"):
            return
        scheduler = self._scheduler
        if scheduler is None or not scheduler.running:
            return
        timezone = os.getenv("APP_TIMEZONE", "Asia/Tashkent")
        # Drop existing dynamic routine jobs.
        for job in list(scheduler.get_jobs()):
            if str(job.id).startswith("routine:"):
                try:
                    scheduler.remove_job(job.id)
                except Exception:
                    logger.debug("failed to remove routine job %s", job.id, exc_info=True)
        # Load enabled routines from DB and register.
        try:
            from database.connection import SessionLocal
            from database.models import AgentRoutine
            with SessionLocal() as db:
                routines = db.query(AgentRoutine).filter(AgentRoutine.enabled.is_(True)).all()
                specs = [
                    (
                        str(r.id),
                        r.cron,
                        r.name,
                        getattr(r, "schedule_kind", None) or "recurring",
                        getattr(r, "run_at", None),
                    )
                    for r in routines
                ]
        except Exception:
            logger.exception("Failed to load routines for scheduling")
            return
        from datetime import datetime as _dt, timezone as _dt_tz
        from apscheduler.triggers.date import DateTrigger
        now = _dt.now(_dt_tz.utc)
        count = 0
        for routine_id, cron, name, schedule_kind, run_at in specs:
            if schedule_kind == "once":
                if run_at is None:
                    logger.warning("Routine %s (%s) is one-shot but has no run_at; skipped", routine_id, name)
                    continue
                fire_at = run_at
                if fire_at.tzinfo is None:
                    fire_at = fire_at.replace(tzinfo=_dt_tz.utc)
                if fire_at <= now:
                    logger.info("Routine %s (%s) one-shot run_at is in the past; skipped", routine_id, name)
                    continue
                trigger = DateTrigger(run_date=run_at, timezone=timezone)
            else:
                try:
                    trigger = CronTrigger.from_crontab(cron, timezone=timezone)
                except Exception:
                    logger.warning("Routine %s (%s) has invalid cron %r; skipped", routine_id, name, cron)
                    continue
            scheduler.add_job(
                self._run_routine_job,
                trigger=trigger,
                id=f"routine:{routine_id}",
                args=[routine_id],
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
            count += 1
        logger.info("Registered %s agent routine(s)", count)

    async def _run_routine_job(self, routine_id: str) -> None:
        """APScheduler entrypoint for one routine tick."""
        try:
            from uuid import UUID
            from services.ai_agent.routine_service import execute_routine
            await execute_routine(UUID(routine_id), trigger="schedule")
        except Exception:
            logger.exception("Routine job %s failed", routine_id)

    def _enqueue_weekly_report(self) -> None:
        if not _flag_truthy("AI_AGENT_WEEKLY_REPORTS_ENABLED", "true"):
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

    def _enqueue_run_watchdog(self) -> None:
        try:
            self._celery.send_task("agent_run_watchdog_sweep")
        except Exception:
            logger.exception("Failed to enqueue agent run watchdog")

    def _enqueue_receipt_watchdog(self) -> None:
        try:
            self._celery.send_task("receipt_task_watchdog_sweep")
        except Exception:
            logger.exception("Failed to enqueue receipt task watchdog")

    def _enqueue_receipt_retention(self) -> None:
        try:
            self._celery.send_task("receipt_task_retention_cleanup")
        except Exception:
            logger.exception("Failed to enqueue receipt task retention cleanup")

    def _enqueue_monitored_chat_sync(self) -> None:
        if not _flag_truthy("MONITORED_CHAT_SYNC_ENABLED", "true"):
            return
        try:
            self._celery.send_task("monitored_chat_sync_tick")
        except Exception:
            logger.exception("Failed to enqueue monitored chat sync")

    async def _run_monitored_chat_sync(self) -> None:
        """Run monitored-chat sync directly in the backend event loop.

        Why this exists (v1.4.10): the Celery worker container does not mount
        the shared `tdlib_data` volume, so its TDLib session is unauthenticated
        and `getChatHistory` always errors out. Backend has the authenticated
        session and a long-lived uvicorn loop, so calling sync_all_active_chats
        here actually persists new messages.

        Setting MONITORED_CHAT_SYNC_VIA_BACKEND=false reverts to the old
        Celery enqueue path (kept as a manual fallback).
        """
        if not _flag_truthy("MONITORED_CHAT_SYNC_ENABLED", "true"):
            return
        if not _flag_truthy("MONITORED_CHAT_SYNC_VIA_BACKEND", "true"):
            self._enqueue_monitored_chat_sync()
            return

        try:
            from services.monitored_chat_sync import sync_all_active_chats
            from services.telegram_tdlib_manager import (
                TDLibUnavailableError,
                get_tdlib_manager,
            )
        except ImportError:
            logger.exception("monitored_chat_sync imports failed; skipping tick")
            return

        manager = get_tdlib_manager()
        per_chat_timeout = max(5.0, float(os.getenv("MONITORED_CHAT_SYNC_FETCH_TIMEOUT_SECONDS", "60")))

        async def _fetch(chat_id: int, from_message_id: int, limit: int) -> List[Dict[str, Any]]:
            try:
                # First page of a tick (from_message_id == 0): warm the chat so
                # TDLib refreshes its cached last_message from the network. Without
                # this, monitored chats the desktop client never opens go stale and
                # getChatHistory(from=0) keeps returning the same old tail forever
                # (HUMO/NBU Card frozen since May — confirmed on prod 2026-05-29).
                if not from_message_id:
                    try:
                        await asyncio.wait_for(
                            manager.warm_up_chat(chat_id),
                            timeout=per_chat_timeout,
                        )
                    except Exception:
                        logger.debug("warm_up_chat skipped for chat %s", chat_id, exc_info=True)
                resp = await asyncio.wait_for(
                    manager.get_messages(
                        chat_id=chat_id,
                        from_message_id=from_message_id or 0,
                        limit=min(int(limit or 100), 100),
                    ),
                    timeout=per_chat_timeout,
                )
                return resp.get("items") or []
            except TDLibUnavailableError:
                logger.warning("TDLib unavailable; skipping chat %s", chat_id)
                return []
            except asyncio.TimeoutError:
                logger.warning(
                    "monitored_chat fetch timeout (%.1fs) for chat %s",
                    per_chat_timeout,
                    chat_id,
                )
                return []
            except Exception:
                logger.exception("monitored_chat fetch failed for chat %s", chat_id)
                return []

        try:
            result = await sync_all_active_chats(fetch_callable=_fetch)
        except Exception:
            logger.exception("monitored_chat_sync tick failed")
            return

        new_total = sum(int(r.get("new_rows", 0) or 0) for r in result if isinstance(r, dict))
        logger.info(
            "monitored_chat_sync tick (backend): chats=%s new_rows=%s",
            len(result),
            new_total,
        )

    def _enqueue_weekly_publish(self) -> None:
        if not _flag_truthy("AGENT_WEEKLY_PUBLISH_ENABLED", "true"):
            return
        try:
            self._celery.send_task("agent_weekly_publish")
            logger.info("Queued weekly publish task")
        except Exception:
            logger.exception("Failed to enqueue weekly publish")


_scheduler_service: AgentSchedulerService | None = None


def get_agent_scheduler_service() -> AgentSchedulerService:
    global _scheduler_service
    if _scheduler_service is None:
        _scheduler_service = AgentSchedulerService()
    return _scheduler_service
