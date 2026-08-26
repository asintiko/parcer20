"""Background auto-monitoring of selected Telegram bot chats via TDLib."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from database.models import (
    MonitoredBotChat,
    ReceiptProcessingTask,
    TgChatMessage,
    TgHistoryCursor,
    Transaction,
)
from database.connection import SessionLocal
from services.auth_bot_service import get_redis
from services.message_utils import (
    build_task_data_from_message,
    is_metadata_only_chat,
    metadata_only_chat_ids,
    parse_message_datetime,
    receipt_min_datetime,
)
from services.telegram_tdlib_manager import TelegramTDLibManager
from workers.celery_worker import queue_receipt_task

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
        queue_size = max(1, int(os.getenv("TG_MONITOR_QUEUE_SIZE", "500")))
        self.queue: asyncio.Queue[Tuple[int, int, asyncio.Future[bool]]] = asyncio.Queue(
            maxsize=queue_size
        )
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._inflight: Dict[Tuple[int, int], asyncio.Future[bool]] = {}
        self._completed_grace_sec = max(
            1, int(os.getenv("TG_MONITOR_COMPLETED_GRACE_SEC", "5"))
        )
        self._dedupe_ttl_sec = max(30, int(os.getenv("TG_MONITOR_DEDUPE_TTL_SEC", "300")))
        self._lease_wait_sec = max(
            0.1, float(os.getenv("TG_MONITOR_LEASE_WAIT_SEC", "2"))
        )
        self._catchup_max_batches = max(
            1, int(os.getenv("TG_MONITOR_CATCHUP_MAX_BATCHES", "20"))
        )
        self._catchup_max_seconds = max(
            5, int(os.getenv("TG_MONITOR_CATCHUP_MAX_SECONDS", "30"))
        )
        self._max_durable_backlog = max(
            100, int(os.getenv("TG_MONITOR_MAX_DURABLE_BACKLOG", "1000"))
        )

    async def _reserve_recent_message(self, chat_id: int, message_id: int) -> Optional[str]:
        """
        Redis fast dedupe.
        Returns:
        - token -> reserved by this process
        - ""    -> another process currently owns the short enqueue lease
        - None  -> Redis unavailable, caller should fallback to DB check
        """
        key = f"tg:seen:{int(chat_id)}:{int(message_id)}"
        token = secrets.token_urlsafe(18)
        try:
            redis = await get_redis()
            created = await redis.set(key, token, ex=self._dedupe_ttl_sec, nx=True)
            return token if created else ""
        except Exception:
            return None

    async def _release_recent_message(
        self, chat_id: int, message_id: int, token: Optional[str]
    ) -> None:
        """Release only our enqueue lease; stale Redis keys must never block retries."""
        if not token:
            return
        key = f"tg:seen:{int(chat_id)}:{int(message_id)}"
        script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
          return redis.call('del', KEYS[1])
        end
        return 0
        """
        try:
            redis = await get_redis()
            await redis.eval(script, 1, key, token)
        except Exception:
            logger.debug("Failed to release enqueue lease for %s:%s", chat_id, message_id)

    def _message_is_durable(self, chat_id: int, message_id: int) -> bool:
        """Use the database, not Redis, as the processing source of truth."""
        if is_metadata_only_chat(chat_id):
            return True
        with self.session_factory() as db:
            transaction = (
                db.query(Transaction.id)
                .filter(
                    Transaction.source_chat_id == int(chat_id),
                    Transaction.source_message_id == int(message_id),
                )
                .first()
            )
            if transaction:
                return True
            task = (
                db.query(ReceiptProcessingTask.status)
                .filter(
                    ReceiptProcessingTask.chat_id == int(chat_id),
                    ReceiptProcessingTask.message_id == int(message_id),
                )
                .first()
            )
            return bool(task and task[0] in {"queued", "processing", "retry", "done"})

    async def _wait_for_durable_owner(self, chat_id: int, message_id: int) -> bool:
        """Give the current Redis lease owner time to commit its outbox row."""
        deadline = time.monotonic() + self._lease_wait_sec
        while time.monotonic() < deadline:
            if await asyncio.to_thread(
                self._message_is_durable, chat_id, message_id
            ):
                return True
            await asyncio.sleep(0.05)
        return False

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
        for future in self._inflight.values():
            if not future.done():
                future.cancel()
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
        if is_metadata_only_chat(chat_id):
            return
        message_datetime = parse_message_datetime(message.get("date"))
        if message_datetime is None or message_datetime < receipt_min_datetime():
            logger.info(
                "Skipping Telegram message outside receipt date window: %s:%s date=%s",
                chat_id,
                message_id,
                message.get("date"),
            )
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
        await self._enqueue(chat_id, message_id)

    async def _enqueue(self, chat_id: int, message_id: int) -> bool:
        """Persistently enqueue a message, applying bounded local backpressure.

        Completion means that ``queue_receipt_task`` has recorded the task in the
        database. A process-local queue entry or a Redis lease is never treated as
        durable progress.
        """
        key = (int(chat_id), int(message_id))
        pending = self._inflight.get(key)
        if pending is not None:
            return await asyncio.shield(pending)

        if await asyncio.to_thread(self._message_is_durable, *key):
            return True

        reservation = await self._reserve_recent_message(*key)
        if reservation == "":
            # Redis is only a short cross-process lease. If its owner did not
            # create a DB task, a stale reservation must not suppress retry.
            if await self._wait_for_durable_owner(*key):
                return True

        # Close the race between the first DB read and lease acquisition. The
        # competing coroutine/process may have committed its outbox row meanwhile.
        if await asyncio.to_thread(self._message_is_durable, *key):
            await self._release_recent_message(*key, reservation)
            return True

        # The DB/Redis checks yield control; another local coroutine may have
        # installed the authoritative future while they were running.
        pending = self._inflight.get(key)
        if pending is not None:
            await self._release_recent_message(*key, reservation)
            return await asyncio.shield(pending)

        future = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            await self.queue.put((key[0], key[1], future))
            return await asyncio.shield(future)
        except BaseException:
            if self._inflight.get(key) is future:
                self._inflight.pop(key, None)
            if not future.done():
                future.cancel()
            raise
        finally:
            await self._release_recent_message(*key, reservation)

    async def _worker(self, idx: int) -> None:
        while True:
            chat_id, message_id, future = await self.queue.get()
            key = (chat_id, message_id)
            try:
                durable = await self._process_single(chat_id, message_id)
                if not future.done():
                    future.set_result(durable)
            except Exception:  # noqa: BLE001
                logger.exception("Worker %s failed on %s:%s", idx, chat_id, message_id)
                if not future.done():
                    future.set_result(False)
            finally:
                if self._inflight.get(key) is future:
                    durable = (
                        future.done()
                        and not future.cancelled()
                        and future.exception() is None
                        and future.result() is True
                    )
                    if durable:
                        asyncio.get_running_loop().call_later(
                            self._completed_grace_sec,
                            self._forget_inflight,
                            key,
                            future,
                        )
                    else:
                        self._inflight.pop(key, None)
                self.queue.task_done()

    def _forget_inflight(
        self, key: Tuple[int, int], future: asyncio.Future[bool]
    ) -> None:
        if self._inflight.get(key) is future:
            self._inflight.pop(key, None)

    async def _process_single(self, chat_id: int, message_id: int) -> bool:
        """Fetch message metadata and hand CPU/network-heavy parsing to Celery."""
        if is_metadata_only_chat(chat_id):
            return True
        message = await self.manager.get_message(chat_id=chat_id, message_id=message_id)
        if not message:
            raise RuntimeError(f"TDLib message unavailable: {chat_id}:{message_id}")

        task_data = build_task_data_from_message(chat_id, message_id, message)
        try:
            await asyncio.to_thread(queue_receipt_task, task_data, False)
        except ValueError:
            # An existing source transaction is durable completion.
            return True
        return await asyncio.to_thread(self._message_is_durable, chat_id, message_id)

    async def _catchup_loop(self) -> None:
        while self._running:
            try:
                await self._run_catchup_once()
            except Exception:  # noqa: BLE001
                logger.exception("Catch-up iteration failed")
            await asyncio.sleep(self.catchup_interval_sec)

    async def _run_catchup_once(self) -> None:
        blocked_ids = metadata_only_chat_ids()
        with self.session_factory() as db:
            backlog = (
                db.query(ReceiptProcessingTask.id)
                .filter(ReceiptProcessingTask.status.in_({"queued", "processing", "retry"}))
                .count()
            )
            if backlog >= self._max_durable_backlog:
                logger.warning(
                    "Catch-up paused by durable backlog guard (%s >= %s)",
                    backlog,
                    self._max_durable_backlog,
                )
                return
            query = db.query(MonitoredBotChat.chat_id).filter(MonitoredBotChat.enabled.is_(True))
            if blocked_ids:
                query = query.filter(~MonitoredBotChat.chat_id.in_(blocked_ids))
            chats = [int(chat_id) for (chat_id,) in query.all()]
        for chat_id in chats:
            await self._catchup_chat(chat_id)

    def _durable_backlog_size(self) -> int:
        with self.session_factory() as db:
            return int(
                db.query(ReceiptProcessingTask.id)
                .filter(ReceiptProcessingTask.status.in_({"queued", "processing", "retry"}))
                .count()
            )

    def _save_scan_progress(
        self,
        chat_id: int,
        *,
        from_message_id: Optional[int],
        target_message_id: Optional[int],
        completed_cursor: Optional[int] = None,
        error: Optional[str] = None,
    ) -> None:
        with self.session_factory() as db:
            monitor = db.get(MonitoredBotChat, int(chat_id))
            if not monitor or not monitor.enabled:
                return
            if completed_cursor is not None:
                monitor.scan_cursor_message_id = max(
                    int(monitor.scan_cursor_message_id or 0), int(completed_cursor)
                )
                monitor.scan_backfill_from_message_id = None
                monitor.scan_backfill_target_message_id = None
            else:
                monitor.scan_backfill_from_message_id = from_message_id
                monitor.scan_backfill_target_message_id = target_message_id
            monitor.last_error = error
            db.commit()

    async def _catchup_chat(self, chat_id: int) -> None:
        """
        Catch up page-by-page without advancing past an enqueue failure.

        ``scan_cursor_message_id`` is a scan watermark, not a processing
        watermark. Each receipt candidate must have a durable DB task before the
        contiguous scanned range is committed. Backfill pagination is persisted,
        so bounded runs resume after restarts instead of rescanning the newest page.
        """
        if is_metadata_only_chat(chat_id):
            return
        with self.session_factory() as db:
            monitor = db.get(MonitoredBotChat, chat_id)
            if not monitor or not monitor.enabled:
                return
            scan_cursor = int(monitor.scan_cursor_message_id or 0)
            from_message_id = int(monitor.scan_backfill_from_message_id or 0)
            target_message_id = (
                int(monitor.scan_backfill_target_message_id)
                if monitor.scan_backfill_target_message_id is not None
                else None
            )
            filter_mode = monitor.filter_mode
            filter_keywords = monitor.filter_keywords
            chat_type = monitor.chat_type

        # Do not keep an ORM object bound to a closed session.
        filter_monitor = MonitoredBotChat(
            chat_id=chat_id,
            enabled=True,
            filter_mode=filter_mode,
            filter_keywords=filter_keywords,
            chat_type=chat_type,
        )

        batch = 100
        batches = 0
        queued = 0
        started_at = time.monotonic()
        limit_hit_reason: Optional[str] = None
        completed = False

        while True:
            backlog = await asyncio.to_thread(self._durable_backlog_size)
            if backlog >= self._max_durable_backlog:
                logger.warning(
                    "Catch-up page paused by durable backlog guard for chat %s (%s >= %s)",
                    chat_id,
                    backlog,
                    self._max_durable_backlog,
                )
                await asyncio.to_thread(
                    self._save_scan_progress,
                    chat_id,
                    from_message_id=from_message_id,
                    target_message_id=target_message_id,
                    error="durable_backlog_guard",
                )
                return
            if batches >= self._catchup_max_batches:
                logger.warning(
                    "Catch-up batch limit hit for chat %s (batches=%s, scan_cursor=%s)",
                    chat_id,
                    batches,
                    scan_cursor,
                )
                limit_hit_reason = "batch_limit"
                break
            if (time.monotonic() - started_at) >= self._catchup_max_seconds:
                logger.warning(
                    "Catch-up time budget exceeded for chat %s (seconds=%s, queued=%s)",
                    chat_id,
                    self._catchup_max_seconds,
                    queued,
                )
                limit_hit_reason = "time_limit"
                break

            page_from_message_id = from_message_id
            resp = await self.manager.get_messages(
                chat_id=chat_id,
                limit=batch,
                from_message_id=from_message_id,
            )
            batches += 1
            items = resp.get("items") or []
            if not items:
                completed = True
                break

            ids = [int(m["id"]) for m in items if m and m.get("id")]
            if not ids:
                completed = True
                break

            if target_message_id is None:
                target_message_id = max(ids)
                await asyncio.to_thread(
                    self._save_scan_progress,
                    chat_id,
                    from_message_id=page_from_message_id,
                    target_message_id=target_message_id,
                )

            page_ok = True
            cutoff_reached = False
            for msg in sorted(items, key=lambda item: int(item.get("id") or 0)):
                mid = int(msg.get("id") or 0)
                if not mid or mid <= scan_cursor:
                    continue
                message_datetime = parse_message_datetime(msg.get("date"))
                if message_datetime is None:
                    logger.warning(
                        "Catch-up skipped message without a valid source date: %s:%s",
                        chat_id,
                        mid,
                    )
                    continue
                if message_datetime < receipt_min_datetime():
                    cutoff_reached = True
                    continue
                if self._should_process_message(filter_monitor, msg):
                    if await self._enqueue(chat_id, mid):
                        queued += 1
                    else:
                        page_ok = False
                        logger.warning(
                            "Catch-up enqueue not durable for %s:%s; retaining page checkpoint",
                            chat_id,
                            mid,
                        )
                        break
                else:
                    logger.debug(
                        "Catchup: Message %s:%s filtered out by %s",
                        chat_id,
                        mid,
                        filter_mode,
                    )

            if not page_ok:
                await asyncio.to_thread(
                    self._save_scan_progress,
                    chat_id,
                    from_message_id=page_from_message_id,
                    target_message_id=target_message_id,
                    error=f"enqueue_failed:{mid}",
                )
                return

            if cutoff_reached:
                logger.info(
                    "Catch-up reached receipt date cutoff for chat %s; older pages skipped",
                    chat_id,
                )
                completed = True
                break

            oldest_id = min(ids)
            if oldest_id <= scan_cursor:
                completed = True
                break
            if int(oldest_id) == int(from_message_id):
                logger.warning(
                    "Catch-up pagination stalled for chat %s at message_id=%s; stopping to avoid loop",
                    chat_id,
                    oldest_id,
                )
                await asyncio.to_thread(
                    self._save_scan_progress,
                    chat_id,
                    from_message_id=page_from_message_id,
                    target_message_id=target_message_id,
                    error="pagination_stalled",
                )
                return
            from_message_id = oldest_id
            await asyncio.to_thread(
                self._save_scan_progress,
                chat_id,
                from_message_id=from_message_id,
                target_message_id=target_message_id,
            )

        if completed and target_message_id is not None:
            await asyncio.to_thread(
                self._save_scan_progress,
                chat_id,
                from_message_id=None,
                target_message_id=None,
                completed_cursor=target_message_id,
            )

        logger.info(
            "Catch-up durably queued %s messages for chat %s (scan_cursor=%s)",
            queued,
            chat_id,
            scan_cursor,
        )
        if limit_hit_reason:
            await asyncio.to_thread(
                self._save_scan_progress,
                chat_id,
                from_message_id=from_message_id,
                target_message_id=target_message_id,
                error=limit_hit_reason,
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
