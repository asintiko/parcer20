"""Admin API for global runtime system settings."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.dependencies import get_system_access_context, require_admin_user
from database.connection import get_db_session
from services.access_control_service import write_audit_log
from services.auth_bot_service import publish_auth_event
from services.system_settings_service import get_settings_snapshot, update_settings

router = APIRouter(prefix="/api/system-settings", tags=["system-settings"])


class SystemSettingsResponse(BaseModel):
    id: int
    otp_enabled: bool
    bot_control_enabled: bool
    totp_2fa_enabled: bool
    launch_gate_enabled: bool
    updated_at: Optional[str] = None
    updated_by: Optional[int] = None


class SystemSettingsUpdateRequest(BaseModel):
    otp_enabled: Optional[bool] = None
    bot_control_enabled: Optional[bool] = None
    totp_2fa_enabled: Optional[bool] = None
    launch_gate_enabled: Optional[bool] = None


def _request_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


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


@router.get("", response_model=SystemSettingsResponse)
async def get_system_settings(
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> SystemSettingsResponse:
    _ = current_user, _system
    return SystemSettingsResponse(**get_settings_snapshot(db))


@router.patch("", response_model=SystemSettingsResponse)
async def patch_system_settings(
    payload: SystemSettingsUpdateRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> SystemSettingsResponse:
    row = update_settings(
        db,
        otp_enabled=payload.otp_enabled,
        bot_control_enabled=payload.bot_control_enabled,
        totp_2fa_enabled=payload.totp_2fa_enabled,
        launch_gate_enabled=payload.launch_gate_enabled,
        updated_by=int(current_user.get("id") or current_user.get("user_id") or 0),
    )
    snapshot = {
        "id": int(row.id),
        "otp_enabled": bool(row.otp_enabled),
        "bot_control_enabled": bool(row.bot_control_enabled),
        "totp_2fa_enabled": bool(row.totp_2fa_enabled),
        "launch_gate_enabled": bool(row.launch_gate_enabled),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by": int(row.updated_by) if row.updated_by is not None else None,
    }
    _audit(
        db,
        request,
        current_user,
        action="system_settings_update",
        success=True,
        details={k: v for k, v in payload.model_dump().items() if v is not None},
    )
    # Publish settings change event for real-time WS notification to all clients
    changed_fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if changed_fields:
        await publish_auth_event("settings_changed", changed_fields)
    return SystemSettingsResponse(**snapshot)
