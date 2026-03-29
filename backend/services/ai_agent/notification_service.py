from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import or_
from sqlalchemy.orm import Session

from database.models import AgentNotification


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


def serialize_notification(row: AgentNotification) -> JsonDict:
    return {
        "id": str(row.id),
        "scope": row.scope,
        "user_id": int(row.user_id) if row.user_id is not None else None,
        "report_id": str(row.report_id) if row.report_id else None,
        "report_item_id": str(row.report_item_id) if row.report_item_id else None,
        "type": row.type,
        "payload": _load_json(row.payload_json),
        "is_read": bool(row.is_read),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "read_at": row.read_at.isoformat() if row.read_at else None,
    }


def create_notification(
    db: Session,
    *,
    scope: str,
    notification_type: str,
    payload: Optional[JsonDict] = None,
    user_id: Optional[int] = None,
    report_id: Optional[UUID] = None,
    report_item_id: Optional[UUID] = None,
) -> AgentNotification:
    row = AgentNotification(
        id=uuid4(),
        scope=scope,
        user_id=user_id,
        report_id=report_id,
        report_item_id=report_item_id,
        type=notification_type,
        payload_json=_dump_json(payload),
        is_read=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_notifications(db: Session, *, user_id: int, scope: Optional[str] = None, limit: int = 100) -> List[JsonDict]:
    query = db.query(AgentNotification).filter(
        or_(
            AgentNotification.scope == "team",
            AgentNotification.user_id == int(user_id),
        )
    )
    if scope in {"team", "personal"}:
        query = query.filter(AgentNotification.scope == scope)
    rows = query.order_by(AgentNotification.created_at.desc()).limit(max(1, min(int(limit), 500))).all()
    return [serialize_notification(row) for row in rows]


def mark_notification_read(db: Session, *, notification_id: UUID, user_id: int) -> AgentNotification | None:
    row = (
        db.query(AgentNotification)
        .filter(
            AgentNotification.id == notification_id,
            or_(AgentNotification.scope == "team", AgentNotification.user_id == int(user_id)),
        )
        .first()
    )
    if not row:
        return None
    row.is_read = True
    row.read_at = datetime.utcnow()
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def mark_all_notifications_read(db: Session, *, user_id: int) -> int:
    rows = (
        db.query(AgentNotification)
        .filter(
            AgentNotification.is_read.is_(False),
            or_(AgentNotification.scope == "team", AgentNotification.user_id == int(user_id)),
        )
        .all()
    )
    now = datetime.utcnow()
    for row in rows:
        row.is_read = True
        row.read_at = now
        db.add(row)
    db.commit()
    return len(rows)
