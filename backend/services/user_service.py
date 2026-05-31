"""User service for RBAC login and admin CRUD."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import User
from services.access_control_service import hash_password, verify_password
from services.root_access_config_service import hash_password_argon2, verify_secret

LOGIN_MAX_ATTEMPTS = int(os.getenv("USER_LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_LOCKOUT_MINUTES = int(os.getenv("USER_LOGIN_LOCKOUT_MINUTES", "15"))
PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "8"))
SESSION_TTL_DAYS_DEFAULT = int(os.getenv("USER_SESSION_TTL_DAYS_DEFAULT", "7"))
SESSION_TTL_DAYS_MIN = int(os.getenv("USER_SESSION_TTL_DAYS_MIN", "1"))
SESSION_TTL_DAYS_MAX = int(os.getenv("USER_SESSION_TTL_DAYS_MAX", "90"))

ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
VALID_ROLES = {ROLE_ADMIN, ROLE_OPERATOR}
ALL_TABS = ["dashboard", "reference", "automation", "userbot", "logs", "admin"]
DEFAULT_OPERATOR_TABS = ["dashboard"]

logger = logging.getLogger(__name__)


class UserServiceError(ValueError):
    pass


def _utcnow() -> datetime:
    return datetime.utcnow()


def _json_list(raw: Optional[str], *, default: Optional[List[Any]] = None) -> List[Any]:
    if not raw:
        return list(default or [])
    try:
        payload = json.loads(raw)
    except Exception:
        return list(default or [])
    if isinstance(payload, list):
        return payload
    return list(default or [])


def _normalize_tabs(tabs: Optional[List[Any]], *, role: str) -> List[str]:
    if role == ROLE_ADMIN:
        return list(ALL_TABS)
    raw = tabs if tabs is not None else list(DEFAULT_OPERATOR_TABS)
    normalized: List[str] = []
    for item in raw:
        value = str(item or "").strip().lower()
        if not value:
            continue
        if value == "transactions":
            value = "dashboard"
        if value in ALL_TABS and value != "admin":
            normalized.append(value)
    if "dashboard" not in normalized:
        normalized.insert(0, "dashboard")
    return sorted(set(normalized), key=lambda x: ALL_TABS.index(x) if x in ALL_TABS else 999)


def _normalize_int_list(values: Optional[List[Any]]) -> List[int]:
    normalized: List[int] = []
    for item in values or []:
        try:
            value = int(item)
        except Exception:
            continue
        normalized.append(value)
    return sorted(set(normalized))


def _normalize_forbidden_periods(periods: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    for period in periods or []:
        if not isinstance(period, dict):
            continue
        date_from = str(period.get("from") or "").strip()
        date_to = str(period.get("to") or "").strip()
        if not date_from or not date_to:
            continue
        result.append({"from": date_from, "to": date_to})
    return result


def _validate_role(role: str) -> str:
    value = (role or ROLE_OPERATOR).strip().lower()
    if value not in VALID_ROLES:
        raise UserServiceError("invalid_role")
    return value


def _validate_username(username: str) -> str:
    value = (username or "").strip()
    if not value:
        raise UserServiceError("invalid_username")
    if len(value) > 50:
        raise UserServiceError("invalid_username")
    return value


def validate_password_strength(password: str) -> None:
    raw = str(password or "")
    if len(raw) < PASSWORD_MIN_LENGTH:
        raise UserServiceError("weak_password")
    has_upper = any(ch.isalpha() and ch.isupper() for ch in raw)
    has_lower = any(ch.isalpha() and ch.islower() for ch in raw)
    has_digit = any(ch.isdigit() for ch in raw)
    has_symbol = any(not ch.isalnum() for ch in raw)
    if not (has_upper and has_lower and has_digit and has_symbol):
        raise UserServiceError("weak_password")


def _normalize_session_ttl_days(value: Optional[Any]) -> int:
    try:
        ttl = int(value if value is not None else SESSION_TTL_DAYS_DEFAULT)
    except Exception:
        ttl = SESSION_TTL_DAYS_DEFAULT
    ttl = max(int(SESSION_TTL_DAYS_MIN), min(int(SESSION_TTL_DAYS_MAX), ttl))
    return ttl


def build_permissions_snapshot(user: User) -> Dict[str, Any]:
    role = (user.role or ROLE_OPERATOR).strip().lower()
    is_admin = role == ROLE_ADMIN

    allowed_tabs = _normalize_tabs(_json_list(user.allowed_tabs, default=DEFAULT_OPERATOR_TABS), role=role)
    allowed_folders = [] if is_admin else _normalize_int_list(_json_list(user.allowed_folders, default=[]))
    allowed_sources = [] if is_admin else _normalize_int_list(_json_list(user.allowed_sources, default=[]))
    forbidden_periods = [] if is_admin else _normalize_forbidden_periods(_json_list(user.forbidden_periods, default=[]))

    return {
        "id": int(user.id),
        "user_id": int(user.id),
        "username": user.username,
        "display_name": user.display_name or user.username,
        "role": role,
        "is_active": bool(user.is_active),
        "allowed_tabs": allowed_tabs,
        "allowed_folders": allowed_folders,
        "forbidden_periods": forbidden_periods,
        "allowed_sources": allowed_sources,
        "can_toggle_sources": True if is_admin else bool(user.can_toggle_sources),
        "permissions_version": int(user.permissions_version or 1),
        "totp_enabled": bool(user.totp_enabled),
        "totp_confirmed_at": user.totp_confirmed_at.isoformat() if user.totp_confirmed_at else None,
        "force_2fa": bool(user.force_2fa),
        "session_ttl_days": _normalize_session_ttl_days(user.session_ttl_days),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def increment_permissions_version(user: User) -> None:
    current = int(user.permissions_version or 1)
    user.permissions_version = current + 1


def _verify_user_password(user: User, password_raw: str) -> bool:
    method = str(user.hash_method or "pbkdf2_sha256").strip().lower()
    if method in {"argon2", "argon2id"}:
        return verify_secret(
            password_raw,
            {
                "kind": "argon2id",
                "hash": str(user.password_hash or ""),
                "active": True,
            },
        )
    return verify_password(password_raw, str(user.password_hash or ""), str(user.salt or ""))


def _hash_user_password(password_raw: str) -> Tuple[str, str, str]:
    try:
        argon_hash = hash_password_argon2(password_raw)
        return argon_hash, "", "argon2id"
    except Exception:
        logger.debug("argon2 unavailable, fallback to pbkdf2 for user password hashing", exc_info=True)
        password_hash, salt = hash_password(password_raw)
        return password_hash, salt, "pbkdf2_sha256"


def _try_upgrade_user_password_hash(user: User, password_raw: str) -> bool:
    method = str(user.hash_method or "pbkdf2_sha256").strip().lower()
    if method not in {"pbkdf2", "pbkdf2_sha256", "legacy_pbkdf2"}:
        return False
    try:
        argon_hash = hash_password_argon2(password_raw)
    except Exception:
        logger.debug("argon2 upgrade skipped for user_id=%s", getattr(user, "id", None), exc_info=True)
        return False
    user.password_hash = argon_hash
    user.salt = ""
    user.hash_method = "argon2id"
    return True


def authenticate(db: Session, username: str, password: str) -> Tuple[Optional[User], Dict[str, Any]]:
    username_norm = (username or "").strip().lower()
    password_raw = password or ""
    if not username_norm or not password_raw:
        return None, {"error": "invalid_credentials"}

    user = (
        db.query(User)
        .filter(func.lower(User.username) == username_norm)
        .first()
    )
    if not user:
        return None, {"error": "invalid_credentials"}

    if not user.is_active:
        return None, {"error": "inactive_user"}

    now = _utcnow()
    if user.locked_until and user.locked_until > now:
        locked_seconds = max(1, int((user.locked_until - now).total_seconds()))
        return None, {"error": "locked", "locked_seconds": locked_seconds}

    if not _verify_user_password(user, password_raw):
        user.failed_attempts = int(user.failed_attempts or 0) + 1
        attempts_left = max(0, int(LOGIN_MAX_ATTEMPTS) - int(user.failed_attempts))
        if attempts_left <= 0:
            user.failed_attempts = int(LOGIN_MAX_ATTEMPTS)
            user.locked_until = now + timedelta(minutes=max(1, int(LOGIN_LOCKOUT_MINUTES)))
            db.commit()
            return None, {
                "error": "locked",
                "locked_seconds": max(1, int(LOGIN_LOCKOUT_MINUTES) * 60),
                "attempts_left": 0,
            }
        db.commit()
        return None, {"error": "invalid_credentials", "attempts_left": attempts_left}

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    _try_upgrade_user_password_hash(user, password_raw)
    db.commit()
    db.refresh(user)
    return user, {"ok": True}


def list_users(db: Session, include_inactive: bool = True) -> List[User]:
    query = db.query(User)
    if not include_inactive:
        query = query.filter(User.is_active.is_(True))
    return query.order_by(User.id.asc()).all()


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    return db.get(User, int(user_id))


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    username_norm = (username or "").strip().lower()
    if not username_norm:
        return None
    return db.query(User).filter(func.lower(User.username) == username_norm).first()


def create_user(
    db: Session,
    *,
    username: str,
    password: str,
    role: str = ROLE_OPERATOR,
    display_name: Optional[str] = None,
    allowed_tabs: Optional[List[Any]] = None,
    allowed_folders: Optional[List[Any]] = None,
    forbidden_periods: Optional[List[Dict[str, Any]]] = None,
    allowed_sources: Optional[List[Any]] = None,
    can_toggle_sources: bool = False,
    force_2fa: bool = False,
    session_ttl_days: Optional[int] = None,
    is_active: bool = True,
    telegram_id: Optional[int] = None,
    telegram_username: Optional[str] = None,
) -> User:
    username_norm = _validate_username(username)
    role_norm = _validate_role(role)

    if get_user_by_username(db, username_norm):
        raise UserServiceError("username_exists")

    if not password:
        raise UserServiceError("invalid_password")
    validate_password_strength(password)

    # Check telegram_id uniqueness if provided
    if telegram_id is not None:
        existing_tg = db.query(User).filter(User.telegram_id == telegram_id).first()
        if existing_tg:
            raise UserServiceError("telegram_id_already_linked")

    password_hash, salt, hash_method = _hash_user_password(password)
    user = User(
        username=username_norm,
        password_hash=password_hash,
        salt=salt,
        hash_method=hash_method,
        role=role_norm,
        display_name=(display_name or username_norm).strip()[:100],
        is_active=bool(is_active),
        allowed_tabs=json.dumps(_normalize_tabs(allowed_tabs, role=role_norm), ensure_ascii=False),
        allowed_folders=json.dumps(_normalize_int_list(allowed_folders), ensure_ascii=False),
        forbidden_periods=json.dumps(_normalize_forbidden_periods(forbidden_periods), ensure_ascii=False),
        allowed_sources=json.dumps(_normalize_int_list(allowed_sources), ensure_ascii=False),
        can_toggle_sources=bool(can_toggle_sources),
        force_2fa=bool(force_2fa),
        session_ttl_days=_normalize_session_ttl_days(session_ttl_days),
        failed_attempts=0,
        locked_until=None,
        permissions_version=1,
        telegram_id=telegram_id,
        telegram_username=(telegram_username or "").strip()[:255] or None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(
    db: Session,
    user: User,
    *,
    role: Optional[str] = None,
    display_name: Optional[str] = None,
    is_active: Optional[bool] = None,
    allowed_tabs: Optional[List[Any]] = None,
    allowed_folders: Optional[List[Any]] = None,
    forbidden_periods: Optional[List[Dict[str, Any]]] = None,
    allowed_sources: Optional[List[Any]] = None,
    can_toggle_sources: Optional[bool] = None,
    force_2fa: Optional[bool] = None,
    session_ttl_days: Optional[int] = None,
    password: Optional[str] = None,
) -> User:
    new_role = _validate_role(role) if role is not None else (user.role or ROLE_OPERATOR)

    permissions_changed = False

    if role is not None and user.role != new_role:
        user.role = new_role
        permissions_changed = True

    if display_name is not None:
        user.display_name = display_name.strip()[:100] if str(display_name).strip() else user.username

    if is_active is not None and bool(user.is_active) != bool(is_active):
        user.is_active = bool(is_active)
        permissions_changed = True

    if can_toggle_sources is not None and bool(user.can_toggle_sources) != bool(can_toggle_sources):
        user.can_toggle_sources = bool(can_toggle_sources)
        permissions_changed = True

    if force_2fa is not None and bool(user.force_2fa) != bool(force_2fa):
        user.force_2fa = bool(force_2fa)
        permissions_changed = True

    if session_ttl_days is not None:
        normalized_ttl = _normalize_session_ttl_days(session_ttl_days)
        if int(user.session_ttl_days or SESSION_TTL_DAYS_DEFAULT) != normalized_ttl:
            user.session_ttl_days = normalized_ttl
            permissions_changed = True

    if any(value is not None for value in (allowed_tabs, role)):
        tabs = _normalize_tabs(allowed_tabs if allowed_tabs is not None else _json_list(user.allowed_tabs), role=new_role)
        user.allowed_tabs = json.dumps(tabs, ensure_ascii=False)
        permissions_changed = True

    if allowed_folders is not None:
        user.allowed_folders = json.dumps(_normalize_int_list(allowed_folders), ensure_ascii=False)
        permissions_changed = True

    if forbidden_periods is not None:
        user.forbidden_periods = json.dumps(_normalize_forbidden_periods(forbidden_periods), ensure_ascii=False)
        permissions_changed = True

    if allowed_sources is not None:
        user.allowed_sources = json.dumps(_normalize_int_list(allowed_sources), ensure_ascii=False)
        permissions_changed = True

    if password is not None:
        if not password:
            raise UserServiceError("invalid_password")
        validate_password_strength(password)
        password_hash, salt, hash_method = _hash_user_password(password)
        user.password_hash = password_hash
        user.salt = salt
        user.hash_method = hash_method
        user.failed_attempts = 0
        user.locked_until = None
        permissions_changed = True

    if permissions_changed:
        increment_permissions_version(user)

    db.commit()
    db.refresh(user)
    return user


def reset_password(db: Session, user: User, password: str) -> User:
    return update_user(db, user, password=password)


def unlock_user(db: Session, user: User) -> User:
    user.failed_attempts = 0
    user.locked_until = None
    db.commit()
    db.refresh(user)
    return user


def deactivate_user(db: Session, user: User) -> User:
    if not user.is_active:
        return user
    user.is_active = False
    increment_permissions_version(user)
    db.commit()
    db.refresh(user)
    return user
