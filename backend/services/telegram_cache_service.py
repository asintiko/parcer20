from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from config.ai_models import AI_AGENT_RECEIPT_GRACE_MINUTES
from database.models import (
    DuplicateMergeLog,
    MonitoredBotChat,
    ReceiptProcessingTask,
    TgChatMessage,
    TgHistoryCursor,
    Transaction,
)
from services.message_utils import looks_like_receipt


ProgressCallback = Callable[[Dict[str, Any]], None]


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except Exception:
        return None


@dataclass
class AuditItem:
    category: str
    chat_id: int
    message_id: Optional[int]
    message_date: Optional[str]
    title: str
    summary: str
    transaction_id: Optional[int] = None
    task_id: Optional[int] = None
    payload: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "message_date": self.message_date,
            "title": self.title,
            "summary": self.summary,
            "transaction_id": self.transaction_id,
            "task_id": self.task_id,
            "payload": self.payload or {},
        }


class TelegramCacheService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_monitored_chat_ids(self, only_enabled: bool = True) -> List[int]:
        query = self.db.query(MonitoredBotChat.chat_id)
        if only_enabled:
            query = query.filter(MonitoredBotChat.enabled.is_(True))
        return [int(row[0]) for row in query.order_by(MonitoredBotChat.chat_id.asc()).all()]

    def search_messages(
        self,
        *,
        chat_ids: Optional[Iterable[int]] = None,
        search: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        looks_like_receipt_only: bool = False,
        processing_status: Optional[str] = None,
        duplicate_status: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        query = self.db.query(TgChatMessage)
        if chat_ids:
            query = query.filter(TgChatMessage.chat_id.in_([int(item) for item in chat_ids]))
        if date_from:
            query = query.filter(TgChatMessage.message_date >= date_from)
        if date_to:
            query = query.filter(TgChatMessage.message_date <= date_to)
        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(TgChatMessage.text.ilike(pattern))
        if looks_like_receipt_only:
            query = query.filter(
                or_(
                    TgChatMessage.looks_like_receipt.is_(True),
                    and_(TgChatMessage.content_type.in_(["messageDocument", "messagePhoto"]), TgChatMessage.message_date.isnot(None)),
                )
            )
        if processing_status:
            query = query.filter(TgChatMessage.processing_status == str(processing_status))
        if duplicate_status:
            query = query.filter(TgChatMessage.duplicate_status == str(duplicate_status))

        rows = query.order_by(TgChatMessage.message_date.desc().nullslast(), TgChatMessage.id.desc()).limit(max(1, min(int(limit), 1000))).all()
        return [self._serialize_message(row) for row in rows]

    def estimate_receipt_candidate_count(
        self,
        *,
        chat_ids: Optional[Iterable[int]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> int:
        query = self.db.query(func.count(TgChatMessage.id))
        if chat_ids:
            query = query.filter(TgChatMessage.chat_id.in_([int(item) for item in chat_ids]))
        if date_from:
            query = query.filter(TgChatMessage.message_date >= date_from)
        if date_to:
            query = query.filter(TgChatMessage.message_date <= date_to)
        query = query.filter(
            or_(
                TgChatMessage.looks_like_receipt.is_(True),
                TgChatMessage.content_type.in_(["messageDocument", "messagePhoto"]),
            )
        )
        return int(query.scalar() or 0)

    def monitored_chat_health(self, chat_ids: Optional[Iterable[int]] = None) -> List[Dict[str, Any]]:
        query = self.db.query(MonitoredBotChat)
        if chat_ids:
            query = query.filter(MonitoredBotChat.chat_id.in_([int(item) for item in chat_ids]))
        chats = query.order_by(MonitoredBotChat.chat_id.asc()).all()
        cursor_map = {
            int(row.chat_id): row
            for row in self.db.query(TgHistoryCursor)
            .filter(TgHistoryCursor.chat_id.in_([int(item.chat_id) for item in chats]) if chats else False)
            .all()
        } if chats else {}
        payload: List[Dict[str, Any]] = []
        for chat in chats:
            cursor = cursor_map.get(int(chat.chat_id))
            payload.append(
                {
                    "chat_id": int(chat.chat_id),
                    "title": chat.chat_title,
                    "chat_type": chat.chat_type,
                    "enabled": bool(chat.enabled),
                    "last_history_sync_at": chat.last_history_sync_at.isoformat() if chat.last_history_sync_at else None,
                    "last_realtime_seen_at": chat.last_realtime_seen_at.isoformat() if chat.last_realtime_seen_at else None,
                    "last_receipt_candidate_at": chat.last_receipt_candidate_at.isoformat() if chat.last_receipt_candidate_at else None,
                    "last_sync_issue_at": chat.last_sync_issue_at.isoformat() if chat.last_sync_issue_at else None,
                    "cursor_status": cursor.status if cursor else "not_started",
                    "cursor_message_id": int(cursor.cursor_message_id) if cursor else 0,
                    "loaded_count": int(cursor.loaded_count) if cursor else 0,
                    "lag_messages": int(cursor.lag_messages) if cursor else 0,
                    "lag_seconds": int(cursor.lag_seconds) if cursor else 0,
                    "cursor_error": cursor.error if cursor else None,
                }
            )
        return payload

    def trace_message(self, *, chat_id: int, message_id: int) -> Dict[str, Any]:
        message = (
            self.db.query(TgChatMessage)
            .filter(TgChatMessage.chat_id == int(chat_id), TgChatMessage.message_id == int(message_id))
            .first()
        )
        task = (
            self.db.query(ReceiptProcessingTask)
            .filter(ReceiptProcessingTask.chat_id == int(chat_id), ReceiptProcessingTask.message_id == int(message_id))
            .order_by(ReceiptProcessingTask.updated_at.desc().nullslast(), ReceiptProcessingTask.id.desc())
            .first()
        )
        transaction = (
            self.db.query(Transaction)
            .filter(Transaction.source_chat_id == int(chat_id), Transaction.source_message_id == int(message_id))
            .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
            .first()
        )
        duplicate = (
            self.db.query(DuplicateMergeLog)
            .filter(DuplicateMergeLog.source_chat_id == int(chat_id), DuplicateMergeLog.source_message_id == int(message_id))
            .order_by(DuplicateMergeLog.created_at.desc())
            .first()
        )
        status = "NOT_FOUND"
        if transaction:
            status = "SYNCED"
        elif task and str(task.status).lower() == "failed":
            status = "FAILED_PARSE"
        elif duplicate:
            status = "DUPLICATE"
        elif message:
            status = "PENDING_PROCESSING" if self._is_fresh_message(message, 5) else "MISSING_IN_DB"
        return {
            "status": status,
            "message": self._serialize_message(message) if message else None,
            "task": self._serialize_task(task) if task else None,
            "transaction": self._serialize_transaction(transaction) if transaction else None,
            "duplicate": {
                "existing_transaction_id": int(duplicate.existing_transaction_id),
                "merged": bool(duplicate.merged),
                "created_at": duplicate.created_at.isoformat() if duplicate.created_at else None,
            } if duplicate else None,
            "summary": self._build_trace_summary(status=status, chat_id=int(chat_id), message_id=int(message_id), task=task, transaction=transaction, duplicate=duplicate),
        }

    def audit_monitored_chats(
        self,
        *,
        chat_ids: Optional[Iterable[int]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        grace_minutes: int = AI_AGENT_RECEIPT_GRACE_MINUTES,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Dict[str, Any]:
        monitored_ids = [int(item) for item in chat_ids] if chat_ids else self.list_monitored_chat_ids(only_enabled=True)
        total_chats = len(monitored_ids)
        issues: List[AuditItem] = []
        by_category: Dict[str, int] = defaultdict(int)
        by_chat: Dict[int, Dict[str, Any]] = {}

        for index, chat_id in enumerate(monitored_ids, start=1):
            chat_health = next((item for item in self.monitored_chat_health([chat_id])), {"chat_id": chat_id})
            chat_summary = {
                "chat_id": chat_id,
                "title": chat_health.get("title"),
                "categories": defaultdict(int),
                "total_candidates": 0,
            }
            by_chat[chat_id] = chat_summary

            if chat_health.get("cursor_status") not in {"completed", "loading", "idle"}:
                issues.append(
                    AuditItem(
                        category="CURSOR_STALE",
                        chat_id=chat_id,
                        message_id=None,
                        message_date=None,
                        title="Проблема синхронизации",
                        summary=f"Курсор истории в состоянии {chat_health.get('cursor_status') or 'unknown'}.",
                        payload=chat_health,
                    )
                )
                by_category["CURSOR_STALE"] += 1
                chat_summary["categories"]["CURSOR_STALE"] += 1

            query = self.db.query(TgChatMessage).filter(TgChatMessage.chat_id == chat_id)
            if date_from:
                query = query.filter(TgChatMessage.message_date >= date_from)
            if date_to:
                query = query.filter(TgChatMessage.message_date <= date_to)
            messages = query.order_by(TgChatMessage.message_date.desc().nullslast(), TgChatMessage.id.desc()).all()
            if not messages:
                issues.append(
                    AuditItem(
                        category="CACHE_GAP",
                        chat_id=chat_id,
                        message_id=None,
                        message_date=None,
                        title="Пустой кеш истории",
                        summary="В кеше нет сообщений за выбранный период.",
                        payload={"chat_id": chat_id, "date_from": date_from.isoformat() if date_from else None, "date_to": date_to.isoformat() if date_to else None},
                    )
                )
                by_category["CACHE_GAP"] += 1
                chat_summary["categories"]["CACHE_GAP"] += 1
                continue

            message_ids = [int(row.message_id) for row in messages]
            tx_rows = (
                self.db.query(Transaction)
                .filter(Transaction.source_chat_id == chat_id, Transaction.source_message_id.in_(message_ids))
                .all()
            )
            tx_map = {int(row.source_message_id): row for row in tx_rows if row.source_message_id is not None}
            task_rows = (
                self.db.query(ReceiptProcessingTask)
                .filter(ReceiptProcessingTask.chat_id == chat_id, ReceiptProcessingTask.message_id.in_(message_ids))
                .all()
            )
            task_map = {int(row.message_id): row for row in task_rows}
            dup_rows = (
                self.db.query(DuplicateMergeLog)
                .filter(DuplicateMergeLog.source_chat_id == chat_id, DuplicateMergeLog.source_message_id.in_(message_ids))
                .all()
            )
            dup_map = {int(row.source_message_id): row for row in dup_rows if row.source_message_id is not None}

            for msg in messages:
                if not self._looks_like_receipt_message(msg):
                    continue
                chat_summary["total_candidates"] += 1
                category = "SYNCED"
                transaction = tx_map.get(int(msg.message_id))
                task = task_map.get(int(msg.message_id))
                duplicate = dup_map.get(int(msg.message_id))
                if transaction or msg.receipt_transaction_id:
                    category = "SYNCED"
                elif duplicate:
                    category = "DUPLICATE"
                elif task and str(task.status).lower() == "failed":
                    category = "FAILED_PARSE"
                elif self._is_fresh_message(msg, grace_minutes):
                    category = "PENDING_PROCESSING"
                else:
                    category = "MISSING_IN_DB"

                by_category[category] += 1
                chat_summary["categories"][category] += 1
                if category != "SYNCED":
                    issues.append(
                        AuditItem(
                            category=category,
                            chat_id=chat_id,
                            message_id=int(msg.message_id),
                            message_date=msg.message_date.isoformat() if msg.message_date else None,
                            title=self._issue_title(category),
                            summary=self._issue_summary(category, msg=msg, task=task, transaction=transaction, duplicate=duplicate),
                            transaction_id=int(transaction.id) if transaction else (int(msg.receipt_transaction_id) if msg.receipt_transaction_id else None),
                            task_id=int(task.id) if task else None,
                            payload={
                                "chat_id": chat_id,
                                "message_id": int(msg.message_id),
                                "text_preview": (msg.text or "")[:280],
                                "task_status": task.status if task else None,
                                "duplicate": bool(duplicate),
                            },
                        )
                    )

            orphaned = (
                self.db.query(Transaction)
                .filter(Transaction.source_chat_id == chat_id)
                .filter(Transaction.source_message_id.isnot(None))
            )
            if date_from:
                orphaned = orphaned.filter(Transaction.transaction_date >= date_from)
            if date_to:
                orphaned = orphaned.filter(Transaction.transaction_date <= date_to)
            message_id_set = set(message_ids)
            for tx in orphaned.all():
                source_message_id = int(tx.source_message_id) if tx.source_message_id is not None else None
                if source_message_id is None or source_message_id in message_id_set:
                    continue
                issues.append(
                    AuditItem(
                        category="ORPHANED_IN_DB",
                        chat_id=chat_id,
                        message_id=source_message_id,
                        message_date=tx.transaction_date.isoformat() if tx.transaction_date else None,
                        title="Транзакция без сообщения в кеше",
                        summary=f"В таблице есть транзакция #{tx.id}, но исходное сообщение отсутствует в кеше.",
                        transaction_id=int(tx.id),
                        payload=self._serialize_transaction(tx),
                    )
                )
                by_category["ORPHANED_IN_DB"] += 1
                chat_summary["categories"]["ORPHANED_IN_DB"] += 1

            if progress_callback:
                progress_callback(
                    {
                        "chat_id": chat_id,
                        "completed_chats": index,
                        "total_chats": total_chats,
                        "categories": {key: int(value) for key, value in by_category.items()},
                    }
                )

        normalized_by_chat = []
        for chat_id in monitored_ids:
            item = by_chat.get(chat_id) or {"chat_id": chat_id, "title": None, "categories": {}, "total_candidates": 0}
            normalized_by_chat.append(
                {
                    "chat_id": item["chat_id"],
                    "title": item.get("title"),
                    "total_candidates": int(item.get("total_candidates") or 0),
                    "categories": {key: int(value) for key, value in dict(item.get("categories") or {}).items()},
                }
            )

        categories_summary = {key: int(value) for key, value in by_category.items()}
        return {
            "categories": categories_summary,
            "issues": [item.to_dict() for item in issues],
            "by_chat": normalized_by_chat,
            "total_issues": len(issues),
            "checked_chats": total_chats,
        }

    def audit_monitored_chats_chunked(
        self,
        *,
        chat_ids: Optional[Iterable[int]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        grace_minutes: int = AI_AGENT_RECEIPT_GRACE_MINUTES,
        chunk_size: int = 500,
        progress_callback: Optional[ProgressCallback] = None,
        resume_state: Optional[Dict[str, Any]] = None,
        max_chunks: Optional[int] = None,
        issue_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        state = dict(resume_state or {})
        monitored_ids = [int(item) for item in (state.get("monitored_ids") or (chat_ids if chat_ids else self.list_monitored_chat_ids(only_enabled=True)))]
        total_chats = len(monitored_ids)
        total_estimated_messages = int(
            state.get("total_estimated_messages")
            or self.estimate_receipt_candidate_count(chat_ids=monitored_ids, date_from=date_from, date_to=date_to)
        )
        processed_messages = int(state.get("processed_messages") or 0)
        total_issues = int(state.get("total_issues") or 0)
        completed_chat_ids = [int(item) for item in (state.get("completed_chat_ids") or [])]
        seen_chat_ids = {int(item) for item in (state.get("seen_chat_ids") or [])}
        issues_preview = list(state.get("issues_preview") or [])
        top_actionable_cases = list(state.get("top_actionable_cases") or [])
        by_category: Dict[str, int] = defaultdict(int, {str(key): int(value) for key, value in (state.get("categories") or {}).items()})

        by_chat_seed = {int(item.get("chat_id")): item for item in (state.get("by_chat") or []) if item.get("chat_id") is not None}
        by_chat: Dict[int, Dict[str, Any]] = {}
        for chat_id in monitored_ids:
            existing = by_chat_seed.get(int(chat_id)) or {}
            by_chat[int(chat_id)] = {
                "chat_id": int(chat_id),
                "title": existing.get("title"),
                "categories": defaultdict(int, {str(key): int(value) for key, value in dict(existing.get("categories") or {}).items()}),
                "total_candidates": int(existing.get("total_candidates") or 0),
            }

        cursor = state.get("cursor") or None
        cursor_chat_id = int(cursor.get("chat_id")) if isinstance(cursor, dict) and cursor.get("chat_id") is not None else None
        cursor_message_date = _parse_datetime(cursor.get("message_date")) if isinstance(cursor, dict) else None
        cursor_row_id = int(cursor.get("id")) if isinstance(cursor, dict) and cursor.get("id") is not None else None
        chunks_processed = 0

        def _normalized_summary(*, complete: bool, phase: str, current_chat_id: Optional[int], current_cursor: Optional[Dict[str, Any]]) -> Dict[str, Any]:
            normalized_by_chat = []
            for normalized_chat_id in monitored_ids:
                item = by_chat.get(normalized_chat_id) or {"chat_id": normalized_chat_id, "title": None, "categories": {}, "total_candidates": 0}
                normalized_by_chat.append(
                    {
                        "chat_id": int(item["chat_id"]),
                        "title": item.get("title"),
                        "total_candidates": int(item.get("total_candidates") or 0),
                        "categories": {key: int(value) for key, value in dict(item.get("categories") or {}).items()},
                    }
                )
            return {
                "complete": bool(complete),
                "mode": "background",
                "phase": phase,
                "current_chat_id": int(current_chat_id) if current_chat_id is not None else None,
                "processed_messages": int(processed_messages),
                "total_estimated_messages": int(total_estimated_messages),
                "issues_found": int(total_issues),
                "categories": {key: int(value) for key, value in by_category.items()},
                "by_chat": normalized_by_chat,
                "issues": list(issues_preview),
                "issues_preview": list(issues_preview),
                "top_actionable_cases": list(top_actionable_cases),
                "total_issues": int(total_issues),
                "checked_chats": total_chats,
                "completed_chat_ids": list(completed_chat_ids),
                "seen_chat_ids": sorted(seen_chat_ids),
                "cursor": current_cursor,
                "started_from_latest": True,
                "monitored_ids": list(monitored_ids),
                "percent": int(min(99 if not complete else 100, max(
                    (processed_messages / max(total_estimated_messages or 1, 1)) * 100,
                    (len(completed_chat_ids) / max(total_chats or 1, 1)) * 100,
                ))),
            }

        def _track_issue(issue: AuditItem, *, actionable: bool = True) -> None:
            nonlocal total_issues
            issue_dict = issue.to_dict()
            total_issues += 1
            if len(issues_preview) < 25:
                issues_preview.append(issue_dict)
            if actionable and len(top_actionable_cases) < 20:
                top_actionable_cases.append(issue_dict)
            if issue_callback:
                issue_callback(issue_dict)

        start_index = len(completed_chat_ids)
        if cursor_chat_id is not None:
            try:
                start_index = monitored_ids.index(cursor_chat_id)
            except ValueError:
                start_index = len(completed_chat_ids)
                cursor_chat_id = None
                cursor_message_date = None
                cursor_row_id = None

        for index in range(start_index, total_chats):
            chat_id = int(monitored_ids[index])
            if chat_id in completed_chat_ids:
                continue

            chat_health = next((item for item in self.monitored_chat_health([chat_id])), {"chat_id": chat_id})
            chat_summary = by_chat.setdefault(
                chat_id,
                {"chat_id": chat_id, "title": chat_health.get("title"), "categories": defaultdict(int), "total_candidates": 0},
            )
            chat_summary["title"] = chat_summary.get("title") or chat_health.get("title")

            if chat_summary["categories"].get("CURSOR_STALE", 0) == 0 and chat_health.get("cursor_status") not in {"completed", "loading", "idle"}:
                stale_issue = AuditItem(
                    category="CURSOR_STALE",
                    chat_id=chat_id,
                    message_id=None,
                    message_date=None,
                    title="Проблема синхронизации",
                    summary=f"Курсор истории в состоянии {chat_health.get('cursor_status') or 'unknown'}.",
                    payload=chat_health,
                )
                by_category["CURSOR_STALE"] += 1
                chat_summary["categories"]["CURSOR_STALE"] += 1
                _track_issue(stale_issue)

            base_query = self.db.query(TgChatMessage).filter(TgChatMessage.chat_id == chat_id)
            if date_from:
                base_query = base_query.filter(TgChatMessage.message_date >= date_from)
            if date_to:
                base_query = base_query.filter(TgChatMessage.message_date <= date_to)

            saw_messages = chat_id in seen_chat_ids
            last_message_date = cursor_message_date if cursor_chat_id == chat_id else None
            last_row_id = cursor_row_id if cursor_chat_id == chat_id else None

            while True:
                query = base_query
                if last_row_id is not None:
                    if last_message_date is not None:
                        query = query.filter(
                            or_(
                                TgChatMessage.message_date < last_message_date,
                                and_(TgChatMessage.message_date == last_message_date, TgChatMessage.id < last_row_id),
                                TgChatMessage.message_date.is_(None),
                            )
                        )
                    else:
                        query = query.filter(TgChatMessage.message_date.is_(None), TgChatMessage.id < last_row_id)

                rows = (
                    query.order_by(TgChatMessage.message_date.desc().nullslast(), TgChatMessage.id.desc())
                    .limit(max(1, min(int(chunk_size), 2000)))
                    .all()
                )
                if not rows:
                    if not saw_messages and chat_summary["categories"].get("CACHE_GAP", 0) == 0:
                        cache_gap_issue = AuditItem(
                            category="CACHE_GAP",
                            chat_id=chat_id,
                            message_id=None,
                            message_date=None,
                            title="Пустой кеш истории",
                            summary="В кеше нет сообщений за выбранный период.",
                            payload={
                                "chat_id": chat_id,
                                "date_from": date_from.isoformat() if date_from else None,
                                "date_to": date_to.isoformat() if date_to else None,
                            },
                        )
                        by_category["CACHE_GAP"] += 1
                        chat_summary["categories"]["CACHE_GAP"] += 1
                        _track_issue(cache_gap_issue)

                    message_exists_query = (
                        self.db.query(TgChatMessage.id)
                        .filter(TgChatMessage.chat_id == chat_id, TgChatMessage.message_id == Transaction.source_message_id)
                        .exists()
                    )
                    orphaned = (
                        self.db.query(Transaction)
                        .filter(Transaction.source_chat_id == chat_id)
                        .filter(Transaction.source_message_id.isnot(None))
                        .filter(~message_exists_query)
                    )
                    if date_from:
                        orphaned = orphaned.filter(Transaction.transaction_date >= date_from)
                    if date_to:
                        orphaned = orphaned.filter(Transaction.transaction_date <= date_to)
                    for tx in orphaned.all():
                        orphan_issue = AuditItem(
                            category="ORPHANED_IN_DB",
                            chat_id=chat_id,
                            message_id=int(tx.source_message_id) if tx.source_message_id is not None else None,
                            message_date=tx.transaction_date.isoformat() if tx.transaction_date else None,
                            title="Транзакция без сообщения в кеше",
                            summary=f"В таблице есть транзакция #{tx.id}, но исходное сообщение отсутствует в кеше.",
                            transaction_id=int(tx.id),
                            payload=self._serialize_transaction(tx),
                        )
                        by_category["ORPHANED_IN_DB"] += 1
                        chat_summary["categories"]["ORPHANED_IN_DB"] += 1
                        _track_issue(orphan_issue)

                    completed_chat_ids.append(chat_id)
                    cursor_chat_id = None
                    cursor_message_date = None
                    cursor_row_id = None
                    if progress_callback:
                        progress_callback(
                            _normalized_summary(
                                complete=False,
                                phase="chat_complete",
                                current_chat_id=chat_id,
                                current_cursor=None,
                            )
                        )
                    break

                saw_messages = True
                seen_chat_ids.add(chat_id)
                message_ids = [int(row.message_id) for row in rows]
                tx_rows = (
                    self.db.query(Transaction)
                    .filter(Transaction.source_chat_id == chat_id, Transaction.source_message_id.in_(message_ids))
                    .all()
                )
                tx_map = {int(row.source_message_id): row for row in tx_rows if row.source_message_id is not None}
                task_rows = (
                    self.db.query(ReceiptProcessingTask)
                    .filter(ReceiptProcessingTask.chat_id == chat_id, ReceiptProcessingTask.message_id.in_(message_ids))
                    .all()
                )
                task_map = {int(row.message_id): row for row in task_rows}
                dup_rows = (
                    self.db.query(DuplicateMergeLog)
                    .filter(DuplicateMergeLog.source_chat_id == chat_id, DuplicateMergeLog.source_message_id.in_(message_ids))
                    .all()
                )
                dup_map = {int(row.source_message_id): row for row in dup_rows if row.source_message_id is not None}

                for msg in rows:
                    if not self._looks_like_receipt_message(msg):
                        continue
                    chat_summary["total_candidates"] += 1
                    category = "SYNCED"
                    transaction = tx_map.get(int(msg.message_id))
                    task = task_map.get(int(msg.message_id))
                    duplicate = dup_map.get(int(msg.message_id))
                    if transaction or msg.receipt_transaction_id:
                        category = "SYNCED"
                    elif duplicate:
                        category = "DUPLICATE"
                    elif task and str(task.status).lower() == "failed":
                        category = "FAILED_PARSE"
                    elif self._is_fresh_message(msg, grace_minutes):
                        category = "PENDING_PROCESSING"
                    else:
                        category = "MISSING_IN_DB"

                    by_category[category] += 1
                    chat_summary["categories"][category] += 1
                    if category != "SYNCED":
                        issue = AuditItem(
                            category=category,
                            chat_id=chat_id,
                            message_id=int(msg.message_id),
                            message_date=msg.message_date.isoformat() if msg.message_date else None,
                            title=self._issue_title(category),
                            summary=self._issue_summary(category, msg=msg, task=task, transaction=transaction, duplicate=duplicate),
                            transaction_id=int(transaction.id) if transaction else (int(msg.receipt_transaction_id) if msg.receipt_transaction_id else None),
                            task_id=int(task.id) if task else None,
                            payload={
                                "chat_id": chat_id,
                                "message_id": int(msg.message_id),
                                "text_preview": (msg.text or "")[:280],
                                "task_status": task.status if task else None,
                                "duplicate": bool(duplicate),
                            },
                        )
                        _track_issue(issue, actionable=category not in {"PENDING_PROCESSING"})

                processed_messages += len(rows)
                chunks_processed += 1
                last_row = rows[-1]
                last_message_date = last_row.message_date
                last_row_id = int(last_row.id)
                cursor_chat_id = chat_id
                cursor_message_date = last_message_date
                cursor_row_id = last_row_id
                current_cursor = {
                    "chat_id": chat_id,
                    "message_date": last_message_date.isoformat() if last_message_date else None,
                    "id": last_row_id,
                    "message_id": int(last_row.message_id),
                }
                if progress_callback:
                    progress_callback(
                        _normalized_summary(
                            complete=False,
                            phase="scan_chunk",
                            current_chat_id=chat_id,
                            current_cursor=current_cursor,
                        )
                    )
                if max_chunks is not None and chunks_processed >= max(1, int(max_chunks)):
                    return _normalized_summary(
                        complete=False,
                        phase="scan_chunk",
                        current_chat_id=chat_id,
                        current_cursor=current_cursor,
                    )

        return _normalized_summary(
            complete=True,
            phase="completed",
            current_chat_id=None,
            current_cursor=None,
        )

    def _serialize_message(self, row: Optional[TgChatMessage]) -> Dict[str, Any]:
        if not row:
            return {}
        return {
            "id": int(row.id),
            "chat_id": int(row.chat_id),
            "message_id": int(row.message_id),
            "message_date": row.message_date.isoformat() if row.message_date else None,
            "text": row.text,
            "receipt_transaction_id": int(row.receipt_transaction_id) if row.receipt_transaction_id is not None else None,
            "looks_like_receipt": bool(row.looks_like_receipt),
            "processing_status": row.processing_status,
            "duplicate_status": row.duplicate_status,
            "source_chat_title_snapshot": row.source_chat_title_snapshot,
        }

    def _serialize_task(self, row: Optional[ReceiptProcessingTask]) -> Dict[str, Any]:
        if not row:
            return {}
        return {
            "id": int(row.id),
            "task_id": row.task_id,
            "chat_id": int(row.chat_id),
            "message_id": int(row.message_id),
            "status": row.status,
            "transaction_id": int(row.transaction_id) if row.transaction_id is not None else None,
            "error": row.error,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _serialize_transaction(self, row: Optional[Transaction]) -> Dict[str, Any]:
        if not row:
            return {}
        return {
            "id": int(row.id),
            "source_chat_id": int(row.source_chat_id) if row.source_chat_id is not None else None,
            "source_message_id": int(row.source_message_id) if row.source_message_id is not None else None,
            "transaction_date": row.transaction_date.isoformat() if row.transaction_date else None,
            "amount": str(row.amount) if row.amount is not None else None,
            "currency": row.currency,
            "operator_raw": row.operator_raw,
            "application_mapped": row.application_mapped,
        }

    def _is_fresh_message(self, row: TgChatMessage, grace_minutes: int) -> bool:
        if not row.message_date:
            return False
        now = datetime.utcnow()
        threshold = now - timedelta(minutes=max(1, int(grace_minutes)))
        return row.message_date.replace(tzinfo=None) >= threshold

    def _looks_like_receipt_message(self, row: TgChatMessage) -> bool:
        if row.looks_like_receipt:
            return True
        if row.content_type in {"messageDocument", "messagePhoto"}:
            return True
        return looks_like_receipt(row.text or "", row.raw_json or "")

    def _issue_title(self, category: str) -> str:
        titles = {
            "MISSING_IN_DB": "Чек не дошел до таблицы",
            "FAILED_PARSE": "Ошибка обработки чека",
            "DUPLICATE": "Чек ушел в дубликат",
            "PENDING_PROCESSING": "Чек еще в обработке",
            "CURSOR_STALE": "Проблема синхронизации",
            "CACHE_GAP": "Пробел в кеше",
            "ORPHANED_IN_DB": "Транзакция без исходного сообщения",
        }
        return titles.get(category, "Проблема мониторинга")

    def _issue_summary(
        self,
        category: str,
        *,
        msg: TgChatMessage,
        task: Optional[ReceiptProcessingTask],
        transaction: Optional[Transaction],
        duplicate: Optional[DuplicateMergeLog],
    ) -> str:
        if category == "MISSING_IN_DB":
            return "Сообщение похоже на чек, но после grace-window транзакция в таблице не появилась."
        if category == "FAILED_PARSE":
            return f"Обработка завершилась ошибкой: {task.error if task and task.error else 'подробности не сохранены'}."
        if category == "DUPLICATE":
            existing_id = int(duplicate.existing_transaction_id) if duplicate else None
            return f"Сообщение распознано как дубль уже существующей транзакции #{existing_id}."
        if category == "PENDING_PROCESSING":
            return "Сообщение свежее и находится внутри grace-window обработки."
        if category == "ORPHANED_IN_DB":
            return f"В таблице уже есть транзакция #{transaction.id if transaction else '-'}, но исходное сообщение отсутствует в кеше."
        return "Найдена проблема мониторинга, требуется перепроверка."

    def _build_trace_summary(
        self,
        *,
        status: str,
        chat_id: int,
        message_id: int,
        task: Optional[ReceiptProcessingTask],
        transaction: Optional[Transaction],
        duplicate: Optional[DuplicateMergeLog],
    ) -> str:
        if status == "SYNCED":
            return f"Сообщение {chat_id}/{message_id} дошло до таблицы и связано с транзакцией #{transaction.id if transaction else '-'} ."
        if status == "FAILED_PARSE":
            return f"Сообщение {chat_id}/{message_id} попало в очередь, но обработка завершилась ошибкой."
        if status == "DUPLICATE":
            return f"Сообщение {chat_id}/{message_id} было классифицировано как дубль транзакции #{duplicate.existing_transaction_id if duplicate else '-'} ."
        if status == "MISSING_IN_DB":
            return f"Сообщение {chat_id}/{message_id} найдено в кеше, но после обработки не попало в таблицу."
        if status == "PENDING_PROCESSING":
            return f"Сообщение {chat_id}/{message_id} еще находится внутри grace-window обработки."
        return f"Сообщение {chat_id}/{message_id} не найдено в кеше или трассировка неполная."
