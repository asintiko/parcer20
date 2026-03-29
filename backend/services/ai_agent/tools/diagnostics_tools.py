from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import (
    DuplicateSuggestion,
    MonitoredBotChat,
    ReceiptProcessingTask,
    TgHistoryCursor,
    Transaction,
)


async def db_inspector(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> Dict[str, Any]:
    summary = {
        "transactions": db.query(func.count(Transaction.id)).scalar() or 0,
        "failed_receipt_tasks": db.query(func.count(ReceiptProcessingTask.id)).filter(ReceiptProcessingTask.status == "failed").scalar() or 0,
        "pending_duplicate_suggestions": db.query(func.count(DuplicateSuggestion.id)).filter(DuplicateSuggestion.status == "pending").scalar() or 0,
    }
    return {
        "summary": "Подготовил краткий срез по системе.",
        "assistant_message": "Подготовил краткий срез по системе.",
        "cards": [
            {
                "type": "result",
                "title": "Состояние системы",
                "body": "Проверил общие показатели по транзакциям и очередям обработки.",
                "payload": summary,
                "details": summary,
            }
        ],
    }


async def duplicate_detector(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> Dict[str, Any]:
    items = (
        db.query(DuplicateSuggestion)
        .filter(DuplicateSuggestion.status == "pending")
        .order_by(DuplicateSuggestion.created_at.desc())
        .limit(int(args.get("limit") or 10))
        .all()
    )
    payload = [
        {
            "id": str(item.id),
            "primary_transaction_id": int(item.primary_transaction_id),
            "duplicate_transaction_id": int(item.duplicate_transaction_id),
            "confidence": item.confidence,
            "reasoning": item.reasoning,
        }
        for item in items
    ]
    return {
        "summary": f"Найдено кандидатов на дубликаты: {len(payload)}",
        "cards": [
            {
                "type": "result",
                "title": "Подозрение на дубликаты",
                "body": f"Найдено кандидатов на проверку: {len(payload)}.",
                "payload": payload,
                "details": payload,
            }
        ],
    }


async def processing_errors_analyzer(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> Dict[str, Any]:
    items = (
        db.query(ReceiptProcessingTask)
        .filter(ReceiptProcessingTask.status == "failed")
        .order_by(ReceiptProcessingTask.updated_at.desc())
        .limit(int(args.get("limit") or 20))
        .all()
    )
    payload = [
        {
            "id": int(item.id),
            "chat_id": int(item.chat_id),
            "message_id": int(item.message_id),
            "error": item.error,
            "raw_message": item.raw_message,
        }
        for item in items
    ]
    return {
        "summary": f"Найдено ошибок парсинга: {len(payload)}",
        "cards": [
            {
                "type": "result",
                "title": "Ошибки обработки",
                "body": f"Нашел ошибок обработки: {len(payload)}.",
                "payload": payload,
                "details": payload,
            }
        ],
    }


async def source_health_check(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> Dict[str, Any]:
    monitored = db.query(MonitoredBotChat).order_by(MonitoredBotChat.chat_id.asc()).all()
    cursors = {int(item.chat_id): item for item in db.query(TgHistoryCursor).all()}
    payload = []
    for chat in monitored:
        cursor = cursors.get(int(chat.chat_id))
        payload.append({
            "chat_id": int(chat.chat_id),
            "chat_title": chat.chat_title,
            "chat_type": chat.chat_type,
            "enabled": bool(chat.enabled),
            "history_status": cursor.status if cursor else "not_started",
            "loaded_count": int(cursor.loaded_count) if cursor else 0,
            "history_error": cursor.error if cursor else None,
        })
    return {
        "summary": f"Проверено источников: {len(payload)}",
        "cards": [
            {
                "type": "result",
                "title": "Состояние источников",
                "body": f"Проверено источников: {len(payload)}.",
                "payload": payload,
                "details": payload,
            }
        ],
    }


async def fix_plan_builder(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> Dict[str, Any]:
    failed_count = db.query(func.count(ReceiptProcessingTask.id)).filter(ReceiptProcessingTask.status == "failed").scalar() or 0
    dup_count = db.query(func.count(DuplicateSuggestion.id)).filter(DuplicateSuggestion.status == "pending").scalar() or 0
    recommendations = []
    if failed_count:
        recommendations.append("Разобрать failed receipt processing tasks и перепарсить сообщения с сохраненным raw_message.")
    if dup_count:
        recommendations.append("Проверить pending duplicate suggestions и согласовать merge policy.")
    if not recommendations:
        recommendations.append("Критических накопленных проблем по текущим quick-check метрикам не обнаружено.")
    return {
        "summary": "Сформирован план действий",
        "cards": [
            {
                "type": "result",
                "title": "План действий",
                "body": "Подготовил список рекомендуемых шагов.",
                "payload": {"recommendations": recommendations},
                "details": {"recommendations": recommendations},
            }
        ],
    }
