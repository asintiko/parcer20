"""Background auto-monitoring of selected Telegram bot chats via TDLib."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Dict, List, Optional, Set, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import MonitoredBotChat
from database.connection import SessionLocal
from services.receipt_processor import process_tdlib_message
from services.telegram_tdlib_manager import TelegramTDLibManager

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class TgAutoMonitorService:
    """Consumes TDLib updates, catches up missed messages, and processes receipts."""

    def __init__(
        self,
        manager: TelegramTDLibManager,
        session_factory: Callable[[], Session],
        workers: int = 2,
        catchup_interval_sec: int = 45,
    ) -> None:
        self.manager = manager
        self.session_factory = session_factory
        self.workers = max(1, workers)
        self.catchup_interval_sec = max(15, catchup_interval_sec)
        self.queue: asyncio.Queue[Tuple[int, int]] = asyncio.Queue()
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._inflight: Set[Tuple[int, int]] = set()

    async def start(self) -> None:
        if self._running:
            return
        await self.manager.start()
        self.manager.add_new_message_handler(self._handle_new_message)
        self._running = True
        # Workers
        for idx in range(self.workers):
            self._tasks.append(asyncio.create_task(self._worker(idx), name=f"tg-auto-worker-{idx}"))
        # Catch-up loop
        self._tasks.append(asyncio.create_task(self._catchup_loop(), name="tg-auto-catchup"))
        logger.info("TG auto monitor started with %s workers", self.workers)

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        self._inflight.clear()

    async def _handle_new_message(self, message: Dict) -> None:
        chat_id = message.get("chat_id")
        message_id = message.get("id")
        if not chat_id or not message_id:
            return
        try:
            with self.session_factory() as db:
                monitored = db.get(MonitoredBotChat, chat_id)
                if not monitored or not monitored.enabled:
                    return
        except Exception:
            logger.exception("Monitor check failed for chat %s", chat_id)
            return
        self._enqueue(chat_id, message_id)

    def _enqueue(self, chat_id: int, message_id: int) -> None:
        key = (chat_id, message_id)
        if key in self._inflight:
            return
        self._inflight.add(key)
        self.queue.put_nowait(key)

    async def _worker(self, idx: int) -> None:
        while True:
            chat_id, message_id = await self.queue.get()
            key = (chat_id, message_id)
            try:
                await self._process_single(chat_id, message_id)
            except Exception:  # noqa: BLE001
                logger.exception("Worker %s failed on %s:%s", idx, chat_id, message_id)
            finally:
                self._inflight.discard(key)
                self.queue.task_done()

    async def _process_single(self, chat_id: int, message_id: int) -> None:
        with self.session_factory() as db:
            monitored = db.get(MonitoredBotChat, chat_id)
            if not monitored or not monitored.enabled:
                return
            last_error: Optional[str] = None
            try:
                await process_tdlib_message(chat_id=chat_id, message_id=message_id, force=False, db=db, manager=self.manager)
                db.commit()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                last_error = str(exc)
                logger.warning("Processing failed for %s:%s -> %s", chat_id, message_id, last_error)
            finally:
                db.query(MonitoredBotChat).filter(MonitoredBotChat.chat_id == chat_id).update(
                    {
                        MonitoredBotChat.last_processed_message_id: func.greatest(
                            func.coalesce(MonitoredBotChat.last_processed_message_id, 0),
                            message_id,
                        ),
                        MonitoredBotChat.last_error: last_error,
                    },
                    synchronize_session=False,
                )
                db.commit()

    async def _catchup_loop(self) -> None:
        while self._running:
            try:
                await self._run_catchup_once()
            except Exception:  # noqa: BLE001
                logger.exception("Catch-up iteration failed")
            await asyncio.sleep(self.catchup_interval_sec)

    async def _run_catchup_once(self) -> None:
        with self.session_factory() as db:
            chats = db.query(MonitoredBotChat).filter(MonitoredBotChat.enabled.is_(True)).all()
        for chat in chats:
            await self._catchup_chat(chat.chat_id, chat.last_processed_message_id or 0)

    async def _catchup_chat(self, chat_id: int, last_processed_id: int) -> None:
        batch = 100
        from_message_id = 0
        collected: List[int] = []
        max_batches = 50
        for _ in range(max_batches):
            resp = await self.manager.get_messages(chat_id=chat_id, limit=batch, from_message_id=from_message_id)
            items = resp.get("items") or []
            if not items:
                break
            ids = [m.get("id") for m in items if m and m.get("id")]
            if not ids:
                break
            for mid in ids:
                if mid > last_processed_id:
                    collected.append(mid)
            oldest_id = min(ids)
            if oldest_id <= last_processed_id or len(items) < batch:
                break
            from_message_id = oldest_id
        if not collected:
            return
        for mid in sorted(set(collected)):
            if mid > last_processed_id:
                self._enqueue(chat_id, mid)

    def status(self) -> Dict[str, int | bool]:
        return {
            "running": self._running,
            "queue_size": self.queue.qsize(),
            "workers": self.workers,
        }


_service: Optional[TgAutoMonitorService] = None


def init_auto_monitor_service(manager: TelegramTDLibManager, session_factory: Callable[[], Session] = SessionLocal) -> TgAutoMonitorService:
    global _service
    if _service is None:
        _service = TgAutoMonitorService(manager=manager, session_factory=session_factory)
    return _service


def get_auto_monitor_service() -> Optional[TgAutoMonitorService]:
    return _service
