from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from database.models import (
    AgentRun,
    AgentRunEvent,
    AgentThread,
    AgentReport,
    AgentReportItem,
    AutomationSuggestion,
    DuplicateMergeLog,
    DuplicateSuggestion,
    ReceiptProcessingIncident,
    ReceiptProcessingTask,
    ReconciliationSuggestion,
    TgChatMessage,
    Transaction,
    VerificationSuggestion,
)
from services.ai_agent.report_service import publish_report
from services.receipt_processor import _merge_duplicate_transaction
from workers.celery_worker import queue_receipt_task


JsonDict = Dict[str, Any]


def _load_json(value: Optional[str]) -> JsonDict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _extract_formatted_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            return text
    return ""


def _confirmation_payload(run: AgentRun) -> JsonDict:
    result = _load_json(run.result_json)
    payload = result.get("confirmation_payload")
    return payload if isinstance(payload, dict) else {}


def _already_confirmed_payload(run: AgentRun) -> Optional[JsonDict]:
    result = _load_json(run.result_json)
    payload = result.get("confirmation_result")
    return payload if isinstance(payload, dict) else None


def _serialize_report_card(report: JsonDict) -> JsonDict:
    items = report.get("items") or []
    compact_report = {
        "id": report.get("id"),
        "title": report.get("title") or "Командный отчет",
        "scope": report.get("scope"),
        "status": report.get("status"),
        "summary": report.get("summary") or {},
        "items_count": len(items),
        "items_preview": items[:10],
    }
    return {
        "type": "report",
        "title": compact_report["title"],
        "report": compact_report,
    }


def _serialize_navigation_for_transactions(
    *,
    row_id: Optional[int] = None,
    row_ids: Optional[Iterable[int]] = None,
    column_id: Optional[str] = None,
    suggested_filters: Optional[JsonDict] = None,
    highlight_seconds: int = 4,
) -> JsonDict:
    cleaned_row_ids = [int(item) for item in (row_ids or []) if item is not None]
    return {
        "route": "/transactions",
        "row_id": int(row_id) if row_id is not None else (cleaned_row_ids[0] if cleaned_row_ids else None),
        "row_ids": cleaned_row_ids or None,
        "column_id": column_id,
        "focus_mode": "row" if row_id is not None or cleaned_row_ids else "filter",
        "suggested_filters": suggested_filters or {},
        "sort_hint": {"sort_by": "transaction_date", "sort_dir": "desc"},
        "page_hint": 1,
        "highlight_seconds": int(highlight_seconds),
        "exists": True,
    }


def _repoint_transaction_links(db: Session, *, old_id: int, new_id: int) -> None:
    db.query(ReceiptProcessingTask).filter(ReceiptProcessingTask.transaction_id == int(old_id)).update(
        {"transaction_id": int(new_id)},
        synchronize_session=False,
    )
    db.query(TgChatMessage).filter(TgChatMessage.receipt_transaction_id == int(old_id)).update(
        {"receipt_transaction_id": int(new_id), "duplicate_status": "merged"},
        synchronize_session=False,
    )
    db.query(VerificationSuggestion).filter(VerificationSuggestion.transaction_id == int(old_id)).update(
        {"transaction_id": int(new_id)},
        synchronize_session=False,
    )
    db.query(AutomationSuggestion).filter(AutomationSuggestion.transaction_id == int(old_id)).update(
        {"transaction_id": int(new_id)},
        synchronize_session=False,
    )
    db.query(ReconciliationSuggestion).filter(ReconciliationSuggestion.transaction_id == int(old_id)).update(
        {"transaction_id": int(new_id)},
        synchronize_session=False,
    )
    db.query(ReceiptProcessingIncident).filter(ReceiptProcessingIncident.transaction_id == int(old_id)).update(
        {"transaction_id": int(new_id)},
        synchronize_session=False,
    )


def _reject_related_duplicate_suggestions(db: Session, *, primary_id: int, duplicate_id: int, approved_id: UUID) -> None:
    related = (
        db.query(DuplicateSuggestion)
        .filter(
            DuplicateSuggestion.id != approved_id,
            (
                (DuplicateSuggestion.primary_transaction_id == int(primary_id))
                | (DuplicateSuggestion.primary_transaction_id == int(duplicate_id))
                | (DuplicateSuggestion.duplicate_transaction_id == int(primary_id))
                | (DuplicateSuggestion.duplicate_transaction_id == int(duplicate_id))
            ),
        )
        .all()
    )
    for row in related:
        row.status = "rejected"
        db.add(row)


def _merge_duplicate_pair(db: Session, *, suggestion: DuplicateSuggestion) -> JsonDict:
    primary = db.query(Transaction).filter(Transaction.id == suggestion.primary_transaction_id).first()
    duplicate = db.query(Transaction).filter(Transaction.id == suggestion.duplicate_transaction_id).first()

    if not primary:
        raise ValueError("primary_transaction_not_found")

    if duplicate is None:
        suggestion.status = "approved"
        db.add(suggestion)
        db.commit()
        return {
            "applied": False,
            "idempotent": True,
            "primary_transaction_id": int(primary.id),
            "duplicate_transaction_id": int(suggestion.duplicate_transaction_id),
        }

    _merge_duplicate_transaction(
        primary,
        candidate_transaction_date=duplicate.transaction_date,
        candidate_operator_raw=duplicate.operator_raw or "",
        candidate_application_mapped=duplicate.application_mapped,
        candidate_balance_after=duplicate.balance_after,
        candidate_receiver_name=duplicate.receiver_name,
        candidate_receiver_card=duplicate.receiver_card,
        candidate_raw_message=duplicate.raw_message or "",
        candidate_is_p2p=duplicate.is_p2p,
        candidate_parsing_method=duplicate.parsing_method,
        candidate_parsing_confidence=duplicate.parsing_confidence,
        candidate_is_gpt=bool(duplicate.is_gpt_parsed),
        candidate_source_type=duplicate.source_type,
    )

    _repoint_transaction_links(db, old_id=int(duplicate.id), new_id=int(primary.id))
    _reject_related_duplicate_suggestions(
        db,
        primary_id=int(primary.id),
        duplicate_id=int(duplicate.id),
        approved_id=suggestion.id,
    )
    suggestion.status = "approved"
    db.add(suggestion)
    db.add(
        DuplicateMergeLog(
            fingerprint=duplicate.fingerprint or primary.fingerprint,
            existing_transaction_id=int(primary.id),
            source_chat_id=int(duplicate.source_chat_id) if duplicate.source_chat_id is not None else None,
            source_message_id=int(duplicate.source_message_id) if duplicate.source_message_id is not None else None,
            merged=True,
            candidate_method=duplicate.parsing_method,
            candidate_confidence=float(duplicate.parsing_confidence or 0.0) if duplicate.parsing_confidence is not None else None,
            existing_method=primary.parsing_method,
            existing_confidence=float(primary.parsing_confidence or 0.0) if primary.parsing_confidence is not None else None,
            details_json=json.dumps(
                {
                    "source": "agent_confirm",
                    "suggestion_id": str(suggestion.id),
                    "duplicate_transaction_id": int(duplicate.id),
                },
                ensure_ascii=False,
            ),
        )
    )
    db.delete(duplicate)
    db.commit()
    db.refresh(primary)

    return {
        "applied": True,
        "idempotent": False,
        "primary_transaction_id": int(primary.id),
        "duplicate_transaction_id": int(suggestion.duplicate_transaction_id),
        "navigation_target": _serialize_navigation_for_transactions(
            row_id=int(primary.id),
            row_ids=[int(primary.id)],
            column_id="amount",
            highlight_seconds=5,
        ),
    }


def _confirm_duplicate_merge(db: Session, *, args: JsonDict) -> JsonDict:
    suggestion_ids = [str(item) for item in (args.get("suggestion_ids") or []) if str(item).strip()]
    if not suggestion_ids:
        raise ValueError("no_duplicate_suggestions")

    applied: List[JsonDict] = []
    skipped = 0
    for raw_id in suggestion_ids:
        suggestion = db.get(DuplicateSuggestion, UUID(str(raw_id)))
        if not suggestion:
            skipped += 1
            continue
        applied.append(_merge_duplicate_pair(db, suggestion=suggestion))

    merged_rows = [item for item in applied if item.get("applied")]
    primary_ids = [int(item["primary_transaction_id"]) for item in applied if item.get("primary_transaction_id") is not None]
    message = (
        f"Подтвердил объединение дублей. Применено: {len(merged_rows)}. "
        f"Без повторного действия: {len(applied) - len(merged_rows)}. Пропущено: {skipped}."
    )
    return {
        "message": message,
        "cards": [
            {
                "type": "result",
                "title": "Объединение дублей выполнено",
                "body": message,
                "payload": {
                    "applied": len(merged_rows),
                    "idempotent": len(applied) - len(merged_rows),
                    "skipped": skipped,
                },
                "details": applied,
            }
        ],
        "navigation_targets": [
            _serialize_navigation_for_transactions(
                row_id=primary_ids[0] if primary_ids else None,
                row_ids=primary_ids,
                column_id="amount",
                highlight_seconds=5,
            )
        ] if primary_ids else [],
        "confirmation_result": {
            "action": "merge_duplicates",
            "applied": len(merged_rows),
            "idempotent": len(applied) - len(merged_rows),
            "skipped": skipped,
            "items": applied,
        },
    }


def _message_payload_from_cache_row(row: TgChatMessage) -> JsonDict:
    raw = _load_json(row.raw_json)
    content = raw.get("content") if isinstance(raw.get("content"), dict) else {}
    content_type = str(content.get("@type") or raw.get("content_type") or row.content_type or "")

    payload: JsonDict = {
        "raw_text": row.text or "",
        "source_type": "AUTO",
        "source_chat_id": int(row.chat_id),
        "source_message_id": int(row.message_id),
    }

    if content_type == "messageDocument":
        document = content.get("document") if isinstance(content.get("document"), dict) else {}
        document_file = document.get("document") if isinstance(document.get("document"), dict) else {}
        payload["document"] = {
            "file_id": document_file.get("id") or document.get("file_id"),
            "mime_type": document.get("mime_type") or raw.get("mime_type"),
            "file_name": document.get("file_name") or raw.get("file_name"),
            "caption": _extract_formatted_text(content.get("caption")) or row.text or "",
        }
    elif content_type == "messagePhoto":
        photo = content.get("photo") if isinstance(content.get("photo"), dict) else {}
        sizes = photo.get("sizes") if isinstance(photo.get("sizes"), list) else []
        file_id = None
        for item in reversed(sizes):
            if not isinstance(item, dict):
                continue
            photo_file = item.get("photo") if isinstance(item.get("photo"), dict) else {}
            file_id = photo_file.get("id") or item.get("file_id") or file_id
            if file_id:
                break
        payload["image"] = {
            "file_id": file_id,
            "mime_type": "image/jpeg",
            "caption": _extract_formatted_text(content.get("caption")) or row.text or "",
        }

    return payload


def _confirm_receipt_reparse(db: Session, *, args: JsonDict) -> JsonDict:
    chat_id = int(args.get("chat_id"))
    message_id = int(args.get("message_id"))
    row = (
        db.query(TgChatMessage)
        .filter(TgChatMessage.chat_id == chat_id, TgChatMessage.message_id == message_id)
        .first()
    )
    if not row:
        raise ValueError("message_not_found")

    task_data = _message_payload_from_cache_row(row)
    task_id = queue_receipt_task(task_data, force=True)
    message = f"Повторный разбор поставлен в очередь для сообщения {chat_id}/{message_id}."
    return {
        "message": message,
        "cards": [
            {
                "type": "result",
                "title": "Повторный разбор запущен",
                "body": message,
                "payload": {"chat_id": chat_id, "message_id": message_id, "task_id": task_id},
                "details": task_data,
            }
        ],
        "navigation_targets": [
            _serialize_navigation_for_transactions(
                column_id="raw_message",
                suggested_filters={"source_chat_ids": [chat_id], "search": str(message_id)},
                highlight_seconds=4,
            )
        ],
        "confirmation_result": {
            "action": "reparse_receipt",
            "task_id": task_id,
            "chat_id": chat_id,
            "message_id": message_id,
        },
    }


def _confirm_report_publish(db: Session, *, args: JsonDict, actor_user_id: int) -> JsonDict:
    report_id = UUID(str(args.get("report_id")))
    report = publish_report(db, report_id=report_id, actor_user_id=actor_user_id)
    if not report:
        raise ValueError("report_not_found")

    message = "Командный отчет опубликован и добавлен в уведомления."
    return {
        "message": message,
        "cards": [_serialize_report_card(report)],
        "navigation_targets": [],
        "report_id": report.get("id"),
        "confirmation_result": {
            "action": "publish_report",
            "report_id": report.get("id"),
            "published": True,
        },
    }


def execute_confirmation_for_run(db: Session, *, run: AgentRun, current_user: JsonDict) -> JsonDict:
    existing = _already_confirmed_payload(run)
    if existing:
        return {
            "message": str(existing.get("message") or "Действие уже подтверждено."),
            "cards": existing.get("cards") or [],
            "navigation_targets": existing.get("navigation_targets") or [],
            "confirmation_result": existing,
        }

    payload = _confirmation_payload(run)
    action = str(payload.get("action") or "").strip()
    args = payload.get("args") if isinstance(payload.get("args"), dict) else {}

    if action == "merge_duplicates":
        return _confirm_duplicate_merge(db, args=args)
    if action == "reparse_receipt":
        return _confirm_receipt_reparse(db, args=args)
    if action == "publish_report":
        return _confirm_report_publish(
            db,
            args=args,
            actor_user_id=int(current_user.get("id") or current_user.get("user_id") or 0),
        )
    raise ValueError("confirmation_action_not_supported")
