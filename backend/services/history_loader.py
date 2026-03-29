"""Background loader for full Telegram chat history with persistent cursor state."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import TgChatMessage, TgHistoryCursor, Transaction
from services.telegram_tdlib_manager import TelegramTDLibManager

logger = logging.getLogger(__name__)

TG_HISTORY_BATCH_SIZE = max(50, int(os.getenv("TG_HISTORY_BATCH_SIZE", "500")))
TG_HISTORY_STATUS_ERROR_LIMIT = max(120, int(os.getenv("TG_HISTORY_STATUS_ERROR_LIMIT", "500")))


class TgHistoryLoaderService:
    def __init__(
        self,
        manager: TelegramTDLibManager,
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        self.manager = manager
        self.session_factory = session_factory
        self._jobs: Dict[int, asyncio.Task] = {}
        self._jobs_lock = asyncio.Lock()
        self._event_handlers: List[Callable[[Dict[str, Any]], Awaitable[None] | None]] = []

    def add_event_handler(self, handler: Callable[[Dict[str, Any]], Awaitable[None] | None]) -> None:
        if handler not in self._event_handlers:
            self._event_handlers.append(handler)

    async def _emit(self, payload: Dict[str, Any]) -> None:
        if not self._event_handlers:
            return
        for handler in list(self._event_handlers):
            try:
                result = handler(payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.debug("History loader event dispatch failed", exc_info=True)

    def _extract_sender_id(self, message: Dict[str, Any]) -> Optional[int]:
        sender = message.get("sender_id") or {}
        if not isinstance(sender, dict):
            return None
        for key in ("user_id", "chat_id"):
            value = sender.get(key)
            if value is None:
                continue
            try:
                return int(value)
            except Exception:
                return None
        return None

    def _extract_text(self, message: Dict[str, Any]) -> str:
        content = message.get("content") or {}
        if not isinstance(content, dict):
            return ""
        content_type = content.get("@type")
        if content_type == "messageText":
            return str((content.get("text") or {}).get("text") or "")
        if content_type == "messageDocument":
            caption = str((content.get("caption") or {}).get("text") or "")
            if caption:
                return caption
            document = content.get("document") or {}
            file_name = document.get("file_name") or "document"
            return f"[FILE] {file_name}"
        if content_type == "messagePhoto":
            caption = str((content.get("caption") or {}).get("text") or "")
            return caption or "[Photo]"
        return ""

    def _extract_message_datetime(self, message: Dict[str, Any]) -> Optional[datetime]:
        raw_ts = message.get("date")
        if raw_ts is None:
            return None
        try:
            return datetime.utcfromtimestamp(int(raw_ts))
        except Exception:
            return None

    def _parse_client_datetime(self, value: Optional[str], *, end_of_day: bool = False) -> Optional[datetime]:
        if value is None:
            return None
        raw = str(value).strip()
        if not raw:
            return None

        parsed: Optional[datetime] = None
        if "/" in raw and raw.count("/") == 2 and "T" not in raw and " " not in raw:
            try:
                parsed = datetime.strptime(raw, "%d/%m/%Y")
            except ValueError as exc:
                raise ValueError(f"Invalid date format: {raw}") from exc
        elif len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
            try:
                parsed = datetime.strptime(raw, "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError(f"Invalid date format: {raw}") from exc
        else:
            try:
                normalized = raw.replace("Z", "+00:00")
                parsed = datetime.fromisoformat(normalized)
            except ValueError as exc:
                raise ValueError(f"Invalid date format: {raw}") from exc

        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

        if end_of_day:
            has_explicit_time = ("T" in raw) or (" " in raw and ":" in raw)
            if not has_explicit_time:
                parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
        return parsed

    def _normalize_date_filters(
        self,
        *,
        date_from: Optional[str],
        date_to: Optional[str],
        exclude_from: Optional[str],
        exclude_to: Optional[str],
    ) -> Dict[str, Optional[datetime]]:
        dt_from = self._parse_client_datetime(date_from, end_of_day=False)
        dt_to = self._parse_client_datetime(date_to, end_of_day=True)
        ex_from = self._parse_client_datetime(exclude_from, end_of_day=False)
        ex_to = self._parse_client_datetime(exclude_to, end_of_day=True)

        if dt_from and dt_to and dt_from > dt_to:
            raise ValueError("date_from must be before or equal to date_to")

        if bool(ex_from) ^ bool(ex_to):
            raise ValueError("exclude_from and exclude_to must be provided together")
        if ex_from and ex_to and ex_from > ex_to:
            raise ValueError("exclude_from must be before or equal to exclude_to")

        return {
            "date_from": dt_from,
            "date_to": dt_to,
            "exclude_from": ex_from,
            "exclude_to": ex_to,
        }

    async def _store_batch(self, chat_id: int, batch: List[Dict[str, Any]]) -> int:
        if not batch:
            return 0

        ids = [int(msg.get("id")) for msg in batch if msg and msg.get("id")]
        if not ids:
            return 0

        with self.session_factory() as db:
            existing = {
                int(row[0])
                for row in db.query(TgChatMessage.message_id)
                .filter(TgChatMessage.chat_id == int(chat_id), TgChatMessage.message_id.in_(ids))
                .all()
            }
            to_insert: List[TgChatMessage] = []
            for msg in batch:
                if not msg:
                    continue
                try:
                    message_id = int(msg.get("id"))
                except Exception:
                    continue
                if message_id in existing:
                    continue

                msg_date = None
                try:
                    raw_ts = msg.get("date")
                    if raw_ts is not None:
                        msg_date = datetime.utcfromtimestamp(int(raw_ts))
                except Exception:
                    msg_date = None

                to_insert.append(
                    TgChatMessage(
                        chat_id=int(chat_id),
                        message_id=message_id,
                        message_date=msg_date,
                        is_outgoing=bool(msg.get("is_outgoing", False)),
                        sender_id=self._extract_sender_id(msg),
                        text=self._extract_text(msg),
                        raw_json=json.dumps(msg, ensure_ascii=False),
                    )
                )

            if to_insert:
                db.add_all(to_insert)
                db.commit()

            # Link newly stored messages to existing transactions
            self._link_existing_transactions(db, chat_id, ids)
            return len(to_insert)

    def _link_existing_transactions(
        self, db: Session, chat_id: int, message_ids: List[int]
    ) -> None:
        """Link history messages to already-existing transactions by source_chat_id + source_message_id."""
        if not message_ids:
            return
        try:
            existing_txs = (
                db.query(Transaction.source_message_id, Transaction.id)
                .filter(
                    Transaction.source_chat_id == int(chat_id),
                    Transaction.source_message_id.in_(message_ids),
                )
                .all()
            )
            if not existing_txs:
                return
            tx_map = {int(row[0]): int(row[1]) for row in existing_txs}
            unlinked = (
                db.query(TgChatMessage)
                .filter(
                    TgChatMessage.chat_id == int(chat_id),
                    TgChatMessage.message_id.in_(list(tx_map.keys())),
                    TgChatMessage.receipt_transaction_id.is_(None),
                )
                .all()
            )
            for msg_row in unlinked:
                tid = tx_map.get(int(msg_row.message_id))
                if tid is not None:
                    msg_row.receipt_transaction_id = tid
            if unlinked:
                db.commit()
        except Exception:
            logger.debug("Failed to link transactions to history messages", exc_info=True)

    def _upsert_cursor(
        self,
        *,
        chat_id: int,
        status: str,
        cursor_message_id: Optional[int] = None,
        loaded_count: Optional[int] = None,
        error: Optional[str] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
    ) -> TgHistoryCursor:
        with self.session_factory() as db:
            row = db.get(TgHistoryCursor, int(chat_id))
            if row is None:
                row = TgHistoryCursor(chat_id=int(chat_id))
                db.add(row)
            row.status = status
            if cursor_message_id is not None:
                row.cursor_message_id = int(cursor_message_id)
            if loaded_count is not None:
                row.loaded_count = int(loaded_count)
            if error is not None:
                row.error = str(error)[:TG_HISTORY_STATUS_ERROR_LIMIT]
            elif status in {"running", "completed"}:
                row.error = None
            if started_at is not None:
                row.started_at = started_at
            if finished_at is not None:
                row.finished_at = finished_at
            db.commit()
            db.refresh(row)
            return row

    async def start_load(
        self,
        *,
        chat_id: int,
        max_messages: Optional[int] = None,
        restart: bool = False,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        exclude_from: Optional[str] = None,
        exclude_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        chat_id = int(chat_id)
        date_filters = self._normalize_date_filters(
            date_from=date_from,
            date_to=date_to,
            exclude_from=exclude_from,
            exclude_to=exclude_to,
        )
        async with self._jobs_lock:
            existing = self._jobs.get(chat_id)
            if existing and not existing.done() and not restart:
                return self.get_status(chat_id)

            if existing and not existing.done() and restart:
                existing.cancel()

            task = asyncio.create_task(
                self._run_job(
                    chat_id=chat_id,
                    max_messages=max_messages,
                    restart=restart,
                    date_filters=date_filters,
                ),
                name=f"tg-history-load-{chat_id}",
            )
            self._jobs[chat_id] = task

        return self.get_status(chat_id)

    async def _run_job(
        self,
        *,
        chat_id: int,
        max_messages: Optional[int],
        restart: bool,
        date_filters: Optional[Dict[str, Optional[datetime]]] = None,
    ) -> None:
        started_at = datetime.utcnow()
        date_filters = date_filters or {}
        date_from_dt = date_filters.get("date_from")
        date_to_dt = date_filters.get("date_to")
        exclude_from_dt = date_filters.get("exclude_from")
        exclude_to_dt = date_filters.get("exclude_to")
        with self.session_factory() as db:
            cursor = db.get(TgHistoryCursor, chat_id)
            if cursor is None:
                cursor = TgHistoryCursor(chat_id=chat_id)
                db.add(cursor)
            if restart:
                cursor.cursor_message_id = 0
                cursor.loaded_count = 0
            cursor.status = "running"
            cursor.error = None
            cursor.started_at = started_at
            cursor.finished_at = None
            db.commit()
            db.refresh(cursor)
            current_cursor = int(cursor.cursor_message_id or 0)
            loaded_total = int(cursor.loaded_count or 0)

        await self._emit(
            {
                "type": "progress",
                "channel": "history",
                "chat_id": chat_id,
                "status": "running",
                "loaded": loaded_total,
                "cursor_message_id": current_cursor,
                "started_at": started_at.isoformat() + "Z",
            }
        )

        try:
            async for batch in self.manager.iter_chat_history(
                chat_id=chat_id,
                from_message_id=current_cursor,
                batch_size=TG_HISTORY_BATCH_SIZE,
                max_messages=max_messages,
            ):
                stop_loading = False
                filtered_batch: List[Dict[str, Any]] = []
                for msg in batch:
                    msg_dt = self._extract_message_datetime(msg)

                    if msg_dt and date_from_dt and msg_dt < date_from_dt:
                        # TDLib history is newest -> oldest; once we crossed lower bound we can stop.
                        stop_loading = True
                        break
                    if msg_dt and date_to_dt and msg_dt > date_to_dt:
                        continue
                    if (
                        msg_dt
                        and exclude_from_dt
                        and exclude_to_dt
                        and exclude_from_dt <= msg_dt <= exclude_to_dt
                    ):
                        continue

                    filtered_batch.append(msg)

                inserted = await self._store_batch(chat_id, filtered_batch)
                if batch:
                    try:
                        current_cursor = int((batch[-1] or {}).get("id") or current_cursor)
                    except Exception:
                        pass
                loaded_total += inserted
                self._upsert_cursor(
                    chat_id=chat_id,
                    status="running",
                    cursor_message_id=current_cursor,
                    loaded_count=loaded_total,
                )
                await self._emit(
                    {
                        "type": "progress",
                        "channel": "history",
                        "chat_id": chat_id,
                        "status": "running",
                        "loaded": loaded_total,
                        "cursor_message_id": current_cursor,
                    }
                )
                if stop_loading:
                    break

            finished_at = datetime.utcnow()
            self._upsert_cursor(
                chat_id=chat_id,
                status="completed",
                cursor_message_id=current_cursor,
                loaded_count=loaded_total,
                finished_at=finished_at,
            )
            await self._emit(
                {
                    "type": "progress",
                    "channel": "history",
                    "chat_id": chat_id,
                    "status": "completed",
                    "loaded": loaded_total,
                    "cursor_message_id": current_cursor,
                    "finished_at": finished_at.isoformat() + "Z",
                }
            )
        except asyncio.CancelledError:
            self._upsert_cursor(
                chat_id=chat_id,
                status="idle",
                cursor_message_id=current_cursor,
                loaded_count=loaded_total,
            )
            await self._emit(
                {
                    "type": "progress",
                    "channel": "history",
                    "chat_id": chat_id,
                    "status": "idle",
                    "loaded": loaded_total,
                    "cursor_message_id": current_cursor,
                }
            )
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("History loader job failed for chat %s", chat_id)
            self._upsert_cursor(
                chat_id=chat_id,
                status="failed",
                cursor_message_id=current_cursor,
                loaded_count=loaded_total,
                error=str(exc),
                finished_at=datetime.utcnow(),
            )
            await self._emit(
                {
                    "type": "progress",
                    "channel": "history",
                    "chat_id": chat_id,
                    "status": "failed",
                    "loaded": loaded_total,
                    "cursor_message_id": current_cursor,
                    "error": str(exc),
                }
            )
        finally:
            current_task = asyncio.current_task()
            async with self._jobs_lock:
                task = self._jobs.get(chat_id)
                if task is current_task or (task is not None and task.done()):
                    self._jobs.pop(chat_id, None)

    def get_status(self, chat_id: int) -> Dict[str, Any]:
        chat_id = int(chat_id)
        with self.session_factory() as db:
            row = db.get(TgHistoryCursor, chat_id)

        task = self._jobs.get(chat_id)
        running = bool(task and not task.done())
        if not row:
            return {
                "chat_id": chat_id,
                "status": "running" if running else "idle",
                "cursor_message_id": 0,
                "loaded_count": 0,
                "error": None,
                "started_at": None,
                "finished_at": None,
                "running": running,
            }

        return {
            "chat_id": chat_id,
            "status": row.status,
            "cursor_message_id": int(row.cursor_message_id or 0),
            "loaded_count": int(row.loaded_count or 0),
            "error": row.error,
            "started_at": row.started_at.isoformat() + "Z" if row.started_at else None,
            "finished_at": row.finished_at.isoformat() + "Z" if row.finished_at else None,
            "running": running,
        }

    def get_messages(
        self,
        *,
        chat_id: int,
        limit: int = 200,
        offset: int = 0,
        search: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        chat_id = int(chat_id)
        limit = min(max(1, int(limit)), 5000)
        offset = max(0, int(offset))

        with self.session_factory() as db:
            query = db.query(TgChatMessage).filter(TgChatMessage.chat_id == chat_id)

            if search:
                query = query.filter(TgChatMessage.text.ilike(f"%{search}%"))
            if date_from:
                try:
                    from datetime import datetime as _dt
                    dt_from = _dt.fromisoformat(date_from.replace("Z", "+00:00").replace("T", " ").split("+")[0])
                    query = query.filter(TgChatMessage.message_date >= dt_from)
                except (ValueError, TypeError):
                    pass
            if date_to:
                try:
                    from datetime import datetime as _dt
                    dt_to = _dt.fromisoformat(date_to.replace("Z", "+00:00").replace("T", " ").split("+")[0])
                    query = query.filter(TgChatMessage.message_date <= dt_to)
                except (ValueError, TypeError):
                    pass

            total = int(query.count())
            rows = (
                query.order_by(TgChatMessage.message_id.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )

        rows = list(reversed(rows))
        items: List[Dict[str, Any]] = []
        for row in rows:
            payload: Dict[str, Any]
            try:
                payload = json.loads(row.raw_json or "{}")
            except Exception:
                payload = {
                    "chat_id": row.chat_id,
                    "id": row.message_id,
                    "date": int(row.message_date.timestamp()) if row.message_date else None,
                    "text": row.text,
                    "is_outgoing": row.is_outgoing,
                    "sender_id": {"user_id": row.sender_id} if row.sender_id is not None else None,
                }
            if row.receipt_transaction_id:
                payload["_receipt_transaction_id"] = int(row.receipt_transaction_id)
            items.append(payload)

        return {
            "chat_id": chat_id,
            "total": total,
            "items": items,
            "offset": offset,
            "limit": limit,
            "has_more": (offset + len(rows)) < total,
        }


_service: Optional[TgHistoryLoaderService] = None


def init_history_loader_service(
    manager: TelegramTDLibManager,
    session_factory: Callable[[], Session] = SessionLocal,
) -> TgHistoryLoaderService:
    global _service
    if _service is None:
        _service = TgHistoryLoaderService(manager=manager, session_factory=session_factory)
    return _service


def get_history_loader_service() -> Optional[TgHistoryLoaderService]:
    return _service
