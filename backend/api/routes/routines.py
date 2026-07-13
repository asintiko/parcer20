"""Admin CRUD API for AI-agent routines (scheduled NL tasks)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import get_system_access_context, require_admin_user
from database.connection import get_db_session
from services.ai_agent import routine_service as rs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/routines", tags=["routines"])


class RoutineCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    task_prompt: str = Field(..., min_length=1, max_length=4000)
    cron: str = Field(default="0 12 * * 1", max_length=120)
    kind: str = Field(default="reconcile", pattern="^(reconcile|summary|custom|receipt_audit)$")
    description: Optional[str] = Field(default=None, max_length=1000)
    enabled: bool = True
    deliver_to_channel: bool = True
    deliver_to_chat: bool = True
    schedule_kind: Optional[str] = Field(default=None, pattern="^(recurring|once)$")
    run_at: Optional[str] = Field(default=None, max_length=40)


class RoutineUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    task_prompt: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    cron: Optional[str] = Field(default=None, max_length=120)
    kind: Optional[str] = Field(default=None, pattern="^(reconcile|summary|custom|receipt_audit)$")
    description: Optional[str] = Field(default=None, max_length=1000)
    enabled: Optional[bool] = None
    deliver_to_channel: Optional[bool] = None
    deliver_to_chat: Optional[bool] = None
    schedule_kind: Optional[str] = Field(default=None, pattern="^(recurring|once)$")
    run_at: Optional[str] = Field(default=None, max_length=40)


def _reschedule() -> None:
    """Re-sync the scheduler's dynamic routine jobs (best-effort)."""
    try:
        from services.ai_agent import get_agent_scheduler_service
        get_agent_scheduler_service().sync_routines()
    except Exception:
        logger.debug("routine reschedule skipped", exc_info=True)


@router.get("")
async def list_routines_route(
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> Dict[str, Any]:
    return {"routines": rs.list_routines(db)}


@router.post("")
async def create_routine_route(
    payload: RoutineCreateRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> Dict[str, Any]:
    try:
        row = rs.create_routine(
            db,
            name=payload.name,
            task_prompt=payload.task_prompt,
            cron=payload.cron,
            kind=payload.kind,
            description=payload.description,
            enabled=payload.enabled,
            deliver_to_channel=payload.deliver_to_channel,
            deliver_to_chat=payload.deliver_to_chat,
            created_by_user_id=int(current_user.get("id") or current_user.get("user_id") or 0) or None,
            schedule_kind=payload.schedule_kind or "recurring",
            run_at=payload.run_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _reschedule()
    return rs.serialize_routine(row)


@router.patch("/{routine_id}")
async def update_routine_route(
    routine_id: UUID,
    payload: RoutineUpdateRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> Dict[str, Any]:
    routine = rs.get_routine(db, routine_id)
    if routine is None:
        raise HTTPException(status_code=404, detail="routine_not_found")
    try:
        row = rs.update_routine(db, routine, **payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _reschedule()
    return rs.serialize_routine(row)


@router.delete("/{routine_id}")
async def delete_routine_route(
    routine_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> Dict[str, Any]:
    routine = rs.get_routine(db, routine_id)
    if routine is None:
        raise HTTPException(status_code=404, detail="routine_not_found")
    rs.delete_routine(db, routine)
    _reschedule()
    return {"ok": True}


@router.get("/{routine_id}/runs")
async def list_runs_route(
    routine_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> Dict[str, Any]:
    if rs.get_routine(db, routine_id) is None:
        raise HTTPException(status_code=404, detail="routine_not_found")
    return {"runs": rs.list_runs(db, routine_id, limit=limit)}


@router.post("/{routine_id}/run")
async def run_routine_now_route(
    routine_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> Dict[str, Any]:
    if rs.get_routine(db, routine_id) is None:
        raise HTTPException(status_code=404, detail="routine_not_found")
    # Fire-and-forget on the running loop; result is delivered to channel/chat.
    asyncio.create_task(rs.execute_routine(routine_id, trigger="manual"))
    return {"ok": True, "status": "started"}
