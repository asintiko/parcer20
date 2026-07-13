"""Scoped access management: passwords, unlock tokens, and audit."""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from aiogram import Bot
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_current_user_optional, get_system_access_context, require_admin_user
from database.connection import get_db_session
from database.models import AccessAuditLog, AccessScope, AppLaunchConfig, LockedPeriod
from services.auth_bot_service import (
    OTPManager,
    create_launch_session_token,
    list_active_sessions,
    publish_auth_event,
    register_active_session,
    revoke_active_session,
    verify_launch_session_token,
)
from services.period_lock_service import period_lock_service
from services.access_control_service import (
    check_lockout,
    clear_failed_attempts,
    config_scope_to_public_dict,
    create_scope_token,
    create_scope_token_from_values,
    decode_scope_token,
    has_active_scopes,
    hash_password,
    normalize_years,
    record_failed_attempt,
    scope_to_public_dict,
    verify_password,
    write_audit_log,
    years_from_json,
    years_to_json,
)
from services.root_access_config_service import (
    find_scope_for_unlock,
    get_available_scope_years,
    get_config_scopes,
    get_system_access_status,
    scopes_managed_by_config,
    verify_secret,
)
from services.system_settings_service import is_otp_enabled
from services.internal_api_key_service import (
    has_configured_internal_api_key,
    is_internal_request,
)

router = APIRouter(prefix="/api/security", tags=["security"])
internal_router = APIRouter(prefix="/api/internal", tags=["security-internal"])

AUTH_BOT_TOKEN = os.getenv("AUTH_BOT_TOKEN", "").strip()
AUTH_ADMIN_IDS = [
    int(x.strip())
    for x in os.getenv("AUTH_ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
]
LAUNCH_LOCKOUT_MINUTES = int(os.getenv("LAUNCH_LOCKOUT_MINUTES", "30"))
LAUNCH_MAX_ATTEMPTS = int(os.getenv("LAUNCH_MAX_ATTEMPTS", "5"))
logger = logging.getLogger(__name__)


class AccessScopeCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    password: str = Field(..., min_length=6, max_length=200)
    years: List[int] = Field(default_factory=list)
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    allow_transactions: bool = True
    allow_sources: bool = False
    is_active: bool = True


class AccessScopeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    password: Optional[str] = Field(None, min_length=6, max_length=200)
    years: Optional[List[int]] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    allow_transactions: Optional[bool] = None
    allow_sources: Optional[bool] = None
    is_active: Optional[bool] = None


class AccessScopeResponse(BaseModel):
    id: int
    name: str
    years: List[int]
    period_start: Optional[str]
    period_end: Optional[str]
    allow_transactions: bool
    allow_sources: bool
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class UnlockRequest(BaseModel):
    password: str = Field(..., min_length=4, max_length=200)
    target_year: Optional[int] = None
    action: str = Field(default="transactions", pattern="^(transactions|sources)$")


class UnlockResponse(BaseModel):
    token: str
    expires_at: Optional[str] = None
    scope: AccessScopeResponse


class OTPVerifyRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=12)


class OTPRequestResponse(BaseModel):
    status: str
    expires_in: int = 0
    code_length: int = 0
    otp_skipped: bool = False
    token: Optional[str] = None
    expires_at: Optional[str] = None
    scope: Optional[AccessScopeResponse] = None


class AppLaunchVerifyRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=500)


class AppLaunchVerifyResponse(BaseModel):
    verified: bool
    session_token: Optional[str] = None
    expires_at: Optional[str] = None
    attempts_left: Optional[int] = None
    locked: Optional[bool] = None
    locked_until: Optional[str] = None


class AppLaunchStatusResponse(BaseModel):
    password_set: bool
    locked: bool
    locked_until: Optional[str] = None


class LockedPeriodCreateRequest(BaseModel):
    date_from: date
    date_to: date
    reason: Optional[str] = Field(None, max_length=500)
    tg_id: Optional[int] = None


class LockedPeriodResponse(BaseModel):
    id: int
    date_from: str
    date_to: str
    reason: Optional[str] = None
    locked_at: Optional[str] = None
    is_active: bool


class AccessStatusResponse(BaseModel):
    scopes_enabled: bool
    available_years: List[int]
    current_scope: Optional[AccessScopeResponse] = None


class SystemAccessStatusResponse(BaseModel):
    enforced: bool
    path: Optional[str]
    loaded: bool
    error: Optional[str]
    scopes_managed_by_config: bool
    available_scope_count: int


class AuditRecordResponse(BaseModel):
    id: int
    action: str
    success: bool
    scope_id: Optional[int]
    user_id: Optional[int]
    ip_address: Optional[str]
    details: Optional[Dict[str, Any]]
    created_at: Optional[str]


class ActiveSessionRecord(BaseModel):
    session_id: str
    token_kind: str
    subject: Optional[str] = None
    user_id: Optional[int] = None
    ip_address: Optional[str] = None
    created_at: Optional[str] = None
    last_activity_at: Optional[str] = None
    expires_at: Optional[str] = None


def _request_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _validate_scope_password_strength(password: str) -> None:
    """
    Minimal complexity rule for scope passwords:
    at least 6 chars, with at least one letter and one digit.
    """
    value = str(password or "")
    if len(value) < 6:
        raise HTTPException(status_code=400, detail="Scope password must be at least 6 characters")
    has_alpha = any(ch.isalpha() for ch in value)
    has_digit = any(ch.isdigit() for ch in value)
    if not (has_alpha and has_digit):
        raise HTTPException(
            status_code=400,
            detail="Scope password must include at least one letter and one digit",
        )


def _years_from_period(start: Optional[datetime], end: Optional[datetime]) -> List[int]:
    if start is None and end is None:
        return []
    start_year = start.year if start else (end.year if end else None)
    end_year = end.year if end else (start.year if start else None)
    if start_year is None or end_year is None:
        return []
    low = min(start_year, end_year)
    high = max(start_year, end_year)
    if high - low > 50:
        return []
    return [year for year in range(low, high + 1)]


def _scope_to_response(scope_dict: Dict[str, Any]) -> AccessScopeResponse:
    return AccessScopeResponse(
        id=int(scope_dict["id"]),
        name=str(scope_dict["name"]),
        years=list(scope_dict.get("years") or []),
        period_start=scope_dict.get("period_start"),
        period_end=scope_dict.get("period_end"),
        allow_transactions=bool(scope_dict.get("allow_transactions", True)),
        allow_sources=bool(scope_dict.get("allow_sources", False)),
        is_active=bool(scope_dict.get("is_active", False)),
        created_at=scope_dict.get("created_at"),
        updated_at=scope_dict.get("updated_at"),
    )


def _payload_to_scope_response(payload: Dict[str, Any]) -> AccessScopeResponse:
    return AccessScopeResponse(
        id=int(payload.get("scope_id", 0)),
        name=str(payload.get("scope_name", "")),
        years=normalize_years(payload.get("years") or []),
        period_start=payload.get("date_from"),
        period_end=payload.get("date_to"),
        allow_transactions=bool(payload.get("allow_transactions", True)),
        allow_sources=bool(payload.get("allow_sources", False)),
        is_active=True,
    )


def _readonly_scopes_guard() -> None:
    # Hybrid mode: DB scopes remain editable even when config scopes are loaded.
    return


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _scope_payload_for_id(db: Session, scope_id: int) -> Optional[Dict[str, Any]]:
    # Hybrid mode with DB priority.
    row = db.query(AccessScope).filter(AccessScope.id == scope_id).first()
    if row:
        return {
            "id": int(row.id),
            "name": row.name,
            "years": years_from_json(row.years_json),
            "period_start": row.period_start.isoformat() if row.period_start else None,
            "period_end": row.period_end.isoformat() if row.period_end else None,
            "allow_transactions": bool(row.allow_transactions),
            "allow_sources": bool(row.allow_sources),
            "is_active": bool(row.is_active),
            "source": "db",
        }

    for scope in get_config_scopes(active_only=False):
        try:
            config_id = int(scope.get("id") or 0)
        except Exception:
            continue
        if config_id == scope_id:
            payload = config_scope_to_public_dict(scope)
            payload["source"] = "config"
            return payload
    return None


def _require_internal_request(request: Request) -> None:
    if not has_configured_internal_api_key():
        raise HTTPException(status_code=503, detail="Internal API key is not configured")
    if not is_internal_request(request):
        raise HTTPException(status_code=403, detail="Invalid internal request origin")


async def _notify_admins(message_text: str) -> None:
    if not AUTH_BOT_TOKEN or not AUTH_ADMIN_IDS:
        return
    bot = Bot(AUTH_BOT_TOKEN)
    try:
        for admin_id in AUTH_ADMIN_IDS:
            try:
                await bot.send_message(chat_id=admin_id, text=message_text)
            except Exception:
                continue
    finally:
        await bot.session.close()


@router.get("/status", response_model=AccessStatusResponse)
async def get_access_status(
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: Optional[dict] = Depends(get_current_user_optional),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
    x_access_token: Optional[str] = Header(None, alias="X-Access-Token"),
) -> AccessStatusResponse:
    _ = request  # explicitly unused but retained for compatibility

    scopes_enabled = has_active_scopes(db) and is_otp_enabled(db)
    available_years: List[int] = []
    active_scopes = db.query(AccessScope).filter(AccessScope.is_active.is_(True)).all()
    db_scope_ids = set()
    for row in active_scopes:
        db_scope_ids.add(int(row.id))
        available_years.extend(years_from_json(row.years_json))
        available_years.extend(_years_from_period(row.period_start, row.period_end))
    for scope in get_config_scopes(active_only=True):
        try:
            scope_id = int(scope.get("id") or 0)
        except Exception:
            scope_id = 0
        if scope_id in db_scope_ids:
            continue
        available_years.extend(scope.get("years") or [])
        available_years.extend(_years_from_period(_parse_iso(scope.get("period_start")), _parse_iso(scope.get("period_end"))))
    available_years = sorted(set(normalize_years(available_years)))

    current_scope = None
    payload = decode_scope_token(x_access_token) if x_access_token else None
    if payload:
        current_scope = _payload_to_scope_response(payload)
    elif str((current_user or {}).get("role") or "").lower() == "admin":
        # Admins always have full access in RBAC mode and should not be blocked by scoped OTP UX.
        current_scope = AccessScopeResponse(
            id=-1,
            name="admin-full-access",
            years=available_years,
            period_start=None,
            period_end=None,
            allow_transactions=True,
            allow_sources=True,
            is_active=True,
        )

    return AccessStatusResponse(
        scopes_enabled=scopes_enabled,
        available_years=available_years,
        current_scope=current_scope,
    )


@router.get("/system-status", response_model=SystemAccessStatusResponse)
async def get_root_access_status(
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> SystemAccessStatusResponse:
    status = get_system_access_status()
    return SystemAccessStatusResponse(
        enforced=bool(status.get("enforced")),
        path=status.get("path"),
        loaded=bool(status.get("loaded")),
        error=status.get("error"),
        scopes_managed_by_config=bool(status.get("scopes_managed_by_config")),
        available_scope_count=int(status.get("available_scope_count") or 0),
    )


@router.get("/scopes", response_model=List[AccessScopeResponse])
async def list_scopes(
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> List[AccessScopeResponse]:
    _ = current_user
    rows = db.query(AccessScope).order_by(AccessScope.id.asc()).all()
    by_id: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        payload = scope_to_public_dict(row)
        by_id[int(payload["id"])] = payload

    # Hybrid fallback: include config scopes not present in DB.
    for scope in get_config_scopes(active_only=False):
        payload = config_scope_to_public_dict(scope)
        scope_id = int(payload.get("id") or 0)
        if scope_id not in by_id:
            by_id[scope_id] = payload

    return [_scope_to_response(item) for _, item in sorted(by_id.items(), key=lambda kv: kv[0])]


@router.post("/scopes", response_model=AccessScopeResponse)
async def create_scope(
    payload: AccessScopeCreate,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> AccessScopeResponse:
    _readonly_scopes_guard()

    if payload.period_start and payload.period_end and payload.period_start > payload.period_end:
        raise HTTPException(status_code=400, detail="period_start must be <= period_end")
    _validate_scope_password_strength(payload.password)

    existing = db.query(AccessScope).filter(AccessScope.name == payload.name.strip()).first()
    if existing:
        raise HTTPException(status_code=409, detail="Scope with this name already exists")

    password_hash, salt = hash_password(payload.password)
    row = AccessScope(
        name=payload.name.strip(),
        password_hash=password_hash,
        salt=salt,
        years_json=years_to_json(payload.years),
        period_start=payload.period_start,
        period_end=payload.period_end,
        allow_transactions=payload.allow_transactions,
        allow_sources=payload.allow_sources,
        is_active=payload.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    write_audit_log(
        db,
        action="scope_create",
        success=True,
        scope_id=int(row.id),
        user_id=current_user.get("user_id") if current_user else None,
        ip_address=_request_ip(request),
        details={"name": row.name},
    )
    return _scope_to_response(scope_to_public_dict(row))


@router.put("/scopes/{scope_id}", response_model=AccessScopeResponse)
async def update_scope(
    scope_id: int,
    payload: AccessScopeUpdate,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> AccessScopeResponse:
    _readonly_scopes_guard()

    row = db.query(AccessScope).filter(AccessScope.id == scope_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Scope not found")

    if payload.name is not None:
        candidate = payload.name.strip()
        if not candidate:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        conflict = (
            db.query(AccessScope)
            .filter(AccessScope.name == candidate, AccessScope.id != scope_id)
            .first()
        )
        if conflict:
            raise HTTPException(status_code=409, detail="Scope with this name already exists")
        row.name = candidate

    if payload.password:
        _validate_scope_password_strength(payload.password)
        password_hash, salt = hash_password(payload.password)
        row.password_hash = password_hash
        row.salt = salt

    if payload.years is not None:
        row.years_json = years_to_json(payload.years)
    if payload.period_start is not None:
        row.period_start = payload.period_start
    if payload.period_end is not None:
        row.period_end = payload.period_end
    if row.period_start and row.period_end and row.period_start > row.period_end:
        raise HTTPException(status_code=400, detail="period_start must be <= period_end")
    if payload.allow_transactions is not None:
        row.allow_transactions = payload.allow_transactions
    if payload.allow_sources is not None:
        row.allow_sources = payload.allow_sources
    if payload.is_active is not None:
        row.is_active = payload.is_active

    db.commit()
    db.refresh(row)

    write_audit_log(
        db,
        action="scope_update",
        success=True,
        scope_id=int(row.id),
        user_id=current_user.get("user_id") if current_user else None,
        ip_address=_request_ip(request),
        details={"name": row.name},
    )
    return _scope_to_response(scope_to_public_dict(row))


@router.delete("/scopes/{scope_id}")
async def delete_scope(
    scope_id: int,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> Dict[str, Any]:
    _readonly_scopes_guard()

    row = db.query(AccessScope).filter(AccessScope.id == scope_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Scope not found")
    name = row.name
    db.delete(row)
    db.commit()

    write_audit_log(
        db,
        action="scope_delete",
        success=True,
        scope_id=scope_id,
        user_id=current_user.get("user_id") if current_user else None,
        ip_address=_request_ip(request),
        details={"name": name},
    )
    return {"success": True}


@router.post("/unlock", response_model=UnlockResponse)
async def unlock_scope(
    payload: UnlockRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: Optional[dict] = Depends(get_current_user_optional),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> UnlockResponse:
    ip = _request_ip(request)
    lock_key = f"{ip}:{payload.action}:{payload.target_year or 'any'}"
    blocked, blocked_until = check_lockout(db, lock_key)
    if blocked:
        write_audit_log(
            db,
            action="scope_unlock_blocked",
            success=False,
            user_id=current_user.get("user_id") if current_user else None,
            ip_address=ip,
            details={"blocked_until": blocked_until.isoformat() if blocked_until else None},
        )
        raise HTTPException(status_code=429, detail="Too many failed attempts, try later")

    matched_scope_dict: Optional[Dict[str, Any]] = None
    matched_db_scope: Optional[AccessScope] = None

    scopes = db.query(AccessScope).filter(AccessScope.is_active.is_(True)).all()
    candidates: List[AccessScope] = []
    for scope in scopes:
        years = years_from_json(scope.years_json)
        if payload.target_year:
            target_year = payload.target_year
            if years and target_year not in years:
                continue
            if scope.period_start and target_year < scope.period_start.year:
                continue
            if scope.period_end and target_year > scope.period_end.year:
                continue
        if payload.action == "sources" and not scope.allow_sources:
            continue
        if payload.action == "transactions" and not scope.allow_transactions:
            continue
        candidates.append(scope)

    for scope in candidates:
        if verify_password(payload.password, scope.password_hash, scope.salt):
            matched_db_scope = scope
            break

    # Hybrid fallback: only check config scopes that are not shadowed by DB IDs.
    if not matched_db_scope:
        db_ids = {int(scope.id) for scope in scopes}
        for config_scope in get_config_scopes(active_only=True):
            try:
                config_id = int(config_scope.get("id") or 0)
            except Exception:
                config_id = 0
            if config_id in db_ids:
                continue
            years = normalize_years(config_scope.get("years") or [])
            period_start = _parse_iso(config_scope.get("period_start"))
            period_end = _parse_iso(config_scope.get("period_end"))

            if payload.target_year:
                target_year = payload.target_year
                if years and target_year not in years:
                    continue
                if period_start and target_year < period_start.year:
                    continue
                if period_end and target_year > period_end.year:
                    continue
            if payload.action == "sources" and not bool(config_scope.get("allow_sources", False)):
                continue
            if payload.action == "transactions" and not bool(config_scope.get("allow_transactions", True)):
                continue

            password_info = config_scope.get("password") or {}
            if verify_secret(payload.password, password_info):
                matched_scope_dict = config_scope_to_public_dict(config_scope)
                break

    if not matched_scope_dict and not matched_db_scope:
        row = record_failed_attempt(db, lock_key)
        write_audit_log(
            db,
            action="scope_unlock_failed",
            success=False,
            user_id=current_user.get("user_id") if current_user else None,
            ip_address=ip,
            details={
                "target_year": payload.target_year,
                "action": payload.action,
                "failed_attempts": row.failed_attempts,
                "blocked_until": row.blocked_until.isoformat() if row.blocked_until else None,
            },
        )
        raise HTTPException(status_code=401, detail="Invalid password or scope does not match requested access")

    clear_failed_attempts(db, lock_key)

    if matched_scope_dict is not None:
        token = create_scope_token_from_values(
            scope_id=int(matched_scope_dict.get("id") or 0),
            scope_name=str(matched_scope_dict.get("name") or "scope"),
            years=matched_scope_dict.get("years") or [],
            date_from=matched_scope_dict.get("period_start"),
            date_to=matched_scope_dict.get("period_end"),
            allow_transactions=bool(matched_scope_dict.get("allow_transactions", True)),
            allow_sources=bool(matched_scope_dict.get("allow_sources", False)),
        )
        scope_payload = config_scope_to_public_dict(matched_scope_dict)
        scope_id = int(scope_payload.get("id") or 0)
    else:
        token = create_scope_token(matched_db_scope)
        scope_payload = scope_to_public_dict(matched_db_scope)
        scope_id = int(matched_db_scope.id)

    decoded = decode_scope_token(token) or {}
    exp = decoded.get("exp")
    expires_at = datetime.utcfromtimestamp(exp).isoformat() + "Z" if exp else None

    write_audit_log(
        db,
        action="scope_unlock_success",
        success=True,
        scope_id=scope_id,
        user_id=current_user.get("user_id") if current_user else None,
        ip_address=ip,
        details={"target_year": payload.target_year, "action": payload.action},
    )

    return UnlockResponse(
        token=token,
        expires_at=expires_at,
        scope=_scope_to_response(scope_payload),
    )


@router.post("/scope/{scope_id}/request-code", response_model=OTPRequestResponse)
async def request_scope_code(
    scope_id: int,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: Optional[dict] = Depends(get_current_user_optional),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> OTPRequestResponse:
    ip = _request_ip(request)
    scope_payload = _scope_payload_for_id(db, scope_id)
    if not scope_payload or not bool(scope_payload.get("is_active", False)):
        raise HTTPException(status_code=404, detail="Scope not found")

    if not is_otp_enabled(db):
        token = create_scope_token_from_values(
            scope_id=int(scope_payload.get("id") or scope_id),
            scope_name=str(scope_payload.get("name") or f"scope-{scope_id}"),
            years=scope_payload.get("years") or [],
            date_from=scope_payload.get("period_start"),
            date_to=scope_payload.get("period_end"),
            allow_transactions=bool(scope_payload.get("allow_transactions", True)),
            allow_sources=bool(scope_payload.get("allow_sources", False)),
        )
        decoded = decode_scope_token(token) or {}
        exp = decoded.get("exp")
        expires_at = datetime.utcfromtimestamp(exp).isoformat() + "Z" if exp else None
        write_audit_log(
            db,
            action="scope_otp_skipped_global_off",
            success=True,
            scope_id=scope_id,
            user_id=current_user.get("user_id") if current_user else None,
            ip_address=ip,
            details={"scope_name": scope_payload.get("name")},
        )
        return OTPRequestResponse(
            status="otp_disabled",
            otp_skipped=True,
            token=token,
            expires_at=expires_at,
            scope=_scope_to_response(scope_payload),
        )

    manager = OTPManager()
    actor_key = f"{ip}:scope:{scope_id}"
    allowed, retry_in = await manager.check_rate_limit(actor_key)
    if not allowed:
        raise HTTPException(
            status_code=423,
            detail={"error": "locked", "locked_until_seconds": retry_in},
        )

    subject = f"scope:{scope_id}:{ip}"
    generated = await manager.generate_code(
        purpose="scope_access",
        subject=subject,
        context={
            "scope_id": scope_id,
            "scope_name": scope_payload.get("name"),
            "ip": ip,
            "requested_by": current_user.get("user_id") if current_user else None,
        },
    )

    subscribers = await publish_auth_event(
        "scope_code_requested",
        {
            "scope_id": scope_id,
            "scope_name": scope_payload.get("name"),
            "ip": ip,
            "code": generated["code"],
            "expires_in": generated["expires_in"],
        },
    )
    if subscribers <= 0:
        await _notify_admins(
            "🔐 Запрос доступа\n"
            f'Скоуп: "{scope_payload.get("name")}"\n'
            f"IP: {ip}\n"
            f'Код: {generated["code"]}\n'
            f'Действует: {generated["expires_in"]} сек'
        )

    write_audit_log(
        db,
        action="scope_otp_requested",
        success=True,
        scope_id=scope_id,
        user_id=current_user.get("user_id") if current_user else None,
        ip_address=ip,
        details={"scope_name": scope_payload.get("name")},
    )
    return OTPRequestResponse(
        status="code_sent",
        expires_in=generated["expires_in"],
        code_length=generated["code_length"],
    )


@router.post("/scope/{scope_id}/verify-code", response_model=UnlockResponse)
async def verify_scope_code(
    scope_id: int,
    payload: OTPVerifyRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: Optional[dict] = Depends(get_current_user_optional),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> UnlockResponse:
    ip = _request_ip(request)
    scope_payload = _scope_payload_for_id(db, scope_id)
    if not scope_payload or not bool(scope_payload.get("is_active", False)):
        raise HTTPException(status_code=404, detail="Scope not found")
    if not is_otp_enabled(db):
        raise HTTPException(
            status_code=409,
            detail={"error": "otp_disabled", "message": "Global OTP is disabled, request-code returns scoped token directly"},
        )

    subject = f"scope:{scope_id}:{ip}"
    manager = OTPManager()
    ok, info = await manager.verify_code("scope_access", subject=subject, input_code=payload.code)
    if not ok:
        error = info.get("error")
        if error == "invalid_code":
            await publish_auth_event(
                "scope_code_invalid",
                {
                    "scope_id": scope_id,
                    "scope_name": scope_payload.get("name"),
                    "ip": ip,
                    "attempts_left": info.get("attempts_left", 0),
                },
            )
        if error == "invalid_code":
            raise HTTPException(status_code=401, detail={"error": "invalid_code", "attempts_left": info.get("attempts_left", 0)})
        if error in {"code_expired", "max_attempts"}:
            raise HTTPException(status_code=429, detail={"error": "code_expired"})
        raise HTTPException(status_code=401, detail={"error": "invalid_code"})

    token = create_scope_token_from_values(
        scope_id=int(scope_payload.get("id") or scope_id),
        scope_name=str(scope_payload.get("name") or f"scope-{scope_id}"),
        years=scope_payload.get("years") or [],
        date_from=scope_payload.get("period_start"),
        date_to=scope_payload.get("period_end"),
        allow_transactions=bool(scope_payload.get("allow_transactions", True)),
        allow_sources=bool(scope_payload.get("allow_sources", False)),
    )
    decoded = decode_scope_token(token) or {}
    exp = decoded.get("exp")
    expires_at = datetime.utcfromtimestamp(exp).isoformat() + "Z" if exp else None

    write_audit_log(
        db,
        action="scope_otp_verified",
        success=True,
        scope_id=scope_id,
        user_id=current_user.get("user_id") if current_user else None,
        ip_address=ip,
        details={"scope_name": scope_payload.get("name")},
    )
    await publish_auth_event(
        "scope_code_verified",
        {
            "scope_id": scope_id,
            "scope_name": scope_payload.get("name"),
            "ip": ip,
        },
    )
    return UnlockResponse(
        token=token,
        expires_at=expires_at,
        scope=_scope_to_response(scope_payload),
    )


@router.get("/app/launch-status", response_model=AppLaunchStatusResponse)
async def get_launch_status(
    db: Session = Depends(get_db_session),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> AppLaunchStatusResponse:
    row = db.get(AppLaunchConfig, 1)
    if row is None:
        return AppLaunchStatusResponse(password_set=False, locked=False, locked_until=None)
    now = datetime.utcnow()
    locked = bool(row.locked_until and row.locked_until > now)
    return AppLaunchStatusResponse(
        password_set=True,
        locked=locked,
        locked_until=row.locked_until.isoformat() if locked and row.locked_until else None,
    )


@router.post("/app/verify-launch", response_model=AppLaunchVerifyResponse)
async def verify_launch_password(
    payload: AppLaunchVerifyRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> AppLaunchVerifyResponse:
    row = db.get(AppLaunchConfig, 1)
    if row is None:
        token = create_launch_session_token(ip_address=_request_ip(request))
        decoded = verify_launch_session_token(token) or {}
        if not decoded:
            raise HTTPException(status_code=503, detail="session_store_unavailable")
        session_id: Optional[str] = None
        session_id = await register_active_session(
            token_payload=decoded,
            token_kind="launch_session",
            user_id=None,
            ip_address=_request_ip(request),
            subject="app_launch",
        )
        if session_id != str(decoded.get("sid") or ""):
            raise HTTPException(status_code=503, detail="session_registration_failed")
        try:
            await publish_auth_event(
                "launch_session_created",
                {
                    "session_id": session_id,
                    "ip": _request_ip(request),
                    "subject": "app_launch",
                    "exp": decoded.get("exp"),
                },
            )
        except Exception:
            logger.debug("Failed to publish launch_session_created for unprotected launch", exc_info=True)
        exp = decoded.get("exp")
        return AppLaunchVerifyResponse(
            verified=True,
            session_token=token,
            expires_at=datetime.utcfromtimestamp(exp).isoformat() + "Z" if exp else None,
        )

    now = datetime.utcnow()
    if row.locked_until and row.locked_until > now:
        return AppLaunchVerifyResponse(
            verified=False,
            locked=True,
            locked_until=row.locked_until.isoformat(),
        )

    if verify_password(payload.password, row.password_hash, row.salt):
        row.failed_attempts = 0
        row.locked_until = None
        db.commit()

        token = create_launch_session_token(ip_address=_request_ip(request))
        decoded = verify_launch_session_token(token) or {}
        if not decoded:
            raise HTTPException(status_code=503, detail="session_store_unavailable")
        session_id: Optional[str] = None
        session_id = await register_active_session(
            token_payload=decoded,
            token_kind="launch_session",
            user_id=None,
            ip_address=_request_ip(request),
            subject="app_launch",
        )
        if session_id != str(decoded.get("sid") or ""):
            raise HTTPException(status_code=503, detail="session_registration_failed")
        try:
            await publish_auth_event(
                "launch_session_created",
                {
                    "session_id": session_id,
                    "ip": _request_ip(request),
                    "subject": "app_launch",
                    "exp": decoded.get("exp"),
                },
            )
        except Exception:
            logger.debug("Failed to publish launch_session_created after password verify", exc_info=True)
        exp = decoded.get("exp")
        return AppLaunchVerifyResponse(
            verified=True,
            session_token=token,
            expires_at=datetime.utcfromtimestamp(exp).isoformat() + "Z" if exp else None,
        )

    row.failed_attempts = int(row.failed_attempts or 0) + 1
    attempts_left = max(0, LAUNCH_MAX_ATTEMPTS - row.failed_attempts)
    if row.failed_attempts >= LAUNCH_MAX_ATTEMPTS:
        row.failed_attempts = 0
        row.locked_until = now + timedelta(minutes=max(1, LAUNCH_LOCKOUT_MINUTES))
    db.commit()
    return AppLaunchVerifyResponse(
        verified=False,
        attempts_left=attempts_left,
        locked=bool(row.locked_until and row.locked_until > now),
        locked_until=row.locked_until.isoformat() if row.locked_until else None,
    )


@internal_router.post("/app/set-launch-password")
async def internal_set_launch_password(
    payload: AppLaunchVerifyRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    _require_internal_request(request)
    password_hash, salt = hash_password(payload.password)
    row = db.get(AppLaunchConfig, 1)
    if row is None:
        row = AppLaunchConfig(id=1, password_hash=password_hash, salt=salt)
        db.add(row)
    else:
        row.password_hash = password_hash
        row.salt = salt
        row.failed_attempts = 0
        row.locked_until = None
    db.commit()
    return {"status": "ok"}


@router.get("/locked-periods")
async def list_locked_periods(
    db: Session = Depends(get_db_session),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> Dict[str, Any]:
    rows = period_lock_service.get_active_locks(db)
    periods = [
        LockedPeriodResponse(
            id=int(row.id),
            date_from=row.date_from.isoformat(),
            date_to=row.date_to.isoformat(),
            reason=row.reason,
            locked_at=row.locked_at.isoformat() if row.locked_at else None,
            is_active=bool(row.is_active),
        ).model_dump()
        for row in rows
    ]
    return {"periods": periods}


@internal_router.post("/locked-periods")
async def create_locked_period(
    payload: LockedPeriodCreateRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    _require_internal_request(request)
    row = period_lock_service.lock_period(
        date_from=payload.date_from,
        date_to=payload.date_to,
        tg_id=int(payload.tg_id or 0),
        reason=payload.reason,
        db=db,
    )
    try:
        await publish_auth_event(
            "locked_periods_changed",
            {"action": "created", "period_id": int(row.id)},
        )
    except Exception:
        logger.debug("Failed to publish locked_periods_changed(created)", exc_info=True)
    return {"id": int(row.id), "status": "locked"}


@internal_router.delete("/locked-periods/{lock_id}")
async def delete_locked_period(
    lock_id: int,
    request: Request,
    db: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    _require_internal_request(request)
    ok = period_lock_service.unlock_period(lock_id, db)
    if not ok:
        raise HTTPException(status_code=404, detail="Lock not found")
    try:
        await publish_auth_event(
            "locked_periods_changed",
            {"action": "deactivated", "period_id": int(lock_id)},
        )
    except Exception:
        logger.debug("Failed to publish locked_periods_changed(deactivated)", exc_info=True)
    return {"id": lock_id, "status": "unlocked"}


@router.get("/sessions", response_model=List[ActiveSessionRecord])
async def get_active_sessions(
    limit: int = Query(200, ge=1, le=2000),
    current_user: dict = Depends(require_admin_user),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> List[ActiveSessionRecord]:
    _ = current_user, _system
    rows = await list_active_sessions(limit=limit)
    return [ActiveSessionRecord(**row) for row in rows]


@router.delete("/sessions/{session_id}")
async def kill_active_session(
    session_id: str,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
) -> Dict[str, Any]:
    ok, info = await revoke_active_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="session_not_found")
    ip = request.client.host if request.client else "unknown"
    try:
        write_audit_log(
            db,
            action="admin_kill_session",
            success=True,
            user_id=int(current_user.get("id") or current_user.get("user_id") or 0),
            ip_address=ip,
            details={"killed_session_id": session_id, "killed_user_id": (info or {}).get("user_id")},
        )
    except Exception:
        logger.warning("Failed to write admin_kill_session audit", exc_info=True)
    return {"ok": True, "session_id": session_id}


class KillAllSessionsRequest(BaseModel):
    except_session_id: str = Field(..., min_length=1)


@router.post("/sessions/kill-all-except-current")
async def kill_all_except_current(
    payload: KillAllSessionsRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_admin_user),
) -> Dict[str, Any]:
    all_sessions = await list_active_sessions(limit=2000)
    killed = 0
    for s in all_sessions:
        sid = s.get("session_id", "")
        if sid and sid != payload.except_session_id:
            ok, _ = await revoke_active_session(sid)
            if ok:
                killed += 1

    ip = request.client.host if request.client else "unknown"
    try:
        write_audit_log(
            db,
            action="admin_kill_all_sessions",
            success=True,
            user_id=int(current_user.get("id") or current_user.get("user_id") or 0),
            ip_address=ip,
            details={"killed_count": killed, "kept_session_id": payload.except_session_id},
        )
    except Exception:
        logger.warning("Failed to write admin_kill_all_sessions audit", exc_info=True)
    return {"ok": True, "killed": killed}


class TelegramAccessOTPResponse(BaseModel):
    status: str
    expires_in: int = 0
    code_length: int = 0
    otp_skipped: bool = False
    token: Optional[str] = None
    expires_at: Optional[str] = None


class TelegramAccessVerifyRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=12)


class TelegramAccessVerifyResponse(BaseModel):
    token: str
    expires_at: Optional[str] = None


@router.post("/otp/telegram-access", response_model=TelegramAccessOTPResponse)
async def request_telegram_access_code(
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: Optional[dict] = Depends(get_current_user_optional),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> TelegramAccessOTPResponse:
    """Request OTP code for Telegram client access."""
    ip = _request_ip(request)

    if str((current_user or {}).get("role") or "").lower() == "admin":
        from services.auth_service import JWT_SECRET, JWT_ALGORITHM
        import jwt as pyjwt

        exp = datetime.utcnow() + timedelta(hours=1)
        token = pyjwt.encode(
            {"kind": "telegram_access", "ip": ip, "exp": exp, "iat": datetime.utcnow()},
            JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        write_audit_log(
            db,
            action="telegram_access_admin_bypass",
            success=True,
            user_id=current_user.get("user_id") if current_user else None,
            ip_address=ip,
        )
        return TelegramAccessOTPResponse(
            status="admin_bypass",
            otp_skipped=True,
            token=token,
            expires_at=exp.isoformat() + "Z",
        )

    if not is_otp_enabled(db):
        # OTP disabled — issue token immediately
        from services.auth_service import JWT_SECRET, JWT_ALGORITHM
        import jwt as pyjwt

        exp = datetime.utcnow() + timedelta(hours=1)
        token = pyjwt.encode(
            {"kind": "telegram_access", "ip": ip, "exp": exp, "iat": datetime.utcnow()},
            JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        write_audit_log(
            db,
            action="telegram_access_otp_skipped",
            success=True,
            user_id=current_user.get("user_id") if current_user else None,
            ip_address=ip,
        )
        return TelegramAccessOTPResponse(
            status="otp_disabled",
            otp_skipped=True,
            token=token,
            expires_at=exp.isoformat() + "Z",
        )

    manager = OTPManager()
    actor_key = f"{ip}:telegram_access"
    allowed, retry_in = await manager.check_rate_limit(actor_key)
    if not allowed:
        raise HTTPException(
            status_code=423,
            detail={"error": "locked", "locked_until_seconds": retry_in},
        )

    subject = f"telegram_access:{ip}"
    generated = await manager.generate_code(
        purpose="telegram_access",
        subject=subject,
        context={
            "ip": ip,
            "requested_by": current_user.get("user_id") if current_user else None,
        },
    )

    subscribers = await publish_auth_event(
        "telegram_access_code_requested",
        {
            "ip": ip,
            "code": generated["code"],
            "expires_in": generated["expires_in"],
        },
    )
    if subscribers <= 0:
        await _notify_admins(
            "🔐 Запрос доступа к Telegram\n"
            f"IP: {ip}\n"
            f'Код: {generated["code"]}\n'
            f'Действует: {generated["expires_in"]} сек'
        )

    write_audit_log(
        db,
        action="telegram_access_otp_requested",
        success=True,
        user_id=current_user.get("user_id") if current_user else None,
        ip_address=ip,
    )
    return TelegramAccessOTPResponse(
        status="code_sent",
        expires_in=generated["expires_in"],
        code_length=generated["code_length"],
    )


@router.post("/otp/telegram-access/verify", response_model=TelegramAccessVerifyResponse)
async def verify_telegram_access_code(
    payload: TelegramAccessVerifyRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: Optional[dict] = Depends(get_current_user_optional),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> TelegramAccessVerifyResponse:
    """Verify OTP code for Telegram client access."""
    ip = _request_ip(request)

    if not is_otp_enabled(db):
        raise HTTPException(status_code=409, detail="OTP is disabled")

    subject = f"telegram_access:{ip}"
    manager = OTPManager()
    ok, info = await manager.verify_code("telegram_access", subject=subject, input_code=payload.code)
    if not ok:
        error = info.get("error")
        if error == "invalid_code":
            await publish_auth_event(
                "telegram_access_code_invalid",
                {"ip": ip, "attempts_left": info.get("attempts_left", 0)},
            )
            raise HTTPException(
                status_code=401,
                detail={"error": "invalid_code", "attempts_left": info.get("attempts_left", 0)},
            )
        if error in {"code_expired", "max_attempts"}:
            raise HTTPException(status_code=429, detail={"error": "code_expired"})
        raise HTTPException(status_code=401, detail={"error": "invalid_code"})

    from services.auth_service import JWT_SECRET, JWT_ALGORITHM
    import jwt as pyjwt

    exp = datetime.utcnow() + timedelta(hours=1)
    token = pyjwt.encode(
        {"kind": "telegram_access", "ip": ip, "exp": exp, "iat": datetime.utcnow()},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )

    write_audit_log(
        db,
        action="telegram_access_otp_verified",
        success=True,
        user_id=current_user.get("user_id") if current_user else None,
        ip_address=ip,
    )
    await publish_auth_event("telegram_access_code_verified", {"ip": ip})
    return TelegramAccessVerifyResponse(token=token, expires_at=exp.isoformat() + "Z")


@router.get("/audit", response_model=List[AuditRecordResponse])
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
    if date_from:
        try:
            query = query.filter(AccessAuditLog.created_at >= datetime.fromisoformat(date_from))
        except Exception:
            logger.debug("Invalid date_from in audit query: %s", date_from, exc_info=True)
    if date_to:
        try:
            query = query.filter(AccessAuditLog.created_at <= datetime.fromisoformat(date_to))
        except Exception:
            logger.debug("Invalid date_to in audit query: %s", date_to, exc_info=True)
    rows = (
        query.order_by(AccessAuditLog.created_at.desc(), AccessAuditLog.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    result: List[AuditRecordResponse] = []
    for row in rows:
        details = None
        if row.details_json:
            try:
                details = json.loads(row.details_json)
            except Exception:
                details = {"raw": row.details_json}
        result.append(
            AuditRecordResponse(
                id=int(row.id),
                action=row.action,
                success=bool(row.success),
                scope_id=row.scope_id,
                user_id=row.user_id,
                ip_address=row.ip_address,
                details=details,
                created_at=row.created_at.isoformat() if row.created_at else None,
            )
        )
    return result
