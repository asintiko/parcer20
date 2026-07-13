"""
API Routes for authentication.
Provides RBAC username/password login.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import (
    get_current_app_user,
    get_current_user as resolve_current_user,
    require_session_active,
)
from database.connection import get_db_session
from database.models import User
from services.access_control_service import create_scope_token_from_values, write_audit_log
from services.auth_service import (
    create_app_user_token,
    create_refresh_token,
    create_temp_2fa_token,
    logout_user,
    rotate_refresh_token,
    revoke_refresh_family,
    verify_jwt_token,
    verify_temp_2fa_token,
    verify_user_token,
)
from services.user_service import authenticate, build_permissions_snapshot
from api.dependencies import get_effective_folder_scope_for_user
from services.totp_service import verify_2fa_code
from services.system_settings_service import is_totp_2fa_enabled
from services.auth_bot_service import get_redis, register_active_session, revoke_active_session

router = APIRouter(prefix="/api/auth", tags=["authentication"])
logger = logging.getLogger(__name__)

REFRESH_COOKIE_NAME = os.getenv("REFRESH_COOKIE_NAME", "refresh_token").strip() or "refresh_token"
REFRESH_COOKIE_SECURE = str(os.getenv("REFRESH_COOKIE_SECURE", "false")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
REFRESH_COOKIE_SAMESITE = os.getenv("REFRESH_COOKIE_SAMESITE", "lax").strip().lower() or "lax"
if REFRESH_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    REFRESH_COOKIE_SAMESITE = "lax"
TWO_FA_MAX_ATTEMPTS = max(1, int(os.getenv("TWO_FA_MAX_ATTEMPTS", "5")))
TWO_FA_LOCKOUT_MINUTES = max(1, int(os.getenv("TWO_FA_LOCKOUT_MINUTES", "15")))
AUTH_TOKEN_COMPAT_TTL_SECONDS = max(300, int(os.getenv("JWT_EXPIRATION_HOURS", "72")) * 3600)
QR_SESSION_TTL_SECONDS = max(120, int(os.getenv("QR_SESSION_TTL_SECONDS", "900")))  # default: 15 minutes
QR_RATE_LIMIT_PER_MINUTE = max(1, int(os.getenv("QR_RATE_LIMIT_PER_MINUTE", "5")))
TELEGRAM_BOT_TOKEN = os.getenv("AUTH_BOT_TOKEN", "").strip()
AUTH_LOGIN_RATE_LIMIT_PER_MIN = max(1, int(os.getenv("AUTH_LOGIN_RATE_LIMIT_PER_MIN", "10")))
AUTH_LOGIN_2FA_RATE_LIMIT_PER_MIN = max(1, int(os.getenv("AUTH_LOGIN_2FA_RATE_LIMIT_PER_MIN", "5")))
PRIMARY_QR_ADMIN_TELEGRAM_ID = int(os.getenv("PRIMARY_QR_ADMIN_TELEGRAM_ID", "1957390574") or 1957390574)
AUTH_DISABLE_LOGIN_2FA = str(os.getenv("AUTH_DISABLE_LOGIN_2FA", "false")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
USER_SESSION_TTL_MIN_DAYS = max(1, int(os.getenv("USER_SESSION_TTL_DAYS_MIN", "1")))
USER_SESSION_TTL_MAX_DAYS = max(USER_SESSION_TTL_MIN_DAYS, int(os.getenv("USER_SESSION_TTL_DAYS_MAX", "90")))
USER_SESSION_TTL_DEFAULT_DAYS = min(
    USER_SESSION_TTL_MAX_DAYS,
    max(USER_SESSION_TTL_MIN_DAYS, int(os.getenv("USER_SESSION_TTL_DAYS_DEFAULT", "7"))),
)


# Request/Response Models
class LogoutResponse(BaseModel):
    success: bool
    message: str


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=500)


class LoginResponse(BaseModel):
    ok: bool
    token: Optional[str] = None
    scope_token: Optional[str] = None
    refresh_token: Optional[str] = None
    user: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    requires_2fa: Optional[bool] = None
    requires_2fa_setup: Optional[bool] = None
    temp_token: Optional[str] = None
    attempts_left: Optional[int] = None
    locked_seconds: Optional[int] = None


class Login2FARequest(BaseModel):
    temp_token: str = Field(..., min_length=16, max_length=4096)
    code: str = Field(..., min_length=4, max_length=32)


class QRGenerateResponse(BaseModel):
    session_id: str
    qr_url: str
    expires_in: int


class QRConfirmRequest(BaseModel):
    session_id: str
    secret: str
    init_data: str


class QRStatusResponse(BaseModel):
    status: str  # pending | confirmed | expired
    token: Optional[str] = None
    scope_token: Optional[str] = None
    refresh_token: Optional[str] = None
    user: Optional[Dict[str, Any]] = None


class RefreshRequest(BaseModel):
    refresh_token: Optional[str] = Field(default=None, min_length=16, max_length=4096)


class UserInfoResponse(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    allowed_tabs: list[str]
    allowed_folders: list[int]
    forbidden_periods: list[dict]
    allowed_sources: list[int]
    can_toggle_sources: bool
    permissions_version: int
    totp_enabled: bool = False
    totp_confirmed_at: Optional[str] = None
    force_2fa: bool = False
    session_ttl_days: int = 7
    exp: Optional[int] = None


async def get_current_user(authorization: Optional[str] = Header(None)):
    """Compatibility dependency used by legacy routes."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = authorization.replace("Bearer ", "")
    user = await verify_user_token(token)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return user


def _safe_user_id(current_user: Optional[dict]) -> Optional[int]:
    if not isinstance(current_user, dict):
        return None
    for key in ("id", "user_id", "sub"):
        value = current_user.get(key)
        try:
            if value is not None:
                return int(value)
        except Exception:
            continue
    return None


def _request_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _safe_audit_log(
    db: Session,
    *,
    action: str,
    success: bool,
    user_id: Optional[int] = None,
    ip_address: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        write_audit_log(
            db,
            action=action,
            success=success,
            user_id=user_id,
            ip_address=ip_address,
            details=details,
        )
    except Exception:
        logger.warning("Failed to write audit log: action=%s", action, exc_info=True)


# In-process fallback rate-limit state when Redis is unavailable. Keyed by
# "key:minute_slot". Protected by a lock so concurrent requests are safe.
_AUTH_FALLBACK_RATE: Dict[str, int] = {}
_AUTH_FALLBACK_LOCK = threading.Lock()


def _auth_fallback_rate_check(key: str, limit: int) -> bool:
    """Return True if allowed under the in-process limiter, False if over limit."""
    current_slot = int(time.time() // 60)
    with _AUTH_FALLBACK_LOCK:
        for k in list(_AUTH_FALLBACK_RATE.keys()):
            try:
                if int(k.rsplit(":", 1)[1]) < current_slot:
                    _AUTH_FALLBACK_RATE.pop(k, None)
            except (ValueError, IndexError):
                _AUTH_FALLBACK_RATE.pop(k, None)
        count = _AUTH_FALLBACK_RATE.get(key, 0) + 1
        _AUTH_FALLBACK_RATE[key] = count
        return count <= limit


async def _check_endpoint_rate_limit(ip: str, key_suffix: str, limit_per_minute: int) -> Optional[int]:
    """Returns retry_after seconds when limited, otherwise None. Fails closed via in-process fallback when Redis is down."""
    minute_slot = int(time.time() // 60)
    fallback_key = f"rate:auth:{key_suffix}:{ip}:{minute_slot}"
    try:
        redis_client = await get_redis()
        key = fallback_key
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, 65)
        if int(count) > int(limit_per_minute):
            ttl = await redis_client.ttl(key)
            return max(1, int(ttl or 1))
        return None
    except Exception:
        logger.warning("Rate-limit Redis unavailable for %s, using in-process fallback", key_suffix)
        if not _auth_fallback_rate_check(fallback_key, limit_per_minute):
            return 60
        return None


def _build_login_scope_token(db: Session, user_snapshot: Dict[str, Any]) -> Optional[str]:
    if str(user_snapshot.get("role") or "").lower() == "admin":
        return None

    folder_scope = get_effective_folder_scope_for_user(user_snapshot, db)
    if not folder_scope:
        return None

    date_from = folder_scope.get("date_from")
    date_to = folder_scope.get("date_to")
    if date_from and date_to:
        try:
            from_dt = datetime.fromisoformat(str(date_from))
            to_dt = datetime.fromisoformat(str(date_to))
            if from_dt > to_dt:
                return None
        except Exception:
            pass

    allow_sources = (
        bool(folder_scope.get("allow_sources", False))
        or bool(user_snapshot.get("allowed_sources"))
        or ("userbot" in (user_snapshot.get("allowed_tabs") or []))
    )

    return create_scope_token_from_values(
        scope_id=int(folder_scope.get("scope_id") or -2),
        scope_name=str(folder_scope.get("scope_name") or "rbac-user"),
        years=folder_scope.get("years") or [],
        date_from=date_from,
        date_to=date_to,
        allow_transactions=True,
        allow_sources=allow_sources,
    )


def _set_refresh_cookie(
    response: Response,
    refresh_token: str,
    *,
    max_age_seconds: Optional[int] = None,
) -> None:
    max_age = int(max_age_seconds or (60 * 60 * 24 * 30))
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=REFRESH_COOKIE_SECURE,
        samesite=REFRESH_COOKIE_SAMESITE,
        path="/",
        max_age=max_age,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/")


def _normalize_session_ttl_days(user: User) -> int:
    raw = getattr(user, "session_ttl_days", USER_SESSION_TTL_DEFAULT_DAYS)
    try:
        ttl_days = int(raw)
    except Exception:
        ttl_days = USER_SESSION_TTL_DEFAULT_DAYS
    ttl_days = max(USER_SESSION_TTL_MIN_DAYS, min(USER_SESSION_TTL_MAX_DAYS, ttl_days))
    return ttl_days


def _requires_2fa(user: User, db: Session) -> bool:
    if AUTH_DISABLE_LOGIN_2FA:
        return False
    # Policy by product decision:
    # - global totp_2fa_enabled enforces 2FA for admin only,
    # - operator is enforced only when force_2fa=true.
    role = str(user.role or "operator").lower()
    return bool(user.force_2fa or (is_totp_2fa_enabled(db) and role == "admin"))


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


async def _clear_2fa_failed(user_id: int) -> None:
    try:
        redis = await get_redis()
        await redis.delete(f"2fa:fail:{int(user_id)}")
    except Exception:
        logger.debug("Redis unavailable in _clear_2fa_failed for user_id=%s", user_id)


async def _store_access_token_compat(user_id: int, token: str) -> None:
    try:
        redis = await get_redis()
        await redis.setex(f"auth_token:{int(user_id)}", AUTH_TOKEN_COMPAT_TTL_SECONDS, token)
    except Exception:
        logger.debug("Failed to store compatibility access token for user_id=%s", user_id, exc_info=True)


async def _register_refresh_backed_app_session(
    *,
    refresh_token: str,
    expected_sid: str,
    user: User,
    ip_address: str,
) -> str:
    """Register an app session for the full lifetime of its refresh token."""
    refresh_claims = verify_jwt_token(refresh_token) or {}
    refresh_sid = str(refresh_claims.get("sid") or "").strip()
    if (
        str(refresh_claims.get("kind") or "") != "refresh_token"
        or not refresh_claims.get("exp")
        or not refresh_sid
        or refresh_sid != expected_sid
    ):
        raise HTTPException(status_code=503, detail="session_registration_failed")

    registered_sid = await register_active_session(
        token_payload=refresh_claims,
        token_kind="app_user",
        user_id=int(user.id),
        ip_address=ip_address,
        subject=user.username,
    )
    if registered_sid != expected_sid:
        raise HTTPException(status_code=503, detail="session_registration_failed")
    return registered_sid


async def _acquire_refresh_rotation_lock(jti: str) -> tuple[str, str]:
    if not jti:
        raise HTTPException(status_code=401, detail="invalid_refresh_token")
    key = f"auth:refresh:rotate-lock:{jti}"
    owner = secrets.token_urlsafe(24)
    try:
        redis = await get_redis()
        acquired = await redis.set(key, owner, nx=True, ex=30)
    except Exception as exc:
        logger.error("Refresh rotation lock store unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="session_store_unavailable") from exc
    if not acquired:
        raise HTTPException(status_code=401, detail="refresh_token_reused")
    return key, owner


async def _release_refresh_rotation_lock(key: str, owner: str) -> None:
    try:
        redis = await get_redis()
        await redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end",
            1,
            key,
            owner,
        )
    except Exception:
        logger.warning("Failed to release refresh rotation lock key=%s", key, exc_info=True)


async def _issue_login_success(
    *,
    db: Session,
    request: Request,
    response: Response,
    user: User,
    snapshot: Dict[str, Any],
) -> LoginResponse:
    ttl_days = _normalize_session_ttl_days(user)
    access_ttl_minutes = ttl_days * 24 * 60
    refresh_ttl_days = ttl_days + 7
    token = create_app_user_token(
        user_id=int(user.id),
        username=user.username,
        role=str(user.role),
        permissions_version=int(user.permissions_version or 1),
        display_name=user.display_name,
        ttl_minutes=access_ttl_minutes,
    )
    decoded_access = verify_jwt_token(token) or {}
    sid = str(decoded_access.get("sid") or "")
    if not sid:
        raise HTTPException(status_code=503, detail="session_registration_failed")

    refresh_payload = await create_refresh_token(
        user_id=int(user.id),
        username=user.username,
        role=str(user.role),
        permissions_version=int(user.permissions_version or 1),
        sid=sid or None,
        ttl_days=refresh_ttl_days,
    )
    refresh_token = str(refresh_payload.get("token") or "")
    await _register_refresh_backed_app_session(
        refresh_token=refresh_token,
        expected_sid=sid,
        user=user,
        ip_address=_request_ip(request),
    )
    if refresh_token:
        _set_refresh_cookie(response, refresh_token, max_age_seconds=refresh_ttl_days * 24 * 3600)

    await _store_access_token_compat(int(user.id), token)
    scope_token = _build_login_scope_token(db, snapshot)
    return LoginResponse(
        ok=True,
        token=token,
        scope_token=scope_token,
        refresh_token=refresh_token,
        user=snapshot,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
):
    ip = _request_ip(request)
    retry_after = await _check_endpoint_rate_limit(
        ip=ip,
        key_suffix="login",
        limit_per_minute=AUTH_LOGIN_RATE_LIMIT_PER_MIN,
    )
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limited", "retry_after_seconds": retry_after},
        )

    user, meta = authenticate(db, payload.username, payload.password)
    if not user:
        error = str(meta.get("error") or "invalid_credentials")
        response_payload = LoginResponse(
            ok=False,
            error=error,
            attempts_left=meta.get("attempts_left"),
            locked_seconds=meta.get("locked_seconds"),
        )

        _safe_audit_log(
            db,
            action="login_failed",
            success=False,
            ip_address=_request_ip(request),
            details={"username": payload.username, "error": error},
        )

        status_code = 423 if error == "locked" else (403 if error == "inactive_user" else 401)
        return JSONResponse(status_code=status_code, content=response_payload.model_dump())

    snapshot = build_permissions_snapshot(user)

    if _requires_2fa(user, db):
        requires_setup = not bool(user.totp_enabled and user.totp_secret)
        temp_token = create_temp_2fa_token(
            user_id=int(user.id),
            username=user.username,
            role=str(user.role),
            permissions_version=int(user.permissions_version or 1),
            requires_setup=requires_setup,
        )
        return LoginResponse(
            ok=False,
            error="requires_2fa",
            requires_2fa=True,
            requires_2fa_setup=requires_setup,
            temp_token=temp_token,
        )

    _safe_audit_log(
        db,
        action="login_success",
        success=True,
        user_id=int(user.id),
        ip_address=_request_ip(request),
        details={"username": user.username, "role": user.role},
    )
    return await _issue_login_success(
        db=db,
        request=request,
        response=response,
        user=user,
        snapshot=snapshot,
    )


@router.post("/qr/generate", response_model=QRGenerateResponse)
async def generate_qr(request: Request):
    """Generate a QR session for Telegram-based login."""
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=503, detail="Telegram bot not configured")

    ip = _request_ip(request)
    redis_client = await get_redis()

    # Rate limit: max 5 per minute per IP
    rate_key = f"qr:rate:{ip}"
    current_rate = await redis_client.incr(rate_key)
    if current_rate == 1:
        await redis_client.expire(rate_key, 60)
    if current_rate > QR_RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Too many QR requests, try later")

    session_id = secrets.token_urlsafe(24)
    secret_token = secrets.token_urlsafe(32)

    # Store in Redis with TTL
    qr_data = {
        "secret": secret_token,
        "ip": ip,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
    }
    import json as _json
    await redis_client.setex(
        f"qr:session:{session_id}",
        QR_SESSION_TTL_SECONDS,
        _json.dumps(qr_data),
    )
    # O(1) lookup path for /qr/confirm by secret to avoid scanning all pending sessions.
    await redis_client.setex(
        f"qr:secret:{secret_token}",
        QR_SESSION_TTL_SECONDS,
        session_id,
    )

    # Build QR URL — deep link to Telegram Mini App
    bot_username = ""
    try:
        from aiogram import Bot as _Bot

        _bot = _Bot(TELEGRAM_BOT_TOKEN)
        me = await _bot.get_me()
        bot_username = me.username or ""
        await _bot.session.close()
    except Exception:
        logger.debug("Failed to resolve auth bot username for QR URL", exc_info=True)

    start_param = f"{session_id}__{secret_token}"
    qr_url = f"https://t.me/{bot_username}?startapp={start_param}" if bot_username else f"qr://{session_id}/{secret_token}"

    return QRGenerateResponse(
        session_id=session_id,
        qr_url=qr_url,
        expires_in=QR_SESSION_TTL_SECONDS,
    )


@router.post("/login/2fa", response_model=LoginResponse)
async def login_2fa(
    payload: Login2FARequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
):
    ip = _request_ip(request)
    retry_after = await _check_endpoint_rate_limit(
        ip=ip,
        key_suffix="login_2fa",
        limit_per_minute=AUTH_LOGIN_2FA_RATE_LIMIT_PER_MIN,
    )
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limited", "retry_after_seconds": retry_after},
        )

    temp_payload = verify_temp_2fa_token(payload.temp_token)
    if not temp_payload:
        raise HTTPException(status_code=401, detail="invalid_temp_token")

    user_id = int(temp_payload.get("user_id") or temp_payload.get("sub") or 0)
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="inactive_user")

    token_version = int(temp_payload.get("permissions_version") or 1)
    if token_version != int(user.permissions_version or 1):
        raise HTTPException(status_code=401, detail="permissions_outdated")

    if not bool(user.totp_enabled and user.totp_secret):
        raise HTTPException(status_code=400, detail="requires_2fa_setup")

    locked_seconds = await _check_2fa_lock(int(user.id))
    if locked_seconds:
        raise HTTPException(status_code=429, detail={"error": "locked", "locked_seconds": locked_seconds})

    ok, method = verify_2fa_code(db, user, payload.code)
    if not ok:
        lock_data = await _mark_2fa_failed(int(user.id))
        raise HTTPException(status_code=401, detail={"error": "invalid_code", **lock_data})

    await _clear_2fa_failed(int(user.id))
    snapshot = build_permissions_snapshot(user)
    _safe_audit_log(
        db,
        action="login_2fa_success",
        success=True,
        user_id=int(user.id),
        ip_address=_request_ip(request),
        details={"method": method},
    )

    return await _issue_login_success(
        db=db,
        request=request,
        response=response,
        user=user,
        snapshot=snapshot,
    )


@router.post("/refresh", response_model=LoginResponse)
async def refresh_auth_token(
    payload: RefreshRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
):
    refresh_token = (
        payload.refresh_token
        or request.headers.get("x-refresh-token")
        or request.cookies.get(REFRESH_COOKIE_NAME)
    )
    if not refresh_token:
        raise HTTPException(status_code=401, detail="missing_refresh_token")

    incoming_refresh = verify_jwt_token(refresh_token) or {}
    if str(incoming_refresh.get("kind") or "") != "refresh_token":
        raise HTTPException(status_code=401, detail="invalid_refresh_token")
    await require_session_active(incoming_refresh)
    user_id = int(incoming_refresh.get("user_id") or incoming_refresh.get("sub") or 0)
    user = db.get(User, user_id)
    if not user or not user.is_active:
        try:
            await revoke_refresh_family(incoming_refresh.get("family_id"))
        except Exception:
            logger.debug("Failed to revoke refresh family for inactive user", exc_info=True)
        raise HTTPException(status_code=403, detail="inactive_user")

    refresh_perm_version = int(incoming_refresh.get("permissions_version") or 1)
    db_perm_version = int(user.permissions_version or 1)
    if refresh_perm_version != db_perm_version:
        try:
            await revoke_refresh_family(incoming_refresh.get("family_id"))
        except Exception:
            logger.debug("Failed to revoke refresh family for permissions mismatch", exc_info=True)
        raise HTTPException(status_code=401, detail="permissions_outdated")

    refresh_ttl_days = _normalize_session_ttl_days(user) + 7
    lock_key, lock_owner = await _acquire_refresh_rotation_lock(str(incoming_refresh.get("jti") or ""))
    try:
        rotated = await rotate_refresh_token(refresh_token, ttl_days=refresh_ttl_days)
    finally:
        await _release_refresh_rotation_lock(lock_key, lock_owner)
    if not rotated:
        raise HTTPException(status_code=401, detail="invalid_refresh_token")

    refresh_jwt = str(rotated.get("token") or "")
    decoded_refresh = verify_jwt_token(refresh_jwt) or {}
    access_sid = str(decoded_refresh.get("sid") or "")
    ttl_days = _normalize_session_ttl_days(user)
    access_ttl_minutes = ttl_days * 24 * 60
    token = create_app_user_token(
        user_id=int(user.id),
        username=user.username,
        role=str(user.role),
        permissions_version=db_perm_version,
        display_name=user.display_name,
        sid=access_sid or None,
        ttl_minutes=access_ttl_minutes,
    )
    decoded_access = verify_jwt_token(token) or {}
    access_token_sid = str(decoded_access.get("sid") or "")
    if not access_token_sid:
        raise HTTPException(status_code=503, detail="session_registration_failed")
    await _register_refresh_backed_app_session(
        refresh_token=refresh_jwt,
        expected_sid=access_token_sid,
        user=user,
        ip_address=_request_ip(request),
    )
    await _store_access_token_compat(int(user.id), token)
    if refresh_jwt:
        _set_refresh_cookie(response, refresh_jwt, max_age_seconds=refresh_ttl_days * 24 * 3600)
    snapshot = build_permissions_snapshot(user)
    _safe_audit_log(
        db,
        action="token_refreshed",
        success=True,
        user_id=int(user.id),
        ip_address=_request_ip(request),
        details={"sid": access_sid or None},
    )

    return LoginResponse(
        ok=True,
        token=token,
        scope_token=_build_login_scope_token(db, snapshot),
        refresh_token=refresh_jwt,
        user=snapshot,
    )


@router.get("/qr/status/{session_id}", response_model=QRStatusResponse)
async def check_login_status(session_id: str):
    """Poll QR session status. Returns tokens when confirmed."""
    redis_client = await get_redis()
    import json as _json

    raw = await redis_client.get(f"qr:session:{session_id}")
    if not raw:
        return QRStatusResponse(status="expired")

    data = _json.loads(raw)
    status = data.get("status", "pending")

    if status == "confirmed":
        # Return tokens and clean up
        await redis_client.delete(f"qr:session:{session_id}")
        try:
            secret = str(data.get("secret") or "").strip()
            if secret:
                await redis_client.delete(f"qr:secret:{secret}")
        except Exception:
            logger.debug("Failed to cleanup qr:secret for session_id=%s", session_id, exc_info=True)
        return QRStatusResponse(
            status="confirmed",
            token=data.get("access_token"),
            scope_token=data.get("scope_token"),
            refresh_token=data.get("refresh_token"),
            user=_json.loads(data["user_snapshot"]) if data.get("user_snapshot") else None,
        )

    return QRStatusResponse(status="pending")


@router.post("/qr/confirm")
async def confirm_qr_login(
    payload: QRConfirmRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
):
    """Confirm QR login from Telegram Mini App. Validates initData via HMAC."""
    import json as _json

    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=503, detail="Telegram bot not configured")

    redis_client = await get_redis()
    session_key = f"qr:session:{payload.session_id}"
    raw = await redis_client.get(session_key)
    # Fallback: recover pending session by secret if session_id parsing was wrong on client side.
    if not raw and payload.secret:
        try:
            mapped_session_id = await redis_client.get(f"qr:secret:{payload.secret}")
            if mapped_session_id:
                mapped_session_id = (
                    mapped_session_id.decode() if isinstance(mapped_session_id, bytes) else str(mapped_session_id)
                )
                session_key = f"qr:session:{mapped_session_id}"
                raw = await redis_client.get(session_key)
        except Exception:
            logger.debug("Failed qr secret->session fallback lookup", exc_info=True)
    if not raw:
        raise HTTPException(status_code=404, detail="QR session expired or not found")

    data = _json.loads(raw)
    if data.get("status") != "pending":
        raise HTTPException(status_code=409, detail="QR session already confirmed")

    # Verify secret matches
    if not secrets.compare_digest(data.get("secret", ""), payload.secret):
        raise HTTPException(status_code=401, detail="Invalid QR secret")

    # Validate Telegram WebApp initData via HMAC-SHA256
    telegram_id, telegram_username = _validate_telegram_init_data(payload.init_data)
    if not telegram_id:
        raise HTTPException(status_code=401, detail="Invalid Telegram initData")

    user: Optional[User] = None
    if PRIMARY_QR_ADMIN_TELEGRAM_ID and int(telegram_id) == int(PRIMARY_QR_ADMIN_TELEGRAM_ID):
        # Product rule: this Telegram ID must always resolve to the active admin account,
        # even if it was previously linked to an operator by mistake.
        admin_candidate = (
            db.query(User)
            .filter(User.role == "admin", User.is_active.is_(True))
            .order_by((User.telegram_id == telegram_id).desc(), User.id.asc())
            .first()
        )
        if admin_candidate:
            conflicting_user = (
                db.query(User)
                .filter(
                    User.telegram_id == telegram_id,
                    User.id != admin_candidate.id,
                )
                .first()
            )
            if conflicting_user:
                conflicting_user.telegram_id = None
                conflicting_user.telegram_username = None
                db.flush()
            if admin_candidate.telegram_id != int(telegram_id):
                admin_candidate.telegram_id = int(telegram_id)
            if telegram_username:
                admin_candidate.telegram_username = str(telegram_username)
            db.commit()
            db.refresh(admin_candidate)
            user = admin_candidate

    if not user:
        # Standard lookup for all other Telegram accounts.
        user = db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=403, detail="No user linked to this Telegram account")

    if _requires_2fa(user, db):
        _safe_audit_log(
            db,
            action="qr_login_2fa_required",
            success=False,
            user_id=int(user.id),
            ip_address=data.get("ip", "unknown"),
            details={"telegram_id": telegram_id},
        )
        raise HTTPException(status_code=403, detail="qr_login_requires_2fa")

    # Issue tokens
    snapshot = build_permissions_snapshot(user)
    token = create_app_user_token(
        user_id=int(user.id),
        username=user.username,
        role=str(user.role),
        permissions_version=int(user.permissions_version or 1),
        display_name=user.display_name,
    )
    decoded_access = verify_jwt_token(token) or {}
    sid = str(decoded_access.get("sid") or "")
    if not sid:
        raise HTTPException(status_code=503, detail="session_registration_failed")

    refresh_payload = await create_refresh_token(
        user_id=int(user.id),
        username=user.username,
        role=str(user.role),
        permissions_version=int(user.permissions_version or 1),
        sid=sid or None,
        ttl_days=_normalize_session_ttl_days(user) + 7,
    )
    refresh_token = str(refresh_payload.get("token") or "")
    await _register_refresh_backed_app_session(
        refresh_token=refresh_token,
        expected_sid=sid,
        user=user,
        ip_address=_request_ip(request),
    )
    if refresh_token:
        _set_refresh_cookie(
            response,
            refresh_token,
            max_age_seconds=(_normalize_session_ttl_days(user) + 7) * 24 * 3600,
        )

    scope_token = _build_login_scope_token(db, snapshot)

    # Store confirmed state in Redis
    data["status"] = "confirmed"
    data["access_token"] = token
    data["scope_token"] = scope_token
    data["refresh_token"] = refresh_token
    data["user_snapshot"] = _json.dumps(snapshot)
    await redis_client.setex(
        session_key,
        60,  # keep for 60 seconds for polling
        _json.dumps(data),
    )
    try:
        await redis_client.delete(f"qr:secret:{payload.secret}")
    except Exception:
        logger.debug("Failed to delete qr:secret during confirm", exc_info=True)

    _safe_audit_log(
        db,
        action="qr_login_success",
        success=True,
        user_id=int(user.id),
        ip_address=data.get("ip", "unknown"),
        details={"telegram_id": telegram_id, "telegram_username": telegram_username},
    )

    return {"ok": True}


def _validate_telegram_init_data(init_data: str) -> tuple:
    """Validate Telegram WebApp initData using HMAC-SHA256.
    Returns (telegram_id, username) or (None, None) on failure.
    """
    try:
        parsed = parse_qs(init_data)
        check_hash = parsed.get("hash", [""])[0]
        if not check_hash:
            return None, None

        # Freshness check: reject init_data older than TELEGRAM_INIT_DATA_TTL seconds
        # (default 600s = 10 min). Defends against replay of captured tokens.
        try:
            import time as _time

            auth_date_raw = parsed.get("auth_date", [""])[0]
            if auth_date_raw:
                auth_ts = int(auth_date_raw)
                ttl = int(os.getenv("TELEGRAM_INIT_DATA_TTL", "600"))
                if _time.time() - auth_ts > ttl:
                    return None, None
        except Exception:  # noqa: BLE001
            return None, None

        # Build data check string
        items = []
        for key, values in sorted(parsed.items()):
            if key == "hash":
                continue
            items.append(f"{key}={values[0]}")
        data_check_string = "\n".join(items)

        # HMAC validation
        secret_key = hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(computed_hash, check_hash):
            return None, None

        # Extract user info
        import json as _json
        user_str = parsed.get("user", [""])[0]
        if not user_str:
            return None, None
        user_data = _json.loads(user_str)
        return int(user_data.get("id", 0)), user_data.get("username", "")
    except Exception:
        return None, None


class InvalidateSessionRequest(BaseModel):
    token: Optional[str] = None


@router.post("/session/invalidate")
async def invalidate_session(
    request: Request,
    response: Response,
    payload: Optional[InvalidateSessionRequest] = None,
):
    """Best-effort session cleanup called from Electron/browser on close via sendBeacon."""
    # 1. Delete refresh cookie
    _clear_refresh_cookie(response)

    # 2. Revoke active session if we can decode the access token
    access_token = (payload.token if payload else None) or ""
    if access_token:
        try:
            decoded = verify_jwt_token(access_token)
            if decoded and decoded.get("sid"):
                await revoke_active_session(decoded["sid"])
        except Exception:
            logger.debug("Failed to revoke active session on invalidate_session", exc_info=True)

    # 3. Revoke refresh token family from cookie
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if refresh_token:
        try:
            decoded_refresh = verify_jwt_token(refresh_token)
            if decoded_refresh and decoded_refresh.get("family_id"):
                await revoke_refresh_family(decoded_refresh["family_id"])
        except Exception:
            logger.debug("Failed to revoke refresh family on invalidate_session", exc_info=True)

    return {"ok": True}


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    response: Response,
    payload: Optional[RefreshRequest] = None,
    authorization: Optional[str] = Header(None),
):
    """Logout current user and invalidate token."""
    token = authorization.replace("Bearer ", "") if authorization and authorization.startswith("Bearer ") else None
    refresh_token = (
        (payload.refresh_token if payload else None)
        or request.headers.get("x-refresh-token")
        or request.cookies.get(REFRESH_COOKIE_NAME)
    )
    try:
        success = False
        if token:
            success = await logout_user(token) or success
        if refresh_token:
            success = await logout_user(refresh_token) or success
        _clear_refresh_cookie(response)
        if success:
            return LogoutResponse(success=True, message="Logged out successfully")
        return LogoutResponse(success=True, message="Already logged out")
    except Exception as e:
        logger.exception("Logout failed: %s", e)
        raise HTTPException(status_code=500, detail="logout_failed")


@router.get("/me", response_model=UserInfoResponse)
async def get_current_user_info(user: dict = Depends(get_current_app_user)):
    """Get current authenticated user information with RBAC snapshot."""
    return UserInfoResponse(
        id=int(user.get("id") or user.get("user_id") or 0),
        username=str(user.get("username") or user.get("user_id") or "unknown"),
        display_name=str(user.get("display_name") or user.get("username") or "User"),
        role=str(user.get("role") or "operator"),
        allowed_tabs=[str(x) for x in (user.get("allowed_tabs") or [])],
        allowed_folders=[int(x) for x in (user.get("allowed_folders") or [])],
        forbidden_periods=list(user.get("forbidden_periods") or []),
        allowed_sources=[int(x) for x in (user.get("allowed_sources") or [])],
        can_toggle_sources=bool(user.get("can_toggle_sources")),
        permissions_version=int(user.get("permissions_version") or 1),
        totp_enabled=bool(user.get("totp_enabled")),
        totp_confirmed_at=user.get("totp_confirmed_at"),
        force_2fa=bool(user.get("force_2fa")),
        session_ttl_days=int(user.get("session_ttl_days") or USER_SESSION_TTL_DEFAULT_DAYS),
        exp=user.get("exp"),
    )


@router.get("/verify")
async def verify_token(user: dict = Depends(resolve_current_user)):
    """Verify token validity and permissions version."""
    return {
        "valid": True,
        "user_id": _safe_user_id(user),
        "permissions_version": int(user.get("permissions_version") or 1) if isinstance(user, dict) else 1,
        "role": user.get("role") if isinstance(user, dict) else None,
    }
