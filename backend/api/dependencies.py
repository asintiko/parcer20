"""
API Dependencies - Authentication and common dependencies
"""
import os
import secrets
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from fastapi import Header, HTTPException, Depends, Request
from starlette.requests import HTTPConnection

from database.connection import get_db_session
from database.models import AppLaunchConfig, AccessScope, User
from services.access_control_service import (
    config_scope_to_public_dict,
    decode_scope_token,
    has_active_scopes,
    is_scope_valid_for_action,
    years_from_json,
    write_audit_log,
)
from services.auth_bot_service import is_session_revoked, touch_active_session, verify_launch_session_token
from services.auth_service import verify_jwt_token
from services.internal_api_key_service import is_internal_request
from services.root_access_config_service import (
    get_config_scopes,
    system_access_enforced,
    verify_system_access_token,
)
from services.user_service import build_permissions_snapshot
from services.system_settings_service import is_launch_gate_enabled, is_otp_enabled
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, str(default))).strip().lower()
    return raw in ("true", "1", "yes", "on")


def _runtime_env_name() -> str:
    return str(
        os.getenv("APP_ENV")
        or os.getenv("ENVIRONMENT")
        or os.getenv("ENV")
        or os.getenv("FASTAPI_ENV")
        or ""
    ).strip().lower()


def _resolve_auth_required() -> bool:
    requested = _env_flag("AUTH_REQUIRED", True)
    if requested:
        return True

    # Only an explicit ALLOW_INSECURE_NO_AUTH unlocks unauthenticated mode, and
    # never when the environment is declared production. DEBUG=true and a bare
    # dev/test env name used to be sufficient on their own — that let a stray
    # prod .env flag silently disable auth, so both triggers were removed.
    allow_insecure = _env_flag("ALLOW_INSECURE_NO_AUTH", False)
    env_name = _runtime_env_name()
    prod_envs = {"prod", "production", "live"}
    if allow_insecure and env_name not in prod_envs:
        return False

    logger.warning(
        "AUTH_REQUIRED=false ignored. Set ALLOW_INSECURE_NO_AUTH=true in a "
        "non-production environment to allow unauthenticated local access."
    )
    return True


AUTH_REQUIRED = _resolve_auth_required()


def _now_naive():
    import datetime as _dt

    return _dt.datetime.utcnow()


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _extract_bearer_token(conn: HTTPConnection) -> Optional[str]:
    auth_header = conn.headers.get("authorization") or conn.headers.get("Authorization")
    if not auth_header:
        return None
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header[7:].strip()
    return token or None


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _session_revoked(payload: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(payload, dict):
        return False
    sid = str(payload.get("sid") or "").strip()
    if not sid:
        return False
    return bool(is_session_revoked(sid))


def _normalize_int_list(values: Any) -> List[int]:
    result: List[int] = []
    if not isinstance(values, list):
        return result
    for item in values:
        value = _to_int(item)
        if value is None:
            continue
        result.append(value)
    return sorted(set(result))


def _parse_forbidden_periods(user: Optional[Dict[str, Any]]) -> List[tuple[date, date]]:
    if not user:
        return []
    if str(user.get("role") or "").lower() == "admin":
        return []
    raw = user.get("forbidden_periods")
    if not isinstance(raw, list):
        return []
    periods: List[tuple[date, date]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        from_raw = item.get("from")
        to_raw = item.get("to")
        try:
            d_from = datetime.fromisoformat(str(from_raw)).date()
            d_to = datetime.fromisoformat(str(to_raw)).date()
        except Exception:
            continue
        if d_from > d_to:
            d_from, d_to = d_to, d_from
        periods.append((d_from, d_to))
    return periods


async def get_current_user_optional(
    conn: HTTPConnection,
    db: Session = Depends(get_db_session),
) -> Optional[dict]:
    """
    Get current user if authenticated, None otherwise.
    Use this for endpoints that work both with and without auth.
    """
    token = _extract_bearer_token(conn)
    if not token:
        return None

    payload = verify_jwt_token(token)
    if not payload:
        return None
    if _session_revoked(payload):
        return None
    user_id = _to_int(payload.get("sub") or payload.get("user_id"))
    if not user_id:
        return payload
    row = db.get(User, user_id)
    if not row:
        if str(payload.get("kind") or "").lower() == "qr_user":
            return {
                "id": user_id,
                "user_id": user_id,
                "username": f"qr_{user_id}",
                "display_name": payload.get("phone") or f"qr_{user_id}",
                "role": "operator",
                "allowed_tabs": ["dashboard"],
                "allowed_folders": [],
                "forbidden_periods": [],
                "allowed_sources": [],
                "can_toggle_sources": False,
                "permissions_version": 1,
                "session_ttl_days": 7,
                "token_kind": "qr_legacy",
                "exp": payload.get("exp"),
                "phone": payload.get("phone"),
            }
        return payload
    snapshot = build_permissions_snapshot(row)
    snapshot["token_kind"] = str(payload.get("kind") or "app_user")
    snapshot["exp"] = payload.get("exp")
    snapshot["phone"] = payload.get("phone")
    sid = str(payload.get("sid") or "").strip()
    if sid:
        try:
            await touch_active_session(sid)
        except Exception:
            pass
    return snapshot


async def get_current_user(
    conn: HTTPConnection,
    db: Session = Depends(get_db_session),
) -> dict:
    """
    Resolve current user from bearer token.
    In single-user local mode AUTH_REQUIRED can be disabled via env.
    """
    token = _extract_bearer_token(conn)
    if not token:
        if not AUTH_REQUIRED:
            return {
                "id": 1,
                "user_id": 1,
                "username": "local",
                "display_name": "Local Admin",
                "role": "admin",
                "allowed_tabs": ["dashboard", "reference", "automation", "userbot", "logs", "admin"],
                "allowed_folders": [],
                "forbidden_periods": [],
                "allowed_sources": [],
                "can_toggle_sources": True,
                "permissions_version": 1,
                "session_ttl_days": 7,
                "token_kind": "local",
                "phone": "local",
                "exp": None,
            }
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_jwt_token(token)
    if not payload:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    if _session_revoked(payload):
        raise HTTPException(
            status_code=401,
            detail="session_revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_kind = str(payload.get("kind") or "").lower()
    user_id = _to_int(payload.get("sub") or payload.get("user_id"))

    if user_id is not None:
        row = db.get(User, user_id)
        if row:
            if not row.is_active:
                raise HTTPException(status_code=403, detail="inactive_user")
            token_version = _to_int(payload.get("permissions_version"))
            db_version = int(row.permissions_version or 1)
            if token_version is not None and token_kind == "app_user" and token_version != db_version:
                raise HTTPException(status_code=401, detail="permissions_outdated")
            snapshot = build_permissions_snapshot(row)
            snapshot["token_kind"] = token_kind or "app_user"
            snapshot["exp"] = payload.get("exp")
            snapshot["phone"] = payload.get("phone")
            sid = str(payload.get("sid") or "").strip()
            if sid:
                try:
                    await touch_active_session(sid)
                except Exception:
                    pass
            return snapshot

    if token_kind == "qr_user":
        return {
            "id": user_id or 0,
            "user_id": user_id or 0,
            "username": f"qr_{user_id or 0}",
            "display_name": payload.get("phone") or f"qr_{user_id or 0}",
            "role": "operator",
            "allowed_tabs": ["dashboard"],
            "allowed_folders": [],
            "forbidden_periods": [],
            "allowed_sources": [],
            "can_toggle_sources": False,
            "permissions_version": 1,
            "session_ttl_days": 7,
            "token_kind": "qr_legacy",
            "exp": payload.get("exp"),
            "phone": payload.get("phone"),
        }

    if token_kind == "app_user":
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def get_current_app_user(
    current_user: dict = Depends(get_current_user),
) -> dict:
    if current_user.get("role"):
        return current_user
    # Compatibility shim for the QR/legacy login path, which returns a roleless
    # payload. Gate it to those token kinds only: without this check, ANY
    # signature-valid JWT that lacks a role (e.g. a refresh_token presented as a
    # bearer) was silently escalated to operator/dashboard access.
    kind = str(current_user.get("token_kind") or current_user.get("kind") or "").lower()
    if kind not in {"qr_user", "qr_legacy", "legacy"}:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {
        "id": _to_int(current_user.get("user_id")) or 0,
        "user_id": _to_int(current_user.get("user_id")) or 0,
        "username": str(current_user.get("user_id") or "legacy"),
        "display_name": str(current_user.get("phone") or "Legacy user"),
        "role": "operator",
        "allowed_tabs": ["dashboard"],
        "allowed_folders": [],
        "forbidden_periods": [],
        "allowed_sources": [],
        "can_toggle_sources": False,
        "permissions_version": 1,
        "session_ttl_days": 7,
        "token_kind": "legacy",
    }


async def require_admin_user(
    current_user: dict = Depends(get_current_app_user),
) -> dict:
    if str(current_user.get("role") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="admin_only")
    return current_user


def require_tab_access(tab_name: str):
    normalized = "dashboard" if tab_name in {"dashboard", "transactions"} else tab_name

    async def _dep(current_user: dict = Depends(get_current_app_user)) -> dict:
        role = str(current_user.get("role") or "").lower()
        if role == "admin":
            return current_user
        tabs = current_user.get("allowed_tabs")
        if not isinstance(tabs, list):
            tabs = []
        normalized_tabs = {str(item).strip().lower() for item in tabs if str(item).strip()}
        if normalized not in normalized_tabs:
            raise HTTPException(status_code=403, detail=f"tab_forbidden:{normalized}")
        return current_user

    return _dep


def get_allowed_sources_for_user(user: Optional[Dict[str, Any]]) -> Optional[set[int]]:
    if not user:
        return set()
    if str(user.get("role") or "").lower() == "admin":
        return None
    return set(_normalize_int_list(user.get("allowed_sources")))


def get_effective_folder_scope_for_user(
    user: Optional[Dict[str, Any]],
    db: Session,
) -> Optional[Dict[str, Any]]:
    if not user:
        return None
    if str(user.get("role") or "").lower() == "admin":
        return None

    folder_ids = _normalize_int_list(user.get("allowed_folders"))
    if not folder_ids:
        return {
            "scope_id": -1,
            "scope_name": "rbac-empty",
            "years": [],
            "date_from": "2100-01-01T00:00:00",
            "date_to": "2100-12-31T23:59:59",
            "allow_transactions": True,
            "allow_sources": False,
        }

    rows = (
        db.query(AccessScope)
        .filter(AccessScope.id.in_(folder_ids), AccessScope.is_active.is_(True))
        .all()
    )
    by_id: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        by_id[int(row.id)] = {
            "id": int(row.id),
            "years": years_from_json(row.years_json),
            "period_start": row.period_start.isoformat() if row.period_start else None,
            "period_end": row.period_end.isoformat() if row.period_end else None,
            "allow_sources": bool(row.allow_sources),
        }

    for cfg in get_config_scopes(active_only=True):
        payload = config_scope_to_public_dict(cfg)
        cfg_id = _to_int(payload.get("id"))
        if cfg_id is None or cfg_id in by_id:
            continue
        by_id[cfg_id] = {
            "id": cfg_id,
            "years": payload.get("years") or [],
            "period_start": payload.get("period_start"),
            "period_end": payload.get("period_end"),
            "allow_sources": bool(payload.get("allow_sources")),
        }

    selected = [by_id[idx] for idx in folder_ids if idx in by_id]
    if not selected:
        return {
            "scope_id": -1,
            "scope_name": "rbac-empty",
            "years": [],
            "date_from": "2100-01-01T00:00:00",
            "date_to": "2100-12-31T23:59:59",
            "allow_transactions": True,
            "allow_sources": False,
        }

    all_years: List[int] = []
    starts: List[datetime] = []
    ends: List[datetime] = []
    allow_sources = False
    for item in selected:
        all_years.extend(_normalize_int_list(item.get("years")))
        start_dt = _parse_iso_datetime(item.get("period_start"))
        end_dt = _parse_iso_datetime(item.get("period_end"))
        if start_dt:
            starts.append(start_dt)
        if end_dt:
            ends.append(end_dt)
        allow_sources = allow_sources or bool(item.get("allow_sources"))

    date_from = min(starts).isoformat() if starts else None
    date_to = max(ends).isoformat() if ends else None

    return {
        "scope_id": -2,
        "scope_name": "rbac-user-folders",
        "years": sorted(set(all_years)),
        "date_from": date_from,
        "date_to": date_to,
        "allow_transactions": True,
        "allow_sources": bool(allow_sources),
    }


def merge_scope_payloads(
    left: Optional[Dict[str, Any]],
    right: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if left and not right:
        return dict(left)
    if right and not left:
        return dict(right)
    if not left and not right:
        return None

    left = left or {}
    right = right or {}
    left_from = _parse_iso_datetime(left.get("date_from"))
    right_from = _parse_iso_datetime(right.get("date_from"))
    left_to = _parse_iso_datetime(left.get("date_to"))
    right_to = _parse_iso_datetime(right.get("date_to"))

    merged_from = max([dt for dt in (left_from, right_from) if dt], default=None)
    merged_to = min([dt for dt in (left_to, right_to) if dt], default=None)

    left_years = _normalize_int_list(left.get("years"))
    right_years = _normalize_int_list(right.get("years"))
    if left_years and right_years:
        years = sorted(set(left_years).intersection(right_years))
    else:
        years = left_years or right_years

    return {
        "scope_id": _to_int(left.get("scope_id")) or _to_int(right.get("scope_id")) or -9,
        "scope_name": str(left.get("scope_name") or right.get("scope_name") or "merged-scope"),
        "years": years,
        "date_from": merged_from.isoformat() if merged_from else None,
        "date_to": merged_to.isoformat() if merged_to else None,
        "allow_transactions": bool(left.get("allow_transactions", True)) and bool(right.get("allow_transactions", True)),
        "allow_sources": bool(left.get("allow_sources", False)) and bool(right.get("allow_sources", False)),
    }


def is_date_allowed_for_user(user: Optional[Dict[str, Any]], value: Optional[datetime]) -> bool:
    if value is None:
        return True
    forbidden_periods = _parse_forbidden_periods(user)
    if not forbidden_periods:
        return True
    target = value.date()
    for date_from, date_to in forbidden_periods:
        if date_from <= target <= date_to:
            return False
    return True


def require_auth():
    """Dependency that requires authentication"""
    return Depends(get_current_user)


def _extract_client_ip(conn: HTTPConnection) -> str:
    if conn.client and conn.client.host:
        return conn.client.host
    return "unknown"


def configured_mobile_ingest_keys() -> List[str]:
    """
    Active mobile ingest keys in priority order.

    Rotation mirrors the internal API key service:
    - MOBILE_SMS_INGEST_KEY: current primary key.
    - MOBILE_SMS_INGEST_KEY_PREVIOUS: prior key still accepted during rollout,
      so phones on the old APK keep ingesting until the new build is shipped.
      Drop PREVIOUS once every device has updated.
    """
    keys: List[str] = []
    for value in (
        os.getenv("MOBILE_SMS_INGEST_KEY", ""),
        os.getenv("MOBILE_SMS_INGEST_KEY_PREVIOUS", ""),
    ):
        normalized = str(value or "").strip()
        if normalized and normalized not in keys:
            keys.append(normalized)
    return keys


async def get_scope_context_optional(
    conn: HTTPConnection,
    db: Session = Depends(get_db_session),
    current_user: Optional[dict] = Depends(get_current_user_optional),
    x_access_token: Optional[str] = Header(None, alias="X-Access-Token"),
) -> Optional[Dict[str, Any]]:
    """
    Returns current scoped access payload.
    Enforcement mode:
    - If no active access scopes configured: token is optional and may be absent.
    - If at least one active scope exists: token becomes mandatory for protected endpoints.
    """
    otp_enabled = is_otp_enabled(db)
    scopes_enabled = has_active_scopes(db) and otp_enabled
    if is_internal_request(conn):
        return {
            "scope_id": 0,
            "scope_name": "internal-service",
            "allow_transactions": True,
            "allow_sources": True,
            "years": [],
            "date_from": None,
            "date_to": None,
        }
    token = x_access_token or conn.headers.get("x-access-token")
    payload = decode_scope_token(token) if token else None

    # Admin users always have full data access in RBAC v1,
    # even when scoped mode is enabled globally.
    if str((current_user or {}).get("role") or "").lower() == "admin":
        if payload:
            return payload
        return {
            "scope_id": -1,
            "scope_name": "admin-full-access",
            "allow_transactions": True,
            "allow_sources": True,
            "years": [],
            "date_from": None,
            "date_to": None,
        }

    if not scopes_enabled:
        return payload

    if not payload:
        try:
            write_audit_log(
                db,
                action="scope_missing",
                success=False,
                ip_address=_extract_client_ip(conn),
                details={"path": str(conn.url.path)},
            )
        except Exception:
            pass
        raise HTTPException(status_code=403, detail="Scoped access token required")

    return payload


async def get_system_access_context(
    conn: HTTPConnection,
    db: Session = Depends(get_db_session),
    x_system_access: Optional[str] = Header(None, alias="X-System-Access"),
) -> Optional[Dict[str, Any]]:
    """
    Mandatory system-level access verification for API calls when enabled.
    Middleware should perform this check first; this dependency acts as a safe
    fallback and provides a normalized context to route handlers.
    """
    if not system_access_enforced():
        return None

    state_payload = getattr(conn.state, "system_access", None)
    if isinstance(state_payload, dict) and state_payload.get("ok"):
        return state_payload

    ok, token_id, error = verify_system_access_token(x_system_access)
    if not ok:
        try:
            write_audit_log(
                db,
                action="system_token_invalid",
                success=False,
                ip_address=_extract_client_ip(conn),
                details={"error": error, "path": str(conn.url.path)},
            )
        except Exception:
            pass
        raise HTTPException(status_code=403, detail=error or "System access denied")

    try:
        write_audit_log(
            db,
            action="system_token_ok",
            success=True,
            ip_address=_extract_client_ip(conn),
            details={"token_id": token_id, "path": str(conn.url.path)},
        )
    except Exception:
        pass
    return {"ok": True, "token_id": token_id}


async def require_transactions_scope(
    conn: HTTPConnection,
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
    scope: Optional[Dict[str, Any]] = Depends(get_scope_context_optional),
    db: Session = Depends(get_db_session),
) -> Optional[Dict[str, Any]]:
    if scope and not is_scope_valid_for_action(scope, require_sources=False):
        try:
            write_audit_log(
                db,
                action="scope_forbidden_transactions",
                success=False,
                scope_id=scope.get("scope_id"),
                ip_address=_extract_client_ip(conn),
                details={"scope_name": scope.get("scope_name")},
            )
        except Exception:
            pass
        raise HTTPException(status_code=403, detail="Scope does not allow transaction access")
    return scope


async def require_sources_scope(
    conn: HTTPConnection,
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
    scope: Optional[Dict[str, Any]] = Depends(get_scope_context_optional),
    db: Session = Depends(get_db_session),
) -> Optional[Dict[str, Any]]:
    if scope and not is_scope_valid_for_action(scope, require_sources=True):
        try:
            write_audit_log(
                db,
                action="scope_forbidden_sources",
                success=False,
                scope_id=scope.get("scope_id"),
                ip_address=_extract_client_ip(conn),
                details={"scope_name": scope.get("scope_name")},
            )
        except Exception:
            pass
        raise HTTPException(status_code=403, detail="Scope does not allow source access")
    return scope


async def require_launch_session(
    conn: HTTPConnection,
    db: Session = Depends(get_db_session),
) -> None:
    try:
        launch_gate_enabled = is_launch_gate_enabled(db)
    except Exception:
        launch_gate_enabled = str(os.getenv("LAUNCH_GATE_ENABLED", "false")).strip().lower() in {
            "1", "true", "yes", "on"
        }
    if not launch_gate_enabled:
        return

    row = db.get(AppLaunchConfig, 1)
    if row is None:
        return
    token = conn.headers.get("x-launch-session")
    if not token:
        raise HTTPException(status_code=403, detail={"error": "launch_required"})
    payload = verify_launch_session_token(token)
    if not payload:
        raise HTTPException(status_code=403, detail={"error": "launch_expired"})
    if row.locked_until and row.locked_until > _now_naive():
        raise HTTPException(status_code=423, detail={"error": "launch_locked", "locked_until": row.locked_until.isoformat()})


async def require_mobile_ingest_key(
    conn: HTTPConnection,
    db: Session = Depends(get_db_session),
    x_mobile_ingest_key: Optional[str] = Header(None, alias="X-Mobile-Ingest-Key"),
) -> None:
    """
    Validate dedicated mobile ingestion key for /api/sms/* endpoints.
    """
    ip = _extract_client_ip(conn)
    path = str(conn.url.path)
    configured_keys = configured_mobile_ingest_keys()
    if not configured_keys:
        try:
            write_audit_log(
                db,
                action="sms_ingest_auth_fail",
                success=False,
                ip_address=ip,
                details={"path": path, "reason": "mobile_key_not_configured"},
            )
        except Exception:
            pass
        raise HTTPException(status_code=503, detail="Mobile SMS ingest key is not configured")

    provided_key = (x_mobile_ingest_key or "").strip()
    if not provided_key or not any(
        secrets.compare_digest(provided_key, key) for key in configured_keys
    ):
        try:
            write_audit_log(
                db,
                action="sms_ingest_auth_fail",
                success=False,
                ip_address=ip,
                details={"path": path, "reason": "invalid_mobile_key"},
            )
        except Exception:
            pass
        raise HTTPException(status_code=403, detail="Invalid X-Mobile-Ingest-Key")

    try:
        write_audit_log(
            db,
            action="sms_ingest_auth_ok",
            success=True,
            ip_address=ip,
            details={"path": path},
        )
    except Exception:
        pass
