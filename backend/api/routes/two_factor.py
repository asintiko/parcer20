"""TOTP 2FA management endpoints."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import get_current_app_user, get_current_user_optional, get_system_access_context
from database.connection import get_db_session
from database.models import User
from services.access_control_service import write_audit_log
from services.auth_bot_service import get_redis
from services.auth_service import verify_temp_2fa_token
from services.system_settings_service import is_totp_2fa_enabled
from services.totp_service import (
    confirm_2fa,
    disable_2fa,
    enable_2fa_setup,
    regenerate_backup_codes,
    verify_2fa_code,
)


TWO_FA_MAX_ATTEMPTS = max(1, int(os.getenv("TWO_FA_MAX_ATTEMPTS", "5")))
TWO_FA_LOCKOUT_MINUTES = max(1, int(os.getenv("TWO_FA_LOCKOUT_MINUTES", "15")))

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/2fa", tags=["two-factor"])


class TwoFactorStatusResponse(BaseModel):
    enabled: bool
    force_2fa: bool
    confirmed_at: Optional[str] = None
    global_policy_enabled: bool
    required_now: bool


class TwoFactorSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    qr_code_base64: str
    backup_codes: list[str]


class TwoFactorCodeRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=32)


class TwoFactorSetupRequest(BaseModel):
    temp_token: Optional[str] = Field(default=None, min_length=16, max_length=4096)


class TwoFactorConfirmRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=32)
    temp_token: Optional[str] = Field(default=None, min_length=16, max_length=4096)


class TwoFactorVerifyRequest(BaseModel):
    temp_token: str = Field(..., min_length=16, max_length=4096)
    code: str = Field(..., min_length=4, max_length=32)


def _request_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _audit(
    db: Session,
    request: Request,
    *,
    action: str,
    success: bool,
    user_id: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        write_audit_log(
            db,
            action=action,
            success=success,
            user_id=user_id,
            ip_address=_request_ip(request),
            details=details or {},
        )
    except Exception:
        pass


def _required_now(user: User, global_policy_enabled: bool) -> bool:
    role = str(user.role or "operator").lower()
    return bool(user.force_2fa or (global_policy_enabled and role == "admin"))


def _resolve_user_from_context(
    db: Session,
    *,
    current_user: Optional[dict],
    temp_token: Optional[str],
) -> User:
    user_id: Optional[int] = None
    temp_payload: Optional[Dict[str, Any]] = None
    if isinstance(current_user, dict):
        try:
            user_id = int(current_user.get("id") or current_user.get("user_id") or 0) or None
        except Exception:
            user_id = None
    if user_id is None and temp_token:
        temp_payload = verify_temp_2fa_token(temp_token)
        if temp_payload:
            try:
                user_id = int(temp_payload.get("user_id") or temp_payload.get("sub") or 0) or None
            except Exception:
                user_id = None
    if user_id is None:
        raise HTTPException(status_code=401, detail="not_authenticated")
    user = db.get(User, int(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="user_not_found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="inactive_user")
    if temp_payload is not None:
        token_version = int(temp_payload.get("permissions_version") or 0)
        if token_version != int(user.permissions_version or 1):
            raise HTTPException(status_code=401, detail="permissions_outdated")
    return user


async def _require_fresh_2fa_step_up(
    db: Session,
    request: Request,
    user: User,
    code: str,
    *,
    action: str,
) -> str:
    if not bool(user.totp_enabled and user.totp_secret):
        raise HTTPException(status_code=400, detail="2fa_not_enabled")
    locked_seconds = await _check_2fa_lock(int(user.id))
    if locked_seconds:
        raise HTTPException(status_code=429, detail={"error": "locked", "locked_seconds": locked_seconds})
    ok, method = verify_2fa_code(db, user, code)
    if not ok:
        lock_data = await _mark_2fa_failed(int(user.id))
        _audit(
            db,
            request,
            action=f"{action}_step_up_failed",
            success=False,
            user_id=int(user.id),
            details=lock_data,
        )
        raise HTTPException(status_code=401, detail={"error": "invalid_code", **lock_data})
    await _clear_2fa_failures(int(user.id))
    return method


async def _check_2fa_lock(user_id: int) -> Optional[int]:
    try:
        redis = await get_redis()
        key = f"2fa:fail:{int(user_id)}"
        failures_raw = await redis.get(key)
        try:
            failures = int(failures_raw or 0)
        except Exception:
            failures = 0
        if failures < TWO_FA_MAX_ATTEMPTS:
            return None
        ttl = await redis.ttl(key)
        if ttl and int(ttl) > 0:
            return int(ttl)
        return max(1, TWO_FA_LOCKOUT_MINUTES * 60)
    except Exception:
        # Redis unavailable: fail closed — treat as locked to prevent brute force.
        logger.warning("Redis unavailable in _check_2fa_lock for user_id=%s; denying", user_id)
        return max(1, TWO_FA_LOCKOUT_MINUTES * 60)


async def _mark_2fa_failed(user_id: int) -> Dict[str, int]:
    try:
        redis = await get_redis()
        key = f"2fa:fail:{int(user_id)}"
        count = int(await redis.incr(key))
        if count == 1:
            await redis.expire(key, TWO_FA_LOCKOUT_MINUTES * 60)
        ttl = await redis.ttl(key)
        attempts_left = max(0, TWO_FA_MAX_ATTEMPTS - count)
        return {"attempts_left": attempts_left, "locked_seconds": max(0, int(ttl or 0))}
    except Exception:
        logger.warning("Redis unavailable in _mark_2fa_failed for user_id=%s", user_id)
        return {"attempts_left": 0, "locked_seconds": TWO_FA_LOCKOUT_MINUTES * 60}


async def _clear_2fa_failures(user_id: int) -> None:
    try:
        redis = await get_redis()
        await redis.delete(f"2fa:fail:{int(user_id)}")
    except Exception:
        logger.debug("Redis unavailable in _clear_2fa_failures for user_id=%s", user_id)


@router.get("/status", response_model=TwoFactorStatusResponse)
async def get_2fa_status(
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> TwoFactorStatusResponse:
    user = db.get(User, int(current_user.get("id") or current_user.get("user_id") or 0))
    if not user:
        raise HTTPException(status_code=404, detail="user_not_found")
    global_policy = is_totp_2fa_enabled(db)
    return TwoFactorStatusResponse(
        enabled=bool(user.totp_enabled),
        force_2fa=bool(user.force_2fa),
        confirmed_at=user.totp_confirmed_at.isoformat() if user.totp_confirmed_at else None,
        global_policy_enabled=global_policy,
        required_now=_required_now(user, global_policy),
    )


@router.post("/setup", response_model=TwoFactorSetupResponse)
async def setup_2fa(
    payload: TwoFactorSetupRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: Optional[dict] = Depends(get_current_user_optional),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> TwoFactorSetupResponse:
    user = _resolve_user_from_context(
        db,
        current_user=current_user,
        temp_token=payload.temp_token,
    )
    if payload.temp_token:
        temp_payload = verify_temp_2fa_token(payload.temp_token)
        if not temp_payload or temp_payload.get("requires_2fa_setup") is not True:
            raise HTTPException(status_code=403, detail="setup_not_authorized")
    if user.totp_enabled or user.totp_secret or user.backup_codes:
        raise HTTPException(status_code=409, detail="2fa_already_initialized")

    setup_payload = enable_2fa_setup(db, user)
    _audit(
        db,
        request,
        action="user_2fa_setup_started",
        success=True,
        user_id=int(user.id),
        details={"username": user.username},
    )
    return TwoFactorSetupResponse(**setup_payload)


@router.post("/confirm")
async def confirm_2fa_setup(
    payload: TwoFactorConfirmRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: Optional[dict] = Depends(get_current_user_optional),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> Dict[str, Any]:
    user = _resolve_user_from_context(
        db,
        current_user=current_user,
        temp_token=payload.temp_token,
    )
    if payload.temp_token:
        temp_payload = verify_temp_2fa_token(payload.temp_token)
        if not temp_payload or temp_payload.get("requires_2fa_setup") is not True:
            raise HTTPException(status_code=403, detail="setup_not_authorized")
    if user.totp_enabled:
        raise HTTPException(status_code=409, detail="2fa_already_enabled")

    locked_seconds = await _check_2fa_lock(int(user.id))
    if locked_seconds:
        raise HTTPException(status_code=429, detail={"error": "locked", "locked_seconds": locked_seconds})

    if not confirm_2fa(db, user, payload.code):
        lock_data = await _mark_2fa_failed(int(user.id))
        _audit(
            db,
            request,
            action="user_2fa_confirm_failed",
            success=False,
            user_id=int(user.id),
            details=lock_data,
        )
        raise HTTPException(status_code=401, detail={"error": "invalid_code", **lock_data})

    await _clear_2fa_failures(int(user.id))
    _audit(
        db,
        request,
        action="user_2fa_confirmed",
        success=True,
        user_id=int(user.id),
        details={"username": user.username},
    )
    return {"ok": True, "enabled": True}


@router.post("/verify")
async def verify_2fa_challenge(
    payload: TwoFactorVerifyRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> Dict[str, Any]:
    token_payload = verify_temp_2fa_token(payload.temp_token)
    if not token_payload:
        raise HTTPException(status_code=401, detail="invalid_temp_token")

    user_id = int(token_payload.get("user_id") or token_payload.get("sub") or 0)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user_not_found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="inactive_user")
    if int(token_payload.get("permissions_version") or 0) != int(user.permissions_version or 1):
        raise HTTPException(status_code=401, detail="permissions_outdated")
    if token_payload.get("requires_2fa_setup") is True:
        raise HTTPException(status_code=403, detail="setup_required")

    locked_seconds = await _check_2fa_lock(user_id)
    if locked_seconds:
        raise HTTPException(status_code=429, detail={"error": "locked", "locked_seconds": locked_seconds})

    ok, method = verify_2fa_code(db, user, payload.code)
    if not ok:
        lock_data = await _mark_2fa_failed(user_id)
        _audit(
            db,
            request,
            action="user_2fa_verify_failed",
            success=False,
            user_id=user_id,
            details=lock_data,
        )
        raise HTTPException(status_code=401, detail={"error": "invalid_code", **lock_data})

    await _clear_2fa_failures(user_id)
    _audit(
        db,
        request,
        action="user_2fa_verified",
        success=True,
        user_id=user_id,
        details={"method": method},
    )
    return {"ok": True, "method": method}


@router.post("/backup-codes")
async def regenerate_2fa_backup_codes(
    payload: TwoFactorCodeRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> Dict[str, Any]:
    user = db.get(User, int(current_user.get("id") or current_user.get("user_id") or 0))
    if not user:
        raise HTTPException(status_code=404, detail="user_not_found")
    method = await _require_fresh_2fa_step_up(
        db,
        request,
        user,
        payload.code,
        action="user_2fa_backup_codes_regenerate",
    )

    codes = regenerate_backup_codes(db, user)
    _audit(
        db,
        request,
        action="user_2fa_backup_codes_regenerated",
        success=True,
        user_id=int(user.id),
        details={"count": len(codes), "step_up_method": method},
    )
    return {"ok": True, "backup_codes": codes}


@router.delete("")
async def disable_user_2fa(
    payload: TwoFactorCodeRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_app_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> Dict[str, Any]:
    user = db.get(User, int(current_user.get("id") or current_user.get("user_id") or 0))
    if not user:
        raise HTTPException(status_code=404, detail="user_not_found")

    method = await _require_fresh_2fa_step_up(
        db,
        request,
        user,
        payload.code,
        action="user_2fa_disable",
    )

    disable_2fa(db, user)
    _audit(
        db,
        request,
        action="user_2fa_disabled",
        success=True,
        user_id=int(user.id),
        details={"username": user.username, "step_up_method": method},
    )
    return {"ok": True}
