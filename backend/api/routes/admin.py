"""Admin API for RBAC user management."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import require_admin_user
from database.connection import get_db_session
from database.models import User
from services.access_control_service import write_audit_log
from services.user_service import (
    UserServiceError,
    build_permissions_snapshot,
    create_user,
    deactivate_user,
    get_user_by_id,
    list_users,
    reset_password,
    unlock_user,
    update_user,
)
from services.totp_service import disable_2fa
from services.auth_bot_service import publish_auth_event

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger(__name__)


class AdminUserResponse(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    allowed_tabs: List[str]
    allowed_folders: List[int]
    forbidden_periods: List[Dict[str, str]]
    allowed_sources: List[int]
    can_toggle_sources: bool
    permissions_version: int
    force_2fa: bool
    totp_enabled: bool
    totp_confirmed_at: Optional[str] = None
    telegram_id: Optional[int] = None
    telegram_username: Optional[str] = None
    session_ttl_days: int
    failed_attempts: int
    locked_until: Optional[str] = None
    last_login_at: Optional[str] = None


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=500)
    role: str = Field(default="operator", pattern="^(admin|operator)$")
    display_name: Optional[str] = Field(default=None, max_length=100)
    is_active: bool = True
    allowed_tabs: List[str] = Field(default_factory=lambda: ["dashboard"])
    allowed_folders: List[int] = Field(default_factory=list)
    forbidden_periods: List[Dict[str, str]] = Field(default_factory=list)
    allowed_sources: List[int] = Field(default_factory=list)
    can_toggle_sources: bool = False
    force_2fa: bool = False
    session_ttl_days: int = Field(default=7, ge=1, le=90)
    telegram_id: Optional[int] = None
    telegram_username: Optional[str] = Field(default=None, max_length=255)


class UpdateUserRequest(BaseModel):
    role: Optional[str] = Field(default=None, pattern="^(admin|operator)$")
    display_name: Optional[str] = Field(default=None, max_length=100)
    is_active: Optional[bool] = None
    allowed_tabs: Optional[List[str]] = None
    allowed_folders: Optional[List[int]] = None
    forbidden_periods: Optional[List[Dict[str, str]]] = None
    allowed_sources: Optional[List[int]] = None
    can_toggle_sources: Optional[bool] = None
    force_2fa: Optional[bool] = None
    session_ttl_days: Optional[int] = Field(default=None, ge=1, le=90)


class ResetPasswordRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=500)


class ForceTwoFactorRequest(BaseModel):
    force: bool = True


def _request_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _to_response(user: User) -> AdminUserResponse:
    snapshot = build_permissions_snapshot(user)
    return AdminUserResponse(
        id=int(user.id),
        username=user.username,
        display_name=str(snapshot.get("display_name") or user.username),
        role=str(snapshot.get("role") or "operator"),
        is_active=bool(user.is_active),
        allowed_tabs=[str(x) for x in (snapshot.get("allowed_tabs") or [])],
        allowed_folders=[int(x) for x in (snapshot.get("allowed_folders") or [])],
        forbidden_periods=list(snapshot.get("forbidden_periods") or []),
        allowed_sources=[int(x) for x in (snapshot.get("allowed_sources") or [])],
        can_toggle_sources=bool(snapshot.get("can_toggle_sources")),
        permissions_version=int(snapshot.get("permissions_version") or 1),
        force_2fa=bool(snapshot.get("force_2fa")),
        totp_enabled=bool(snapshot.get("totp_enabled")),
        totp_confirmed_at=snapshot.get("totp_confirmed_at"),
        telegram_id=int(user.telegram_id) if user.telegram_id else None,
        telegram_username=str(user.telegram_username) if user.telegram_username else None,
        session_ttl_days=int(snapshot.get("session_ttl_days") or 7),
        failed_attempts=int(user.failed_attempts or 0),
        locked_until=user.locked_until.isoformat() if user.locked_until else None,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
    )


def _audit(
    db: Session,
    request: Request,
    current_user: Optional[dict],
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
            user_id=int(current_user.get("id") or current_user.get("user_id") or 0) if current_user else None,
            ip_address=_request_ip(request),
            details=details or {},
        )
    except Exception:
        pass


@router.get("/users", response_model=List[AdminUserResponse])
async def get_users(
    include_inactive: bool = Query(True),
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
):
    rows = list_users(db, include_inactive=include_inactive)
    return [_to_response(row) for row in rows]


@router.post("/users", response_model=AdminUserResponse)
async def create_user_endpoint(
    payload: CreateUserRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
):
    try:
        row = create_user(
            db,
            username=payload.username,
            password=payload.password,
            role=payload.role,
            display_name=payload.display_name,
            is_active=payload.is_active,
            allowed_tabs=payload.allowed_tabs,
            allowed_folders=payload.allowed_folders,
            forbidden_periods=payload.forbidden_periods,
            allowed_sources=payload.allowed_sources,
            can_toggle_sources=payload.can_toggle_sources,
            force_2fa=payload.force_2fa,
            session_ttl_days=payload.session_ttl_days,
            telegram_id=payload.telegram_id,
            telegram_username=payload.telegram_username,
        )
    except UserServiceError as exc:
        if str(exc) == "username_exists":
            raise HTTPException(status_code=409, detail="username_exists")
        if str(exc) == "telegram_id_already_linked":
            raise HTTPException(status_code=409, detail="telegram_id_already_linked")
        raise HTTPException(status_code=400, detail=str(exc))

    _audit(
        db,
        request,
        current_user,
        action="admin_user_create",
        success=True,
        details={"user_id": int(row.id), "username": row.username},
    )
    return _to_response(row)


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user_endpoint(
    user_id: int,
    payload: UpdateUserRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
):
    row = get_user_by_id(db, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="user_not_found")

    try:
        row = update_user(
            db,
            row,
            role=payload.role,
            display_name=payload.display_name,
            is_active=payload.is_active,
            allowed_tabs=payload.allowed_tabs,
            allowed_folders=payload.allowed_folders,
            forbidden_periods=payload.forbidden_periods,
            allowed_sources=payload.allowed_sources,
            can_toggle_sources=payload.can_toggle_sources,
            force_2fa=payload.force_2fa,
            session_ttl_days=payload.session_ttl_days,
        )
    except UserServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    _audit(
        db,
        request,
        current_user,
        action="admin_user_update",
        success=True,
        details={"user_id": int(row.id), "username": row.username},
    )
    try:
        await publish_auth_event(
            "user_permissions_changed",
            {"user_id": int(row.id), "username": row.username, "admin_id": int(current_user.get("id") or 0)},
        )
    except Exception:
        logger.debug("Failed to publish user_permissions_changed for user_id=%s", int(row.id), exc_info=True)
    return _to_response(row)


@router.post("/users/{user_id}/reset-password", response_model=AdminUserResponse)
async def reset_user_password_endpoint(
    user_id: int,
    payload: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
):
    row = get_user_by_id(db, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="user_not_found")

    try:
        row = reset_password(db, row, payload.password)
    except UserServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    _audit(
        db,
        request,
        current_user,
        action="admin_user_reset_password",
        success=True,
        details={"user_id": int(row.id), "username": row.username},
    )
    return _to_response(row)


@router.post("/users/{user_id}/reset-2fa", response_model=AdminUserResponse)
async def reset_user_2fa_endpoint(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
):
    row = get_user_by_id(db, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="user_not_found")

    disable_2fa(db, row)
    _audit(
        db,
        request,
        current_user,
        action="admin_user_reset_2fa",
        success=True,
        details={"user_id": int(row.id), "username": row.username},
    )
    try:
        await publish_auth_event(
            "user_2fa_reset",
            {"user_id": int(row.id), "username": row.username, "admin_id": int(current_user.get("id") or 0)},
        )
    except Exception:
        logger.debug("Failed to publish user_2fa_reset for user_id=%s", int(row.id), exc_info=True)
    return _to_response(row)


@router.post("/users/{user_id}/force-2fa", response_model=AdminUserResponse)
async def force_user_2fa_endpoint(
    user_id: int,
    payload: ForceTwoFactorRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
):
    row = get_user_by_id(db, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="user_not_found")

    row = update_user(db, row, force_2fa=bool(payload.force))
    _audit(
        db,
        request,
        current_user,
        action="admin_user_force_2fa",
        success=True,
        details={"user_id": int(row.id), "username": row.username, "force_2fa": bool(payload.force)},
    )
    try:
        await publish_auth_event(
            "user_2fa_forced",
            {
                "user_id": int(row.id),
                "username": row.username,
                "admin_id": int(current_user.get("id") or 0),
                "force_2fa": bool(payload.force),
            },
        )
    except Exception:
        logger.debug("Failed to publish user_2fa_forced for user_id=%s", int(row.id), exc_info=True)
    return _to_response(row)


@router.post("/users/{user_id}/unlock", response_model=AdminUserResponse)
async def unlock_user_endpoint(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
):
    row = get_user_by_id(db, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="user_not_found")

    row = unlock_user(db, row)
    _audit(
        db,
        request,
        current_user,
        action="admin_user_unlock",
        success=True,
        details={"user_id": int(row.id), "username": row.username},
    )
    return _to_response(row)


@router.delete("/users/{user_id}", response_model=AdminUserResponse)
async def deactivate_user_endpoint(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
):
    row = get_user_by_id(db, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="user_not_found")

    row = deactivate_user(db, row)
    _audit(
        db,
        request,
        current_user,
        action="admin_user_deactivate",
        success=True,
        details={"user_id": int(row.id), "username": row.username},
    )
    return _to_response(row)


class LinkTelegramRequest(BaseModel):
    telegram_id: int
    telegram_username: Optional[str] = None


@router.post("/users/{user_id}/link-telegram", response_model=AdminUserResponse)
async def link_telegram_endpoint(
    user_id: int,
    payload: LinkTelegramRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
):
    row = get_user_by_id(db, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="user_not_found")

    # Check that telegram_id is not already linked to another user
    existing = db.query(User).filter(
        User.telegram_id == payload.telegram_id,
        User.id != user_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="telegram_id_already_linked")

    row.telegram_id = payload.telegram_id
    row.telegram_username = payload.telegram_username or None
    db.commit()
    db.refresh(row)

    _audit(
        db,
        request,
        current_user,
        action="admin_user_link_telegram",
        success=True,
        details={
            "user_id": int(row.id),
            "username": row.username,
            "telegram_id": payload.telegram_id,
            "telegram_username": payload.telegram_username,
        },
    )
    return _to_response(row)


@router.post("/users/{user_id}/unlink-telegram", response_model=AdminUserResponse)
async def unlink_telegram_endpoint(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
):
    row = get_user_by_id(db, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="user_not_found")

    old_tg_id = row.telegram_id
    row.telegram_id = None
    row.telegram_username = None
    db.commit()
    db.refresh(row)

    _audit(
        db,
        request,
        current_user,
        action="admin_user_unlink_telegram",
        success=True,
        details={"user_id": int(row.id), "username": row.username, "old_telegram_id": old_tg_id},
    )
    return _to_response(row)
