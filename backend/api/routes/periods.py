"""Admin CRUD API for locked periods."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import get_system_access_context, require_admin_user
from database.connection import get_db_session
from database.models import LockedPeriod, User
from services.access_control_service import write_audit_log
from services.auth_bot_service import publish_auth_event
from services.period_lock_service import period_lock_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/periods", tags=["periods"])


# Cap to prevent JSONB bloat / DoS via massive lists.
EXCLUDED_USER_IDS_LIMIT = 1000


class PeriodCreateRequest(BaseModel):
    date_from: date
    date_to: date
    reason: Optional[str] = Field(default=None, max_length=500)
    excluded_user_ids: Optional[List[int]] = None


class PeriodUpdateRequest(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    reason: Optional[str] = Field(default=None, max_length=500)
    is_active: Optional[bool] = None
    excluded_user_ids: Optional[List[int]] = None


class PeriodResponse(BaseModel):
    id: int
    date_from: str
    date_to: str
    reason: Optional[str]
    is_active: bool
    locked_by_tg_id: Optional[int]
    created_at: Optional[str]
    excluded_user_ids: List[int] = Field(default_factory=list)


def _request_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _to_response(row: LockedPeriod) -> PeriodResponse:
    raw_excluded = getattr(row, "excluded_user_ids", None) or []
    excluded: List[int] = []
    for item in raw_excluded:
        try:
            excluded.append(int(item))
        except (TypeError, ValueError):
            continue
    return PeriodResponse(
        id=int(row.id),
        date_from=row.date_from.isoformat(),
        date_to=row.date_to.isoformat(),
        reason=row.reason,
        is_active=bool(row.is_active),
        locked_by_tg_id=int(row.locked_by_tg_id) if row.locked_by_tg_id is not None else None,
        created_at=row.locked_at.isoformat() if row.locked_at else None,
        excluded_user_ids=excluded,
    )


def _normalize_excluded(values: Optional[List[int]], db: Optional[Session] = None) -> List[int]:
    """Coerce + dedupe + (optionally) FK-validate user ids.

    M-2: drop ids that are <= 0 or do not exist in `users` table when `db` is given.
    """
    if not values:
        return []
    seen: set[int] = set()
    out: List[int] = []
    for v in values:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
    if len(out) > EXCLUDED_USER_IDS_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"excluded_user_ids exceeds limit ({EXCLUDED_USER_IDS_LIMIT})",
        )
    if db is not None and out:
        existing_ids = {
            int(uid)
            for (uid,) in db.query(User.id).filter(User.id.in_(out)).all()
        }
        missing = [n for n in out if n not in existing_ids]
        if missing:
            raise HTTPException(
                status_code=400,
                detail={"error": "unknown_user_ids", "missing": missing},
            )
    return out


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
        logger.exception("audit log write failed for action=%s", action)


async def _publish_locked_periods_change(action: str, period_id: int) -> None:
    try:
        await publish_auth_event(
            "locked_periods_changed",
            {"action": action, "period_id": int(period_id)},
        )
    except Exception:
        logger.exception("publish_auth_event failed for action=%s period_id=%s", action, period_id)


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
    excluded = _normalize_excluded(payload.excluded_user_ids, db=db)
    row = period_lock_service.lock_period(
        date_from=payload.date_from,
        date_to=payload.date_to,
        tg_id=int(current_user.get("id") or current_user.get("user_id") or 0),
        reason=payload.reason,
        db=db,
    )
    if excluded:
        row.excluded_user_ids = excluded
        db.commit()
        db.refresh(row)
    audit_details: Dict[str, Any] = {"period_id": int(row.id)}
    if excluded:
        audit_details["excluded_user_ids"] = excluded
    _audit(
        db,
        request,
        current_user,
        action="period_create",
        success=True,
        details=audit_details,
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

    # Snapshot before-state for audit (B3).
    before = {
        "date_from": row.date_from.isoformat() if row.date_from else None,
        "date_to": row.date_to.isoformat() if row.date_to else None,
        "reason": row.reason,
        "is_active": bool(row.is_active),
        "excluded_user_ids": list(getattr(row, "excluded_user_ids", []) or []),
    }

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
    if payload.excluded_user_ids is not None:
        row.excluded_user_ids = _normalize_excluded(payload.excluded_user_ids, db=db)
    db.commit()
    db.refresh(row)

    after = {
        "date_from": row.date_from.isoformat() if row.date_from else None,
        "date_to": row.date_to.isoformat() if row.date_to else None,
        "reason": row.reason,
        "is_active": bool(row.is_active),
        "excluded_user_ids": list(getattr(row, "excluded_user_ids", []) or []),
    }
    diff = {k: {"before": before[k], "after": after[k]} for k in after if before.get(k) != after.get(k)}
    audit_details: Dict[str, Any] = {"period_id": int(row.id)}
    if diff:
        audit_details["diff"] = diff

    _audit(
        db,
        request,
        current_user,
        action="period_update",
        success=True,
        details=audit_details,
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
