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


def _esc(value: Any) -> str:
    text = str(value if value is not None else "")
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# Human-readable RU titles for the notification types we mirror to Telegram.
_NOTIFICATION_TITLES: Dict[str, str] = {
    "report_ready": "Отчёт готов",
    "report_assigned": "Назначен пункт отчёта",
    "weekly_report": "Еженедельный отчёт",
    "team_mention": "Упоминание в команде",
    "run_failed": "Сбой выполнения агента",
}


def _build_mirror_message(notification_type: str, payload: Optional[JsonDict]) -> str:
    """Compact Telegram-HTML message for an in-app notification (<3000 chars)."""
    data = payload or {}
    title = _NOTIFICATION_TITLES.get(notification_type, notification_type)
    lines = [f"🔔 <b>{_esc(title)}</b>"]
    name = data.get("name") or data.get("title")
    if name:
        lines.append(_esc(name))
    body = data.get("text") or data.get("message") or data.get("body")
    if body:
        lines.append("")
        lines.append(_esc(str(body)))
    elif not name:
        # Generic fallback: compact preview of the payload keys.
        preview = ", ".join(
            f"{_esc(k)}: {_esc(v)}"
            for k, v in list(data.items())[:6]
            if not isinstance(v, (dict, list))
        )
        if preview:
            lines.append("")
            lines.append(_esc(preview))
    text = "\n".join(lines)
    if len(text) > 3000:
        text = text[:2990].rstrip() + "\n…"
    return text


def _mirror_notification_to_channel(notification_type: str, payload: Optional[JsonDict]) -> None:
    """Best-effort mirror of an in-app notification to the receipt-log channel.

    Never raises. Skips `routine_report` (already delivered to the channel by
    the routine itself) to avoid double-posting.
    """
    if notification_type == "routine_report":
        return
    try:
        from services.receipt_logger import post_plain

        post_plain(_build_mirror_message(notification_type, payload))
    except Exception:  # noqa: BLE001
        pass


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
    _mirror_notification_to_channel(notification_type, payload)
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
