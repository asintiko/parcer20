"""Audit log browsing API."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.dependencies import get_system_access_context, require_admin_user
from database.connection import get_db_session
from database.models import AccessAuditLog

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditRecordResponse(BaseModel):
    id: int
    action: str
    success: bool
    scope_id: Optional[int]
    user_id: Optional[int]
    ip_address: Optional[str]
    details: Optional[Dict[str, Any]]
    created_at: Optional[str]


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _normalize_details(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return {"raw": raw}
    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}


@router.get("", response_model=List[AuditRecordResponse])
async def get_audit_logs(
    action: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0, le=200000),
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> List[AuditRecordResponse]:
    _ = current_user, _system
    query = db.query(AccessAuditLog)
    if action:
        query = query.filter(AccessAuditLog.action == action.strip())
    if user_id is not None:
        query = query.filter(AccessAuditLog.user_id == int(user_id))
    parsed_from = _parse_date(date_from)
    if parsed_from is not None:
        query = query.filter(AccessAuditLog.created_at >= parsed_from)
    parsed_to = _parse_date(date_to)
    if parsed_to is not None:
        query = query.filter(AccessAuditLog.created_at <= parsed_to)

    rows = (
        query.order_by(AccessAuditLog.created_at.desc(), AccessAuditLog.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        AuditRecordResponse(
            id=int(row.id),
            action=row.action,
            success=bool(row.success),
            scope_id=row.scope_id,
            user_id=row.user_id,
            ip_address=row.ip_address,
            details=_normalize_details(row.details_json),
            created_at=row.created_at.isoformat() if row.created_at else None,
        )
        for row in rows
    ]
