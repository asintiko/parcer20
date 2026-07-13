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
from services.auth_bot_service import (
    SessionStoreUnavailableError,
    is_active_session,
    touch_active_session,
    verify_launch_session_token,
)
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
    test_envs = {"test", "testing"}
    if allow_insecure and env_name in test_envs:
        return False

    logger.warning(
        "AUTH_REQUIRED=false ignored. Set ALLOW_INSECURE_NO_AUTH=true in a "
        "declared test environment to allow unauthenticated test access."
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


async def require_session_active(payload: Optional[Dict[str, Any]]) -> str:
    """Require a registered, non-revoked server-side session."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=401, detail="invalid_session")
    sid = str(payload.get("sid") or "").strip()
    if not sid:
        raise HTTPException(status_code=401, detail="missing_session_id")
    token_kind = str(payload.get("kind") or "").strip()
    expected_kind = "app_user" if token_kind in {"app_user", "refresh_token"} else token_kind
    try:
        active = await is_active_session(sid, expected_kind=expected_kind or None)
    except SessionStoreUnavailableError as exc:
        logger.error("Session store unavailable while authenticating sid=%s: %s", sid, exc)
        raise HTTPException(status_code=503, detail="session_store_unavailable") from exc
    if not active:
        raise HTTPException(status_code=401, detail="session_inactive")
    return sid


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
    token_kind = str(payload.get("kind") or "").lower()
    if token_kind != "app_user":
        return None
    await require_session_active(payload)
    user_id = _to_int(payload.get("sub") or payload.get("user_id"))
    if not user_id:
        return None
    row = db.get(User, user_id)
    if not row:
        return None
    if not row.is_active:
        return None
    token_version = _to_int(payload.get("permissions_version"))
    db_version = int(row.permissions_version or 1)
    if token_version != db_version:
        return None
    snapshot = build_permissions_snapshot(row)
    snapshot["token_kind"] = "app_user"
    snapshot["exp"] = payload.get("exp")
    snapshot["phone"] = payload.get("phone")
    try:
        await touch_active_session(str(payload["sid"]))
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
    token_kind = str(payload.get("kind") or "").lower()
    if token_kind != "app_user":
        raise HTTPException(
            status_code=401,
            detail="invalid_token_purpose",
            headers={"WWW-Authenticate": "Bearer"},
        )
    await require_session_active(payload)

    user_id = _to_int(payload.get("sub") or payload.get("user_id"))
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    row = db.get(User, user_id)
    if not row:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not row.is_active:
        raise HTTPException(status_code=403, detail="inactive_user")
    token_version = _to_int(payload.get("permissions_version"))
    db_version = int(row.permissions_version or 1)
    if token_version != db_version:
        raise HTTPException(status_code=401, detail="permissions_outdated")
    snapshot = build_permissions_snapshot(row)
    snapshot["token_kind"] = "app_user"
    snapshot["exp"] = payload.get("exp")
    snapshot["phone"] = payload.get("phone")
    try:
        await touch_active_session(str(payload["sid"]))
    except Exception:
        pass
    return snapshot


async def get_current_app_user(
    current_user: dict = Depends(get_current_user),
) -> dict:
    if current_user.get("role") and str(current_user.get("token_kind") or "").lower() in {"app_user", "local"}:
        return current_user
    raise HTTPException(
        status_code=401,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


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


def configured_export_keys() -> List[str]:
    """
    Active read-only transactions-export keys in priority order.

    Consumed by the Excel Power Query live sheet (`GET /api/transactions/export.csv`).
    Rotation mirrors the mobile ingest key:
    - TRANSACTIONS_EXPORT_KEY: current primary key.
    - TRANSACTIONS_EXPORT_KEY_PREVIOUS: prior key still accepted during rollout,
      so operators on an older workbook keep pulling until they get the new file.
      Drop PREVIOUS once every workbook has been re-issued.
    """
    keys: List[str] = []
    for value in (
        os.getenv("TRANSACTIONS_EXPORT_KEY", ""),
        os.getenv("TRANSACTIONS_EXPORT_KEY_PREVIOUS", ""),
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
    decoded_payload = decode_scope_token(token) if token else None
    payload = _resolve_current_scope_payload(db, decoded_payload) if decoded_payload else None
    if token and not payload:
        try:
            write_audit_log(
                db,
                action="scope_stale_or_invalid",
                success=False,
                ip_address=_extract_client_ip(conn),
                details={"path": str(conn.url.path)},
            )
        except Exception:
            pass
        raise HTTPException(status_code=403, detail="Scoped access token is stale or invalid")

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
    await require_session_active(payload)
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


async def require_export_key(
    conn: HTTPConnection,
    db: Session = Depends(get_db_session),
    x_export_key: Optional[str] = Header(None, alias="X-Export-Key"),
) -> None:
    """
    Validate the dedicated read-only key for the transactions CSV export.

    Used by the Excel live sheet, which re-pulls once a minute per operator, so
    success is intentionally NOT audit-logged (only failures) to keep audit_log
    from being flooded by routine refreshes.
    """
    ip = _extract_client_ip(conn)
    path = str(conn.url.path)
    configured_keys = configured_export_keys()
    if not configured_keys:
        try:
            write_audit_log(
                db,
                action="transactions_export_auth_fail",
                success=False,
                ip_address=ip,
                details={"path": path, "reason": "export_key_not_configured"},
            )
        except Exception:
            pass
        raise HTTPException(status_code=503, detail="Transactions export key is not configured")

    provided_key = (x_export_key or "").strip()
    if not provided_key or not any(
        secrets.compare_digest(provided_key, key) for key in configured_keys
    ):
        try:
            write_audit_log(
                db,
                action="transactions_export_auth_fail",
                success=False,
                ip_address=ip,
                details={"path": path, "reason": "invalid_export_key"},
            )
        except Exception:
            pass
        raise HTTPException(status_code=403, detail="Invalid X-Export-Key")


def _normalized_scope_datetime(value: Any) -> Optional[str]:
    parsed = _parse_iso_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.isoformat()


def _scope_claims_match(token_payload: Dict[str, Any], current: Dict[str, Any]) -> bool:
    return (
        str(token_payload.get("scope_name") or "") == str(current.get("scope_name") or "")
        and _normalize_int_list(token_payload.get("years")) == _normalize_int_list(current.get("years"))
        and _normalized_scope_datetime(token_payload.get("date_from")) == _normalized_scope_datetime(current.get("date_from"))
        and _normalized_scope_datetime(token_payload.get("date_to")) == _normalized_scope_datetime(current.get("date_to"))
        and bool(token_payload.get("allow_transactions", True)) == bool(current.get("allow_transactions", True))
        and bool(token_payload.get("allow_sources", False)) == bool(current.get("allow_sources", False))
    )


def _resolve_current_scope_payload(
    db: Session,
    token_payload: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not token_payload:
        return None
    scope_id = _to_int(token_payload.get("scope_id"))
    if scope_id is None:
        return None

    row = db.get(AccessScope, scope_id)
    if row is not None:
        if not row.is_active:
            return None
        current = {
            "scope_id": int(row.id),
            "scope_name": row.name,
            "years": years_from_json(row.years_json),
            "date_from": row.period_start.isoformat() if row.period_start else None,
            "date_to": row.period_end.isoformat() if row.period_end else None,
            "allow_transactions": bool(row.allow_transactions),
            "allow_sources": bool(row.allow_sources),
        }
        if not _scope_claims_match(token_payload, current):
            return None
        issued_at = _to_int(token_payload.get("iat"))
        if issued_at is None:
            return None
        if row.updated_at is not None and issued_at < int(row.updated_at.timestamp()):
            return None
        return current

    for configured in get_config_scopes(active_only=True):
        public = config_scope_to_public_dict(configured)
        if _to_int(public.get("id")) != scope_id:
            continue
        current = {
            "scope_id": scope_id,
            "scope_name": public.get("name"),
            "years": public.get("years") or [],
            "date_from": public.get("period_start"),
            "date_to": public.get("period_end"),
            "allow_transactions": bool(public.get("allow_transactions", True)),
            "allow_sources": bool(public.get("allow_sources", False)),
        }
        if not _scope_claims_match(token_payload, current):
            return None
        issued_at = _to_int(token_payload.get("iat"))
        if issued_at is None:
            return None
        config_updated_at = _parse_iso_datetime(public.get("updated_at"))
        if config_updated_at is not None and issued_at < int(config_updated_at.timestamp()):
            return None
        return current
    return None
