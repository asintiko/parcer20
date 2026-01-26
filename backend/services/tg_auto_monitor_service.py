"""Background auto-monitoring of selected Telegram bot chats via TDLib."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import MonitoredBotChat, Transaction
from database.connection import SessionLocal
from services.receipt_processor import process_tdlib_message
from services.telegram_tdlib_manager import TelegramTDLibManager

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEFAULT_RECEIPT_KEYWORDS = {
    "uzs",
    "usd",
    "humo",
    "uzcard",
    "oplata",
    "оплата",
    "пополнение",
    "balans",
    "баланс",
    "receipt",
    "chek",
    "чек",
    "transfer",
    "перевод",
    "payme",
    "click",
    "apelsin",
    "terminal",
}

MIN_RECEIPT_TEXT_LENGTH = 20
GROUP_CHAT_TYPES = {"group", "supergroup", "channel"}


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

    def _should_process_message(
        self,
        monitor: MonitoredBotChat,
        message: Dict[str, Any]
    ) -> bool:
        """
        Check if a message passes the PDF/keyword filters before enqueueing.
        """
        # Formatted messages (from TDLib manager) already include "document"/"text"
        doc = message.get("document") or {}
        if doc.get("mime_type") == "application/pdf":
            return True

        text = (message.get("text") or "").strip()

        # Fallback for raw TDLib updates (should rarely occur)
        if not text and "content" in message:
            content = message.get("content") or {}
            content_type = content.get("@type", "")
            if content_type == "messageText":
                text = content.get("text", {}).get("text", "") or ""
            elif content_type == "messageDocument":
                caption = content.get("caption", {}).get("text", "") or ""
                text = caption
                doc_obj = content.get("document") or {}
                if (doc_obj or {}).get("mime_type") == "application/pdf":
                    return True

        if not text:
            return False

        text_lower = text.lower()
        chat_id_val = message.get("chat_id")
        is_group_chat = (monitor.chat_type or "private") in GROUP_CHAT_TYPES or (chat_id_val is not None and chat_id_val < 0)

        default_hit = len(text_lower) >= MIN_RECEIPT_TEXT_LENGTH and any(
            kw in text_lower for kw in DEFAULT_RECEIPT_KEYWORDS
        )
        if is_group_chat and not default_hit:
            # Groups can be noisy; require default receipt keywords or PDF
            return False

        keywords = self._parse_keywords(monitor.filter_keywords)
        has_keyword = any(kw.lower() in text_lower for kw in keywords) if keywords else False

        if monitor.filter_mode == "blacklist":
            if not keywords:
                return default_hit or not is_group_chat
            return not has_keyword

        if monitor.filter_mode == "whitelist":
            return has_keyword and (default_hit or not is_group_chat)

        # 'all' mode: allow if either default keywords triggered (for groups) or custom keywords match
        if not keywords:
            return True if (default_hit or not is_group_chat) else False
        return has_keyword

    def _parse_keywords(self, raw_value: Optional[str]) -> List[str]:
        """Safely parse keywords from JSON or comma-separated strings."""
        if not raw_value:
            return []
        try:
            payload = json.loads(raw_value)
            if isinstance(payload, list):
                return [str(item).strip() for item in payload if str(item).strip()]
            if isinstance(payload, str):
                cleaned = payload.strip()
                return [cleaned] if cleaned else []
        except Exception:
            pass
        return [part.strip() for part in raw_value.split(",") if part.strip()]

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

                # Check filters
                if not self._should_process_message(monitored, message):
                    logger.debug("Message %s:%s filtered out by %s", chat_id, message_id, monitored.filter_mode)
                    return
        except Exception:
            logger.exception("Monitor check failed for chat %s", chat_id)
            return
        self._enqueue(chat_id, message_id)

    def _enqueue(self, chat_id: int, message_id: int) -> None:
        """Add message to processing queue with duplicate check."""
        key = (chat_id, message_id)
        if key in self._inflight:
            return

        # Check if already processed in database (strict duplicate check)
        try:
            with self.session_factory() as db:
                existing = db.query(Transaction).filter(
                    Transaction.source_chat_id == int(chat_id),
                    Transaction.source_message_id == int(message_id)
                ).first()
                if existing:
                    logger.debug("Message %s:%s already processed (transaction %s), skipping",
                                chat_id, message_id, existing.id)
                    return
        except Exception:
            logger.exception("Duplicate check failed for %s:%s, proceeding anyway", chat_id, message_id)

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

            success = False
            last_error: Optional[str] = None
            try:
                result = await process_tdlib_message(
                    chat_id=chat_id,
                    message_id=message_id,
                    force=False,
                    db=db,
                    manager=self.manager
                )
                db.commit()
                success = True
                # Mark as success even for duplicates (they were processed before)
                if result.duplicate:
                    logger.debug("Message %s:%s is duplicate", chat_id, message_id)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                last_error = str(exc)
                # Check if error is due to parsing failure (not retriable) vs transient error
                error_str = str(exc).lower()
                is_permanent_error = any(x in error_str for x in [
                    "cannot parse", "empty message", "unsupported",
                    "missing", "invalid"
                ])
                if is_permanent_error:
                    # Mark as processed to avoid retrying parsing errors forever
                    success = True
                    logger.warning("Permanent parsing error for %s:%s -> %s", chat_id, message_id, last_error)
                else:
                    logger.warning("Transient error for %s:%s -> %s (will retry)", chat_id, message_id, last_error)

            # Only update last_processed_message_id on success
            # This prevents skipping messages that failed due to transient errors
            if success:
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
            else:
                # Only update last_error for transient failures
                db.query(MonitoredBotChat).filter(MonitoredBotChat.chat_id == chat_id).update(
                    {MonitoredBotChat.last_error: last_error},
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
        """
        Catch up on missed messages for a chat, applying filters.

        Args:
            chat_id: Telegram chat ID
            last_processed_id: Last message ID that was processed
        """
        # Get monitor settings for filtering
        with self.session_factory() as db:
            monitor = db.get(MonitoredBotChat, chat_id)
            if not monitor or not monitor.enabled:
                return

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

            # Filter messages and collect IDs that should be processed
            for msg in items:
                mid = msg.get("id")
                if not mid or mid <= last_processed_id:
                    continue

                # Check filters before adding to queue
                if self._should_process_message(monitor, msg):
                    collected.append(mid)
                else:
                    logger.debug("Catchup: Message %s:%s filtered out by %s", chat_id, mid, monitor.filter_mode)

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
