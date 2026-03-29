"""Admin CRUD API for locked periods."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import get_system_access_context, require_admin_user
from database.connection import get_db_session
from database.models import LockedPeriod
from services.access_control_service import write_audit_log
from services.auth_bot_service import publish_auth_event
from services.period_lock_service import period_lock_service

router = APIRouter(prefix="/api/periods", tags=["periods"])


class PeriodCreateRequest(BaseModel):
    date_from: date
    date_to: date
    reason: Optional[str] = Field(default=None, max_length=500)


class PeriodUpdateRequest(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    reason: Optional[str] = Field(default=None, max_length=500)
    is_active: Optional[bool] = None


class PeriodResponse(BaseModel):
    id: int
    date_from: str
    date_to: str
    reason: Optional[str]
    is_active: bool
    locked_by_tg_id: Optional[int]
    created_at: Optional[str]


def _request_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _to_response(row: LockedPeriod) -> PeriodResponse:
    return PeriodResponse(
        id=int(row.id),
        date_from=row.date_from.isoformat(),
        date_to=row.date_to.isoformat(),
        reason=row.reason,
        is_active=bool(row.is_active),
        locked_by_tg_id=int(row.locked_by_tg_id) if row.locked_by_tg_id is not None else None,
        created_at=row.locked_at.isoformat() if row.locked_at else None,
    )


def _audit(
    db: Session,
    request: Request,
    current_user: dict,
    *,
    action: str,
    success: bool,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        write_audit_log(
            db,
            action=action,
            success=success,
            user_id=int(current_user.get("id") or current_user.get("user_id") or 0),
            ip_address=_request_ip(request),
            details=details or {},
        )
    except Exception:
        pass


async def _publish_locked_periods_change(action: str, period_id: int) -> None:
    try:
        await publish_auth_event(
            "locked_periods_changed",
            {"action": action, "period_id": int(period_id)},
        )
    except Exception:
        pass


@router.get("", response_model=List[PeriodResponse])
async def list_periods(
    active_only: bool = Query(True),
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> List[PeriodResponse]:
    _ = current_user, _system
    query = db.query(LockedPeriod).order_by(LockedPeriod.is_active.desc(), LockedPeriod.date_from.asc(), LockedPeriod.id.asc())
    if active_only:
        query = query.filter(LockedPeriod.is_active.is_(True))
    return [_to_response(row) for row in query.all()]


@router.post("", response_model=PeriodResponse, status_code=201)
async def create_period(
    payload: PeriodCreateRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> PeriodResponse:
    row = period_lock_service.lock_period(
        date_from=payload.date_from,
        date_to=payload.date_to,
        tg_id=int(current_user.get("id") or current_user.get("user_id") or 0),
        reason=payload.reason,
        db=db,
    )
    _audit(
        db,
        request,
        current_user,
        action="period_create",
        success=True,
        details={"period_id": int(row.id)},
    )
    await _publish_locked_periods_change("created", int(row.id))
    return _to_response(row)


@router.patch("/{period_id}", response_model=PeriodResponse)
async def update_period(
    period_id: int,
    payload: PeriodUpdateRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> PeriodResponse:
    row = db.get(LockedPeriod, period_id)
    if row is None:
        raise HTTPException(status_code=404, detail="period_not_found")

    new_from = payload.date_from or row.date_from
    new_to = payload.date_to or row.date_to
    if new_from > new_to:
        new_from, new_to = new_to, new_from
    row.date_from = new_from
    row.date_to = new_to
    if payload.reason is not None:
        row.reason = payload.reason or None
    if payload.is_active is not None:
        row.is_active = bool(payload.is_active)
    db.commit()
    db.refresh(row)

    _audit(
        db,
        request,
        current_user,
        action="period_update",
        success=True,
        details={"period_id": int(row.id)},
    )
    await _publish_locked_periods_change("updated", int(row.id))
    return _to_response(row)


@router.delete("/{period_id}")
async def deactivate_period(
    period_id: int,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> Dict[str, Any]:
    row = db.get(LockedPeriod, period_id)
    if row is None:
        raise HTTPException(status_code=404, detail="period_not_found")
    row.is_active = False
    db.commit()
    _audit(
        db,
        request,
        current_user,
        action="period_deactivate",
        success=True,
        details={"period_id": period_id},
    )
    await _publish_locked_periods_change("deactivated", int(period_id))
    return {"status": "ok", "id": period_id, "is_active": False}
