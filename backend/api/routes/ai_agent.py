from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import get_current_app_user, get_scope_context_optional, require_admin_user
from database.connection import SessionLocal, get_db_session
from database.models import AgentReportItem, AgentRun
from services.ai_agent import AgentOrchestrator
from services.ai_agent.notification_service import (
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    serialize_notification,
)
from services.ai_agent.confirm_service import execute_confirmation_for_run
from services.ai_agent.report_service import (
    build_previous_week_window,
    claim_report_item,
    generate_report,
    get_report,
    list_reports,
    reassign_report_item,
    release_report_item,
)
from services.ai_agent.session_service import (
    create_message,
    create_run,
    create_thread,
    create_run_event,
    get_thread,
    list_messages,
    list_run_events,
    list_threads,
    purge_thread,
    restore_thread,
    serialize_run,
    serialize_thread,
    trash_thread,
    update_thread,
    update_run,
    archive_thread,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])
_orchestrator = AgentOrchestrator()


class ThreadCreateRequest(BaseModel):
    title: Optional[str] = Field(default="Новый диалог", max_length=255)
    context: Optional[Dict[str, Any]] = None


class ThreadMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=12000)
    requested_tool: Optional[str] = Field(default=None, max_length=80)
    metadata: Optional[Dict[str, Any]] = None


class ThreadUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    context: Optional[Dict[str, Any]] = None


class GenerateReportRequest(BaseModel):
    thread_id: Optional[UUID] = None
    team: bool = False
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None


class ReportItemReassignRequest(BaseModel):
    assignee_user_id: int


class ReportActionsConfirmRequest(BaseModel):
    item_ids: List[UUID] = Field(default_factory=list)
    action: str = Field(default="resolve_items")


def _user_id_from_snapshot(current_user: dict) -> int:
    return int(current_user.get("id") or current_user.get("user_id") or 0)


async def _run_agent_message_in_background(
    *,
    thread_id: UUID,
    run_id: UUID,
    user_snapshot: Dict[str, Any],
    scope_snapshot: Optional[Dict[str, Any]],
    user_text: str,
    requested_tool: Optional[str],
) -> None:
    with SessionLocal() as db:
        try:
            await _orchestrator.handle_message(
                db=db,
                thread_id=thread_id,
                run_id=run_id,
                current_user=user_snapshot,
                scope=scope_snapshot,
                user_text=user_text,
                requested_tool=requested_tool,
            )
        except Exception as exc:  # noqa: BLE001
            update_run(
                db,
                run_id=run_id,
                status="failed",
                progress={"step": "failed", "percent": 100},
                error_text=str(exc),
            )
            create_run_event(
                db,
                run_id=run_id,
                event_type="failed",
                label="Выполнение завершилось ошибкой",
                status="failed",
                payload={"error": str(exc)},
            )
            create_message(
                db,
                thread_id=thread_id,
                run_id=run_id,
                role="system",
                message_type="warning",
                content={"message": f"Ошибка агента: {exc}"},
            )


@router.post("/threads")
async def create_agent_thread(
    payload: ThreadCreateRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    thread = create_thread(db, user_id=user_id, title=payload.title or "Новый диалог", context=payload.context)
    return serialize_thread(thread)


@router.get("/threads")
async def get_agent_threads(
    view: str = Query(default="active", pattern="^(active|archived|trash)$"),
    search: Optional[str] = Query(default=None, max_length=255),
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    return list_threads(db, user_id=user_id, view=view, search=search)


@router.get("/threads/{thread_id}")
async def get_agent_thread(
    thread_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    thread = get_thread(db, thread_id=thread_id, user_id=user_id, include_archived=True, include_deleted=True)
    if not thread:
        raise HTTPException(status_code=404, detail="thread_not_found")
    runs = (
        db.query(AgentRun)
        .filter(AgentRun.thread_id == thread_id)
        .order_by(AgentRun.created_at.desc())
        .limit(20)
        .all()
    )
    return {
        **serialize_thread(thread),
        "messages": list_messages(db, thread_id=thread_id, limit=500),
        "runs": [serialize_run(row) for row in runs],
        "run_events": list_run_events(db, run_ids=[row.id for row in runs]),
    }


@router.patch("/threads/{thread_id}")
async def patch_agent_thread(
    thread_id: UUID,
    payload: ThreadUpdateRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    thread = get_thread(db, thread_id=thread_id, user_id=user_id, include_archived=True, include_deleted=True)
    if not thread:
        raise HTTPException(status_code=404, detail="thread_not_found")
    return serialize_thread(update_thread(db, thread=thread, title=payload.title, context=payload.context))


@router.post("/threads/{thread_id}/archive")
async def archive_agent_thread(
    thread_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    thread = get_thread(db, thread_id=thread_id, user_id=user_id, include_archived=True, include_deleted=True)
    if not thread:
        raise HTTPException(status_code=404, detail="thread_not_found")
    return serialize_thread(archive_thread(db, thread=thread, actor_user_id=user_id))


@router.post("/threads/{thread_id}/trash")
async def trash_agent_thread_route(
    thread_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    thread = get_thread(db, thread_id=thread_id, user_id=user_id, include_archived=True, include_deleted=True)
    if not thread:
        raise HTTPException(status_code=404, detail="thread_not_found")
    return serialize_thread(trash_thread(db, thread=thread, actor_user_id=user_id))


@router.post("/threads/{thread_id}/restore")
async def restore_agent_thread_route(
    thread_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    thread = get_thread(db, thread_id=thread_id, user_id=user_id, include_archived=True, include_deleted=True)
    if not thread:
        raise HTTPException(status_code=404, detail="thread_not_found")
    return serialize_thread(restore_thread(db, thread=thread))


@router.post("/threads/{thread_id}/purge")
async def purge_agent_thread_route(
    thread_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    thread = get_thread(db, thread_id=thread_id, user_id=user_id, include_archived=True, include_deleted=True)
    if not thread:
        raise HTTPException(status_code=404, detail="thread_not_found")
    purge_thread(db, thread=thread)
    return {"ok": True, "thread_id": str(thread_id)}


@router.post("/threads/{thread_id}/messages")
async def post_agent_message(
    thread_id: UUID,
    payload: ThreadMessageRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
    scope: Optional[Dict[str, Any]] = Depends(get_scope_context_optional),
):
    user_id = _user_id_from_snapshot(current_user)
    thread = get_thread(db, thread_id=thread_id, user_id=user_id)
    if not thread:
        raise HTTPException(status_code=404, detail="thread_not_found")

    user_message = create_message(
        db,
        thread_id=thread_id,
        role="user",
        message_type="text",
        content={"message": payload.text, "metadata": payload.metadata or {}},
    )
    run = create_run(
        db,
        thread_id=thread_id,
        user_id=user_id,
        tool_name=payload.requested_tool,
        status="queued",
        progress={"step": "queued", "percent": 0},
    )
    asyncio.create_task(
        _run_agent_message_in_background(
            thread_id=thread_id,
            run_id=run.id,
            user_snapshot=dict(current_user),
            scope_snapshot=dict(scope) if isinstance(scope, dict) else None,
            user_text=payload.text,
            requested_tool=payload.requested_tool,
        )
    )
    return {
        "accepted": True,
        "thread_id": str(thread_id),
        "message": {"id": str(user_message.id), "created_at": user_message.created_at.isoformat() if user_message.created_at else None},
        "run": serialize_run(run),
    }


@router.get("/stream/{thread_id}")
async def stream_agent_thread(
    thread_id: UUID,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    thread = get_thread(db, thread_id=thread_id, user_id=user_id)
    if not thread:
        raise HTTPException(status_code=404, detail="thread_not_found")

    async def event_generator():
        seen_message_ids: set[str] = set()
        seen_run_keys: set[str] = set()
        seen_run_event_ids: set[str] = set()
        while True:
            if await request.is_disconnected():
                break
            with SessionLocal() as session:
                messages = list_messages(session, thread_id=thread_id, limit=500)
                for message in messages:
                    if message["id"] in seen_message_ids:
                        continue
                    seen_message_ids.add(message["id"])
                    yield f"event: message\ndata: {json.dumps(message, ensure_ascii=False)}\n\n"
                runs = (
                    session.query(AgentRun)
                    .filter(AgentRun.thread_id == thread_id)
                    .order_by(AgentRun.updated_at.desc())
                    .limit(20)
                    .all()
                )
                for row in runs:
                    serialized = serialize_run(row)
                    cache_key = f"{serialized['id']}:{serialized['status']}:{serialized['updated_at']}"
                    if cache_key in seen_run_keys:
                        continue
                    seen_run_keys.add(cache_key)
                    yield f"event: run\ndata: {json.dumps(serialized, ensure_ascii=False)}\n\n"
                run_ids = [row.id for row in runs]
                for event in list_run_events(session, run_ids=run_ids):
                    if event["id"] in seen_run_event_ids:
                        continue
                    seen_run_event_ids.add(event["id"])
                    yield f"event: run_event\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            yield "event: heartbeat\ndata: {}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/notifications")
async def get_agent_notifications(
    scope: Optional[str] = Query(default=None, pattern="^(team|personal)$"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    return list_notifications(db, user_id=user_id, scope=scope, limit=limit)


@router.post("/notifications/{notification_id}/read")
async def read_agent_notification(
    notification_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    row = mark_notification_read(db, notification_id=notification_id, user_id=user_id)
    if not row:
        raise HTTPException(status_code=404, detail="notification_not_found")
    return serialize_notification(row)


@router.post("/notifications/read-all")
async def read_all_agent_notifications(
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    return {"updated": mark_all_notifications_read(db, user_id=user_id)}


@router.post("/report-items/{item_id}/claim")
async def claim_agent_report_item(
    item_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    try:
        item = claim_report_item(db, item_id=item_id, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not item:
        raise HTTPException(status_code=404, detail="report_item_not_found")
    return item


@router.post("/report-items/{item_id}/release")
async def release_agent_report_item(
    item_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    try:
        item = release_report_item(db, item_id=item_id, user_id=user_id, force=False)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not item:
        raise HTTPException(status_code=404, detail="report_item_not_found")
    return item


@router.post("/report-items/{item_id}/reassign")
async def reassign_agent_report_item(
    item_id: UUID,
    payload: ReportItemReassignRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
):
    item = reassign_report_item(db, item_id=item_id, assignee_user_id=payload.assignee_user_id)
    if not item:
        raise HTTPException(status_code=404, detail="report_item_not_found")
    return item


@router.post("/reports/generate")
async def generate_agent_report(
    payload: GenerateReportRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    report = generate_report(
        db,
        created_by_user_id=user_id,
        thread_id=payload.thread_id,
        scope="team" if payload.team else "personal",
        period_start=payload.period_start,
        period_end=payload.period_end,
        publish_team_notification=payload.team,
    )
    return report


@router.get("/reports")
async def get_agent_reports(
    include_team: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    return list_reports(db, user_id=user_id, include_team=include_team, limit=limit)


@router.get("/reports/{report_id}")
async def get_agent_report(
    report_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    report = get_report(db, report_id=report_id, user_id=user_id)
    if not report:
        raise HTTPException(status_code=404, detail="report_not_found")
    return report


@router.post("/reports/{report_id}/actions/preview")
async def preview_agent_report_actions(
    report_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    report = get_report(db, report_id=report_id, user_id=user_id)
    if not report:
        raise HTTPException(status_code=404, detail="report_not_found")
    actions = [
        item.get("suggested_action")
        for item in report.get("items", [])
        if item.get("status") in {"open", "released", "claimed"} and item.get("suggested_action")
    ]
    return {"report_id": str(report_id), "actions": actions, "count": len(actions)}


@router.post("/reports/{report_id}/actions/confirm")
async def confirm_agent_report_actions(
    report_id: UUID,
    payload: ReportActionsConfirmRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    user_id = _user_id_from_snapshot(current_user)
    report = get_report(db, report_id=report_id, user_id=user_id)
    if not report:
        raise HTTPException(status_code=404, detail="report_not_found")
    updated = 0
    if payload.action == "resolve_items" and payload.item_ids:
        rows = db.query(AgentReportItem).filter(AgentReportItem.report_id == report_id, AgentReportItem.id.in_(payload.item_ids)).all()
        for row in rows:
            row.status = "resolved"
            row.resolved_at = datetime.utcnow()
            db.add(row)
            updated += 1
        db.commit()
    return {"report_id": str(report_id), "updated": updated, "action": payload.action}


@router.post("/runs/{run_id}/confirm")
async def confirm_agent_run(
    run_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
):
    row = db.get(AgentRun, run_id)
    user_id = _user_id_from_snapshot(current_user)
    if not row or int(row.created_by_user_id) != user_id:
        raise HTTPException(status_code=404, detail="run_not_found")
    if row.requires_confirmation:
        update_run(
            db,
            run_id=run_id,
            status="processing",
            progress={"step": "confirming", "percent": 92},
            requires_confirmation=True,
        )
        create_run_event(
            db,
            run_id=run_id,
            event_type="tool_started",
            label="Применяю подтвержденное действие",
            status="running",
            payload={"confirmed": True},
        )
        try:
            confirmation_result = execute_confirmation_for_run(db, run=row, current_user=current_user)
        except ValueError as exc:
            updated = update_run(
                db,
                run_id=run_id,
                status="failed",
                progress={"step": "failed", "percent": 100},
                error_text=str(exc),
                requires_confirmation=False,
            )
            create_run_event(
                db,
                run_id=run_id,
                event_type="failed",
                label="Подтверждение завершилось ошибкой",
                status="failed",
                payload={"error": str(exc)},
            )
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        assistant_payload = {
            "message": confirmation_result.get("message") or "Действие подтверждено.",
            "cards": confirmation_result.get("cards") or [],
            "navigation_targets": confirmation_result.get("navigation_targets") or [],
            "requires_confirmation": False,
            "confirmation_result": confirmation_result.get("confirmation_result") or {},
        }
        create_message(
            db,
            thread_id=row.thread_id,
            run_id=run_id,
            role="assistant",
            message_type="text",
            content=assistant_payload,
        )
        create_run_event(
            db,
            run_id=run_id,
            event_type="tool_finished",
            label="Подтвержденное действие применено",
            status="completed",
            payload=confirmation_result.get("confirmation_result") or {"confirmed": True},
        )
        create_run_event(
            db,
            run_id=run_id,
            event_type="completed",
            label="Готово",
            status="completed",
            payload={"confirmed": True},
        )
        updated = update_run(
            db,
            run_id=run_id,
            status="completed",
            progress={"step": "completed", "percent": 100},
            result=assistant_payload,
            requires_confirmation=False,
            error_text=None,
        )
        return serialize_run(updated or row)
    return serialize_run(row)
