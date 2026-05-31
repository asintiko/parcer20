from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from database.models import ReceiptProcessingIncident
from services.ai_agent.notification_service import create_notification


AUTH_INCIDENT_CHAT_ID = str(os.getenv('AUTH_INCIDENT_CHAT_ID', '')).strip()
AUTH_INCIDENT_TOPIC_ID = str(os.getenv('AUTH_INCIDENT_TOPIC_ID', '')).strip()


JsonDict = Dict[str, Any]


def _dump_json(payload: Optional[JsonDict]) -> str:
    return json.dumps(payload or {}, ensure_ascii=False)


def _load_json(value: Optional[str]) -> JsonDict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def serialize_incident(row: ReceiptProcessingIncident) -> JsonDict:
    return {
        'id': str(row.id),
        'chat_id': int(row.chat_id),
        'message_id': int(row.message_id) if row.message_id is not None else None,
        'transaction_id': int(row.transaction_id) if row.transaction_id is not None else None,
        'task_id': int(row.task_id) if row.task_id is not None else None,
        'incident_type': row.incident_type,
        'severity': row.severity,
        'status': row.status,
        'reason_code': row.reason_code,
        'reason_text': row.reason_text,
        'payload': _load_json(row.payload_json),
        'first_seen_at': row.first_seen_at.isoformat() if row.first_seen_at else None,
        'last_seen_at': row.last_seen_at.isoformat() if row.last_seen_at else None,
        'notified_at': row.notified_at.isoformat() if row.notified_at else None,
        'resolved_at': row.resolved_at.isoformat() if row.resolved_at else None,
    }


def upsert_receipt_incident(
    db: Session,
    *,
    chat_id: int,
    incident_type: str,
    severity: str = 'medium',
    status: str = 'open',
    message_id: Optional[int] = None,
    transaction_id: Optional[int] = None,
    task_id: Optional[int] = None,
    reason_code: Optional[str] = None,
    reason_text: Optional[str] = None,
    payload: Optional[JsonDict] = None,
    notify: bool = True,
    auto_commit: bool = True,
) -> ReceiptProcessingIncident:
    now = datetime.utcnow()
    row = (
        db.query(ReceiptProcessingIncident)
        .filter(
            ReceiptProcessingIncident.chat_id == int(chat_id),
            ReceiptProcessingIncident.message_id == int(message_id) if message_id is not None else ReceiptProcessingIncident.message_id.is_(None),
            ReceiptProcessingIncident.incident_type == str(incident_type),
            ReceiptProcessingIncident.status.in_(['open', 'acknowledged', 'ignored']),
        )
        .order_by(ReceiptProcessingIncident.last_seen_at.desc())
        .first()
    )
    if row is None:
        row = ReceiptProcessingIncident(
            chat_id=int(chat_id),
            message_id=int(message_id) if message_id is not None else None,
            transaction_id=int(transaction_id) if transaction_id is not None else None,
            task_id=int(task_id) if task_id is not None else None,
            incident_type=str(incident_type),
            severity=str(severity),
            status=str(status),
            reason_code=reason_code,
            reason_text=reason_text,
            payload_json=_dump_json(payload),
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(row)
    else:
        row.transaction_id = int(transaction_id) if transaction_id is not None else row.transaction_id
        row.task_id = int(task_id) if task_id is not None else row.task_id
        row.severity = str(severity)
        row.status = str(status or row.status)
        row.reason_code = reason_code or row.reason_code
        row.reason_text = reason_text or row.reason_text
        row.payload_json = _dump_json(payload or _load_json(row.payload_json))
        row.last_seen_at = now
        if status == 'resolved':
            row.resolved_at = now
        db.add(row)
    if auto_commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()

    if notify and row.notified_at is None and row.status in {'open', 'acknowledged'}:
        notification_payload = {
            'incident_id': str(row.id),
            'chat_id': int(row.chat_id),
            'message_id': int(row.message_id) if row.message_id is not None else None,
            'incident_type': row.incident_type,
            'severity': row.severity,
            'reason_text': row.reason_text,
            'reason_code': row.reason_code,
            'ops_chat_id': AUTH_INCIDENT_CHAT_ID or None,
            'ops_topic_id': AUTH_INCIDENT_TOPIC_ID or None,
        }
        create_notification(
            db,
            scope='team',
            notification_type='receipt_processing_incident',
            payload=notification_payload,
        )
        try:
            from services.auth_bot_service import publish_auth_event

            asyncio.run(
                publish_auth_event(
                    'receipt_incident',
                    {
                        **notification_payload,
                        'title': _incident_title(row),
                        'summary': _incident_summary(row),
                    },
                )
            )
        except Exception:
            pass
        row.notified_at = datetime.utcnow()
        db.add(row)
        if auto_commit:
            db.commit()
            db.refresh(row)
        else:
            db.flush()
    return row


def _incident_title(row: ReceiptProcessingIncident) -> str:
    mapping = {
        'failed_parse': 'Ошибка обработки чека',
        'missing_in_db': 'Чек не попал в таблицу',
        'duplicate_without_row': 'Сообщение ушло в дубликат',
        'cursor_stale': 'Проблема синхронизации',
        'cache_gap': 'Пробел в кеше',
        'manual_review': 'Требуется ручная проверка',
    }
    return mapping.get(str(row.incident_type), 'Инцидент обработки чеков')


def _incident_summary(row: ReceiptProcessingIncident) -> str:
    return row.reason_text or f'chat_id={row.chat_id} message_id={row.message_id or "-"}'
