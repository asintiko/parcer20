"""Background auto-monitoring of selected Telegram bot chats via TDLib."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import MonitoredBotChat, TgChatMessage, TgHistoryCursor, Transaction
from database.connection import SessionLocal
from services.receipt_processor import process_tdlib_message
from services.auth_bot_service import get_redis
from services.telegram_tdlib_manager import TelegramTDLibManager
from services import receipt_logger

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
        self._inflight: Dict[Tuple[int, int], float] = {}
        self._inflight_ttl_sec = max(60, int(os.getenv("TG_MONITOR_INFLIGHT_TTL_SEC", "300")))
        self._dedupe_ttl_sec = max(60, int(os.getenv("TG_MONITOR_DEDUPE_TTL_SEC", "3600")))
        self._catchup_max_batches = max(0, int(os.getenv("TG_MONITOR_CATCHUP_MAX_BATCHES", "0")))
        raw_catchup_max_seconds = int(os.getenv("TG_MONITOR_CATCHUP_MAX_SECONDS", "0"))
        self._catchup_max_seconds = 0 if raw_catchup_max_seconds <= 0 else max(5, raw_catchup_max_seconds)

    def _prune_inflight(self) -> None:
        now = time.monotonic()
        stale = [key for key, expires_at in self._inflight.items() if expires_at <= now]
        for key in stale:
            self._inflight.pop(key, None)

    async def _reserve_recent_message(self, chat_id: int, message_id: int) -> Optional[bool]:
        """
        Redis fast dedupe.
        Returns:
        - True  -> reserved (not seen recently)
        - False -> already seen recently
        - None  -> Redis unavailable, caller should fallback to DB check
        """
        key = f"tg:seen:{int(chat_id)}:{int(message_id)}"
        try:
            redis = await get_redis()
            created = await redis.set(key, "1", ex=self._dedupe_ttl_sec, nx=True)
            return bool(created)
        except Exception:
            return None

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
        doc_mime = str(doc.get("mime_type") or "").lower()
        if doc_mime == "application/pdf" or doc_mime.startswith("image/"):
            return True
        photo = message.get("photo") or {}
        if photo.get("file_id"):
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
                raw_doc_mime = str((doc_obj or {}).get("mime_type") or "").lower()
                if raw_doc_mime == "application/pdf" or raw_doc_mime.startswith("image/"):
                    return True
            elif content_type == "messagePhoto":
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

    def _persist_to_history(self, chat_id: int, message: Dict) -> None:
        """Save a new real-time message to tg_chat_messages if the chat has been synced."""
        message_id = message.get("id")
        if not message_id:
            return
        try:
            with self.session_factory() as db:
                # Only persist if chat was previously synced (cursor exists)
                cursor = db.get(TgHistoryCursor, int(chat_id))
                if cursor is None:
                    return
                # Check for duplicates
                existing = (
                    db.query(TgChatMessage.id)
                    .filter(TgChatMessage.chat_id == int(chat_id), TgChatMessage.message_id == int(message_id))
                    .first()
                )
                if existing:
                    return

                from datetime import datetime as _dt
                msg_date = None
                raw_ts = message.get("date")
                if raw_ts is not None:
                    try:
                        msg_date = _dt.utcfromtimestamp(int(raw_ts))
                    except Exception:
                        pass

                # Extract text from message
                text = (message.get("text") or "").strip()
                if not text:
                    content = message.get("content") or {}
                    ct = content.get("@type", "")
                    if ct == "messageText":
                        text = (content.get("text") or {}).get("text") or ""
                    elif ct == "messageDocument":
                        text = (content.get("caption") or {}).get("text") or ""
                    elif ct == "messagePhoto":
                        text = (content.get("caption") or {}).get("text") or ""

                sender = message.get("sender_id") or {}
                sender_id = None
                if isinstance(sender, dict):
                    for key in ("user_id", "chat_id"):
                        val = sender.get(key)
                        if val is not None:
                            try:
                                sender_id = int(val)
                            except Exception:
                                pass
                            break

                row = TgChatMessage(
                    chat_id=int(chat_id),
                    message_id=int(message_id),
                    message_date=msg_date,
                    is_outgoing=bool(message.get("is_outgoing", False)),
                    sender_id=sender_id,
                    text=text,
                    raw_json=json.dumps(message, ensure_ascii=False),
                )
                db.add(row)
                db.commit()
        except Exception:
            logger.debug("Failed to persist realtime message %s:%s to history", chat_id, message_id, exc_info=True)

    async def _handle_new_message(self, message: Dict) -> None:
        chat_id = message.get("chat_id")
        message_id = message.get("id")
        if not chat_id or not message_id:
            return

        # Persist to chat history if this chat has been synced
        self._persist_to_history(int(chat_id), message)

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
        await self._enqueue(chat_id, message_id)

    async def _enqueue(self, chat_id: int, message_id: int) -> None:
        """Add message to processing queue with duplicate check."""
        key = (chat_id, message_id)
        self._prune_inflight()
        if key in self._inflight:
            return

        redis_reservation = await self._reserve_recent_message(chat_id, message_id)
        if redis_reservation is False:
            return

        if redis_reservation is None:
            # Redis unavailable: fallback to strict DB duplicate check.
            try:
                with self.session_factory() as db:
                    existing = db.query(Transaction).filter(
                        Transaction.source_chat_id == int(chat_id),
                        Transaction.source_message_id == int(message_id)
                    ).first()
                    if existing:
                        logger.debug(
                            "Message %s:%s already processed (transaction %s), skipping",
                            chat_id, message_id, existing.id
                        )
                        return
            except Exception:
                logger.exception("Duplicate check failed for %s:%s, proceeding anyway", chat_id, message_id)

        self._inflight[key] = time.monotonic() + self._inflight_ttl_sec
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
                self._inflight.pop(key, None)
                self.queue.task_done()

    def _emit_receipt_log(
        self,
        *,
        chat_id: int,
        chat_title: Optional[str],
        message_id: int,
        result: Any,
        last_error: Optional[str],
        permanent: bool,
        duration_seconds: Optional[float] = None,
    ) -> None:
        """Map a realtime processing outcome to a receipt-log channel event.

        Best-effort; the caller wraps this in try/except. Covers: created success,
        duplicate, and permanent parse failure. Transient errors are skipped (they
        retry, so logging them would spam the channel with noise that self-heals).
        Each log_* call is internally a no-op when the channel is not configured.
        """
        # Failure (only permanent — transient will retry and log on its final outcome).
        if result is None:
            if permanent and last_error:
                receipt_logger.log_failed(
                    task_id=None,
                    chat_id=chat_id,
                    chat_title=chat_title,
                    message_id=message_id,
                    rejection_reason=last_error,
                    error_summary=last_error,
                    duration_seconds=duration_seconds,
                )
            return

        tx = getattr(result, "transaction", None)
        if tx is None:
            return

        if getattr(result, "duplicate", False):
            receipt_logger.log_duplicate(
                task_id=None,
                transaction_id=getattr(tx, "id", None),
                duplicate_of_id=getattr(tx, "id", None),
                chat_id=chat_id,
                chat_title=chat_title,
                message_id=message_id,
                amount=getattr(tx, "amount", None),
                currency=getattr(tx, "currency", None) or "UZS",
                transaction_date=getattr(tx, "transaction_date", None),
                operator=getattr(tx, "operator_raw", None),
            )
            return

        if getattr(result, "created", False):
            parsing = getattr(result, "parsing", None)
            receipt_logger.log_processed(
                task_id=None,
                transaction_id=getattr(tx, "id", None),
                chat_id=chat_id,
                chat_title=chat_title,
                message_id=message_id,
                amount=getattr(tx, "amount", None),
                currency=getattr(tx, "currency", None) or "UZS",
                transaction_date=getattr(tx, "transaction_date", None),
                operator=getattr(tx, "operator_raw", None),
                receiver_name=getattr(tx, "receiver_name", None),
                receiver_card=getattr(tx, "receiver_card", None),
                sender_card=getattr(tx, "card_last_4", None),
                parsing_method=getattr(tx, "parsing_method", None) or getattr(parsing, "method", None),
                parsing_confidence=getattr(tx, "parsing_confidence", None) or getattr(parsing, "confidence", None),
                is_p2p=bool(getattr(tx, "is_p2p", False)),
                duration_seconds=duration_seconds,
                ocr_preview=getattr(tx, "raw_message", None),
            )

    async def _process_single(self, chat_id: int, message_id: int) -> None:
        with self.session_factory() as db:
            monitored = db.get(MonitoredBotChat, chat_id)
            if not monitored or not monitored.enabled:
                return

            chat_title = getattr(monitored, "chat_title", None)
            started_at = time.monotonic()
            success = False
            last_error: Optional[str] = None
            result = None
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

            # Emit a receipt-log channel event. Must never break processing:
            # the whole block is best-effort and swallows its own errors.
            try:
                self._emit_receipt_log(
                    chat_id=chat_id,
                    chat_title=chat_title,
                    message_id=message_id,
                    result=result,
                    last_error=last_error,
                    permanent=success and last_error is not None,
                    duration_seconds=time.monotonic() - started_at,
                )
            except Exception:
                logger.debug("receipt-log emit failed for %s:%s", chat_id, message_id, exc_info=True)

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
        batches = 0
        started_at = time.monotonic()
        limit_hit_reason: Optional[str] = None

        while True:
            if self._catchup_max_batches and batches >= self._catchup_max_batches:
                logger.warning(
                    "Catch-up batch limit hit for chat %s (batches=%s, last_processed_id=%s)",
                    chat_id,
                    batches,
                    last_processed_id,
                )
                limit_hit_reason = "batch_limit"
                break
            if self._catchup_max_seconds and (time.monotonic() - started_at) >= self._catchup_max_seconds:
                logger.warning(
                    "Catch-up time budget exceeded for chat %s (seconds=%s, queued=%s)",
                    chat_id,
                    self._catchup_max_seconds,
                    len(collected),
                )
                limit_hit_reason = "time_limit"
                break

            resp = await self.manager.get_messages(chat_id=chat_id, limit=batch, from_message_id=from_message_id)
            batches += 1
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
            if oldest_id <= last_processed_id:
                break
            if int(oldest_id) == int(from_message_id):
                logger.warning(
                    "Catch-up pagination stalled for chat %s at message_id=%s; stopping to avoid loop",
                    chat_id,
                    oldest_id,
                )
                break
            from_message_id = oldest_id

        if not collected:
            return

        for mid in sorted(set(collected)):
            if mid > last_processed_id:
                await self._enqueue(chat_id, mid)

        logger.info(
            "Catch-up queued %s messages for chat %s (last_processed_id=%s)",
            len(collected),
            chat_id,
            last_processed_id,
        )
        if limit_hit_reason:
            logger.warning(
                "Catch-up stopped early for chat %s due to %s; consider disabling limits to avoid backlog lag",
                chat_id,
                limit_hit_reason,
            )

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
        workers = max(1, int(os.getenv("TG_MONITOR_WORKERS", "2")))
        catchup_interval = max(15, int(os.getenv("TG_MONITOR_CATCHUP_INTERVAL_SEC", "45")))
        _service = TgAutoMonitorService(
            manager=manager,
            session_factory=session_factory,
            workers=workers,
            catchup_interval_sec=catchup_interval,
        )
    return _service


def get_auto_monitor_service() -> Optional[TgAutoMonitorService]:
    return _service
