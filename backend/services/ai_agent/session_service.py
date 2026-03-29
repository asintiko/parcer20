from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import or_
from sqlalchemy.orm import Session

from database.models import AgentMessage, AgentRun, AgentRunEvent, AgentThread


JsonDict = Dict[str, Any]
THREAD_RETENTION_DAYS = 30


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


def serialize_thread(row: AgentThread, latest_run: Optional[AgentRun] = None) -> JsonDict:
    return {
        "id": str(row.id),
        "created_by_user_id": int(row.created_by_user_id),
        "title": row.title,
        "context": _load_json(row.context_json),
        "last_message_preview": row.last_message_preview,
        "latest_run_status": latest_run.status if latest_run else None,
        "latest_run_tool_name": latest_run.tool_name if latest_run else None,
        "latest_run_updated_at": latest_run.updated_at.isoformat() if latest_run and latest_run.updated_at else None,
        "latest_run_requires_confirmation": bool(latest_run.requires_confirmation) if latest_run else False,
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
        "purge_after": row.purge_after.isoformat() if row.purge_after else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_message(row: AgentMessage) -> JsonDict:
    return {
        "id": str(row.id),
        "thread_id": str(row.thread_id),
        "run_id": str(row.run_id) if row.run_id else None,
        "role": row.role,
        "message_type": row.message_type,
        "content": _load_json(row.content_json),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def serialize_run(row: AgentRun) -> JsonDict:
    return {
        "id": str(row.id),
        "thread_id": str(row.thread_id),
        "created_by_user_id": int(row.created_by_user_id),
        "status": row.status,
        "tool_name": row.tool_name,
        "progress": _load_json(row.progress_json),
        "result": _load_json(row.result_json) if row.result_json else None,
        "error_text": row.error_text,
        "requires_confirmation": bool(row.requires_confirmation),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_run_event(row: AgentRunEvent) -> JsonDict:
    return {
        "id": str(row.id),
        "run_id": str(row.run_id),
        "event_type": row.event_type,
        "label": row.label,
        "status": row.status,
        "payload": _load_json(row.payload_json),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_threads(db: Session, *, user_id: int, view: str = "active", search: Optional[str] = None) -> List[JsonDict]:
    query = db.query(AgentThread).filter(AgentThread.created_by_user_id == int(user_id))
    normalized_view = str(view or "active").strip().lower()
    if normalized_view == "archived":
        query = query.filter(AgentThread.archived_at.isnot(None), AgentThread.deleted_at.is_(None))
    elif normalized_view == "trash":
        query = query.filter(AgentThread.deleted_at.isnot(None))
    else:
        query = query.filter(AgentThread.archived_at.is_(None), AgentThread.deleted_at.is_(None))
    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                AgentThread.title.ilike(pattern),
                AgentThread.last_message_preview.ilike(pattern),
            )
        )
    rows = query.order_by(AgentThread.updated_at.desc(), AgentThread.created_at.desc()).all()
    thread_ids = [row.id for row in rows]
    latest_run_by_thread: Dict[UUID, AgentRun] = {}
    if thread_ids:
        run_rows = (
            db.query(AgentRun)
            .filter(AgentRun.thread_id.in_(thread_ids))
            .order_by(AgentRun.thread_id.asc(), AgentRun.created_at.desc())
            .all()
        )
        for run in run_rows:
            latest_run_by_thread.setdefault(run.thread_id, run)
    return [serialize_thread(row, latest_run=latest_run_by_thread.get(row.id)) for row in rows]


def get_thread(
    db: Session,
    *,
    thread_id: UUID,
    user_id: int,
    include_archived: bool = True,
    include_deleted: bool = False,
) -> AgentThread | None:
    query = db.query(AgentThread).filter(AgentThread.id == thread_id, AgentThread.created_by_user_id == int(user_id))
    if not include_archived:
        query = query.filter(AgentThread.archived_at.is_(None))
    if not include_deleted:
        query = query.filter(AgentThread.deleted_at.is_(None))
    return query.first()


def create_thread(
    db: Session,
    *,
    user_id: int,
    title: str = "Новый диалог",
    context: Optional[JsonDict] = None,
) -> AgentThread:
    now = datetime.utcnow()
    row = AgentThread(
        id=uuid4(),
        created_by_user_id=int(user_id),
        title=(title or "Новый диалог").strip()[:255] or "Новый диалог",
        context_json=_dump_json(context),
        archived_at=None,
        deleted_at=None,
        purge_after=None,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def touch_thread(db: Session, *, thread: AgentThread, title: Optional[str] = None, context: Optional[JsonDict] = None) -> AgentThread:
    if title is not None:
        thread.title = title.strip()[:255] or thread.title
    if context is not None:
        thread.context_json = _dump_json(context)
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def update_thread(
    db: Session,
    *,
    thread: AgentThread,
    title: Optional[str] = None,
    context: Optional[JsonDict] = None,
) -> AgentThread:
    return touch_thread(db, thread=thread, title=title, context=context)


def archive_thread(db: Session, *, thread: AgentThread, actor_user_id: int) -> AgentThread:
    thread.archived_at = datetime.utcnow()
    thread.archived_by_user_id = int(actor_user_id)
    thread.deleted_at = None
    thread.deleted_by_user_id = None
    thread.purge_after = None
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def trash_thread(db: Session, *, thread: AgentThread, actor_user_id: int, retention_days: int = THREAD_RETENTION_DAYS) -> AgentThread:
    now = datetime.utcnow()
    thread.deleted_at = now
    thread.deleted_by_user_id = int(actor_user_id)
    thread.purge_after = now + timedelta(days=max(1, int(retention_days or THREAD_RETENTION_DAYS)))
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def restore_thread(db: Session, *, thread: AgentThread) -> AgentThread:
    thread.archived_at = None
    thread.archived_by_user_id = None
    thread.deleted_at = None
    thread.deleted_by_user_id = None
    thread.purge_after = None
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def purge_thread(db: Session, *, thread: AgentThread) -> None:
    db.query(AgentRunEvent).filter(AgentRunEvent.run_id.in_(db.query(AgentRun.id).filter(AgentRun.thread_id == thread.id))).delete(synchronize_session=False)
    db.query(AgentMessage).filter(AgentMessage.thread_id == thread.id).delete(synchronize_session=False)
    db.query(AgentRun).filter(AgentRun.thread_id == thread.id).delete(synchronize_session=False)
    db.delete(thread)
    db.commit()


def purge_expired_threads(db: Session, *, limit: int = 100) -> int:
    now = datetime.utcnow()
    rows = (
        db.query(AgentThread)
        .filter(AgentThread.deleted_at.isnot(None), AgentThread.purge_after.isnot(None), AgentThread.purge_after < now)
        .order_by(AgentThread.purge_after.asc())
        .limit(max(1, min(int(limit), 1000)))
        .all()
    )
    count = 0
    for row in rows:
        thread_id = str(row.id)
        owner_id = int(row.created_by_user_id)
        purge_thread(db, thread=row)
        from services.access_control_service import write_audit_log
        write_audit_log(
            db,
            action="agent_thread_purge",
            success=True,
            user_id=owner_id,
            details={"thread_id": thread_id, "reason": "retention_expired"},
        )
        count += 1
    return count


def list_messages(db: Session, *, thread_id: UUID, limit: int = 200, after: Optional[str] = None) -> List[JsonDict]:
    query = db.query(AgentMessage).filter(AgentMessage.thread_id == thread_id)
    if after:
        try:
            after_id = UUID(str(after))
            query = query.filter(AgentMessage.id != after_id)
        except Exception:
            pass
    rows = query.order_by(AgentMessage.created_at.asc()).limit(max(1, min(int(limit), 500))).all()
    return [serialize_message(row) for row in rows]


def create_message(
    db: Session,
    *,
    thread_id: UUID,
    role: str,
    message_type: str,
    content: Optional[JsonDict] = None,
    run_id: Optional[UUID] = None,
) -> AgentMessage:
    preview = ""
    if isinstance(content, dict):
        preview = str(content.get("message") or content.get("summary") or "").strip()
    row = AgentMessage(
        id=uuid4(),
        thread_id=thread_id,
        run_id=run_id,
        role=role,
        message_type=message_type,
        content_json=_dump_json(content),
    )
    db.add(row)
    thread = db.get(AgentThread, thread_id)
    if thread:
        if preview:
            thread.last_message_preview = preview[:500]
        db.add(thread)
    db.commit()
    db.refresh(row)
    return row


def create_run(
    db: Session,
    *,
    thread_id: UUID,
    user_id: int,
    tool_name: Optional[str] = None,
    status: str = "queued",
    progress: Optional[JsonDict] = None,
    requires_confirmation: bool = False,
) -> AgentRun:
    row = AgentRun(
        id=uuid4(),
        thread_id=thread_id,
        created_by_user_id=int(user_id),
        tool_name=tool_name,
        status=status,
        progress_json=_dump_json(progress),
        requires_confirmation=requires_confirmation,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_run(
    db: Session,
    *,
    run_id: UUID,
    status: Optional[str] = None,
    progress: Optional[JsonDict] = None,
    result: Optional[JsonDict] = None,
    error_text: Optional[str] = None,
    requires_confirmation: Optional[bool] = None,
) -> AgentRun | None:
    row = db.get(AgentRun, run_id)
    if not row:
        return None
    if status is not None:
        row.status = status
    if progress is not None:
        row.progress_json = _dump_json(progress)
    if result is not None:
        row.result_json = _dump_json(result)
    if error_text is not None:
        row.error_text = error_text[:4000] if error_text else None
    if requires_confirmation is not None:
        row.requires_confirmation = bool(requires_confirmation)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_run_events(db: Session, *, run_ids: Iterable[UUID]) -> List[JsonDict]:
    run_ids_list = [item for item in run_ids]
    if not run_ids_list:
        return []
    rows = (
        db.query(AgentRunEvent)
        .filter(AgentRunEvent.run_id.in_(run_ids_list))
        .order_by(AgentRunEvent.created_at.asc())
        .all()
    )
    return [serialize_run_event(row) for row in rows]


def create_run_event(
    db: Session,
    *,
    run_id: UUID,
    event_type: str,
    label: str,
    status: str = "running",
    payload: Optional[JsonDict] = None,
) -> AgentRunEvent:
    row = AgentRunEvent(
        id=uuid4(),
        run_id=run_id,
        event_type=event_type,
        label=label[:255],
        status=status,
        payload_json=_dump_json(payload),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
