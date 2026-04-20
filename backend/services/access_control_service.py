"""Scoped access control helpers: passwords, lockouts, scope JWT, and audits."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from database.models import AccessAuditLog, AccessLockout, AccessScope
from services.root_access_config_service import (
    get_config_scopes,
    has_active_config_scopes,
)


LOCKOUT_MAX_ATTEMPTS = int(os.getenv("ACCESS_LOCKOUT_MAX_ATTEMPTS", "5"))
LOCKOUT_MINUTES = int(os.getenv("ACCESS_LOCKOUT_MINUTES", "15"))
SCOPE_TOKEN_TTL_HOURS = int(os.getenv("ACCESS_SCOPE_TOKEN_TTL_HOURS", "12"))
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

if not JWT_SECRET:
    raise EnvironmentError("JWT_SECRET environment variable is required")


def _now_naive() -> datetime:
    return datetime.utcnow().replace(tzinfo=None)


def _to_iso(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    return value.replace(microsecond=0).isoformat()


def _from_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def normalize_years(values: Optional[Iterable[int]]) -> List[int]:
    if not values:
        return []
    normalized: List[int] = []
    for year in values:
        try:
            y = int(year)
        except Exception:
            continue
        if 1970 <= y <= 2200:
            normalized.append(y)
    return sorted(set(normalized))


def years_to_json(values: Optional[Iterable[int]]) -> Optional[str]:
    years = normalize_years(values)
    if not years:
        return None
    return json.dumps(years)


def years_from_json(value: Optional[str]) -> List[int]:
    if not value:
        return []
    try:
        payload = json.loads(value)
        if isinstance(payload, list):
            return normalize_years(payload)
    except Exception:
        return []
    return []


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    if not password:
        raise ValueError("Password cannot be empty")
    generated_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        generated_salt.encode("utf-8"),
        200_000,
    )
    encoded = base64.b64encode(digest).decode("ascii")
    return encoded, generated_salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    candidate, _ = hash_password(password=password, salt=salt)
    return secrets.compare_digest(candidate, stored_hash)


def scope_to_public_dict(scope: AccessScope) -> Dict[str, Any]:
    return {
        "id": int(scope.id),
        "name": scope.name,
        "years": years_from_json(scope.years_json),
        "period_start": _to_iso(scope.period_start),
        "period_end": _to_iso(scope.period_end),
        "allow_transactions": bool(scope.allow_transactions),
        "allow_sources": bool(scope.allow_sources),
        "is_active": bool(scope.is_active),
        "created_at": scope.created_at.isoformat() if scope.created_at else None,
        "updated_at": scope.updated_at.isoformat() if scope.updated_at else None,
    }


def config_scope_to_public_dict(scope: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": int(scope.get("id") or 0),
        "name": str(scope.get("name") or ""),
        "years": normalize_years(scope.get("years") or []),
        "period_start": _to_iso(_from_iso(scope.get("period_start"))),
        "period_end": _to_iso(_from_iso(scope.get("period_end"))),
        "allow_transactions": bool(scope.get("allow_transactions", True)),
        "allow_sources": bool(scope.get("allow_sources", False)),
        "is_active": bool(scope.get("is_active", True)),
        "created_at": scope.get("created_at"),
        "updated_at": scope.get("updated_at"),
    }


def create_scope_token(scope: AccessScope) -> str:
    return create_scope_token_from_values(
        scope_id=int(scope.id),
        scope_name=scope.name,
        years=years_from_json(scope.years_json),
        date_from=_to_iso(scope.period_start),
        date_to=_to_iso(scope.period_end),
        allow_transactions=bool(scope.allow_transactions),
        allow_sources=bool(scope.allow_sources),
    )


def create_scope_token_from_values(
    *,
    scope_id: int,
    scope_name: str,
    years: Optional[Iterable[int]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    allow_transactions: bool = True,
    allow_sources: bool = False,
) -> str:
    now = _now_naive()
    exp = now + timedelta(hours=max(1, SCOPE_TOKEN_TTL_HOURS))
    payload = {
        "kind": "scope_access",
        "scope_id": int(scope_id),
        "scope_name": str(scope_name),
        "years": normalize_years(years or []),
        "date_from": _to_iso(_from_iso(date_from)),
        "date_to": _to_iso(_from_iso(date_to)),
        "allow_transactions": bool(allow_transactions),
        "allow_sources": bool(allow_sources),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_scope_token(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("kind") != "scope_access":
        return None
    return payload


def has_active_scopes(db: Session) -> bool:
    db_has = db.query(AccessScope.id).filter(AccessScope.is_active.is_(True)).first() is not None
    cfg_has = has_active_config_scopes()
    return db_has or cfg_has


def list_active_scopes(db: Session) -> List[Dict[str, Any]]:
    rows = db.query(AccessScope).filter(AccessScope.is_active.is_(True)).order_by(AccessScope.id.asc()).all()
    by_id = {int(row.id): scope_to_public_dict(row) for row in rows}
    for scope in get_config_scopes(active_only=True):
        payload = config_scope_to_public_dict(scope)
        scope_id = int(payload.get("id") or 0)
        if scope_id not in by_id:
            by_id[scope_id] = payload
    return [item for _, item in sorted(by_id.items(), key=lambda kv: kv[0])]


def is_scope_valid_for_action(scope_payload: Dict[str, Any], require_sources: bool = False) -> bool:
    if not scope_payload:
        return False
    if require_sources and not bool(scope_payload.get("allow_sources")):
        return False
    if not require_sources and not bool(scope_payload.get("allow_transactions", True)):
        return False
    return True


def get_scope_window(scope_payload: Optional[Dict[str, Any]]) -> Tuple[Optional[datetime], Optional[datetime], List[int]]:
    if not scope_payload:
        return None, None, []
    date_from = _from_iso(scope_payload.get("date_from"))
    date_to = _from_iso(scope_payload.get("date_to"))
    years = normalize_years(scope_payload.get("years") or [])
    return date_from, date_to, years


def is_datetime_allowed(scope_payload: Optional[Dict[str, Any]], value: Optional[datetime]) -> bool:
    if not scope_payload or value is None:
        return True
    date_from, date_to, years = get_scope_window(scope_payload)
    if date_from and value < date_from:
        return False
    if date_to and value > date_to:
        return False
    if years and value.year not in years:
        return False
    return True


def clamp_requested_range(
    scope_payload: Optional[Dict[str, Any]],
    requested_from: Optional[datetime],
    requested_to: Optional[datetime],
) -> Tuple[Optional[datetime], Optional[datetime], bool]:
    """
    Returns effective_from, effective_to, is_disjoint.
    """
    if not scope_payload:
        return requested_from, requested_to, False

    scope_from, scope_to, years = get_scope_window(scope_payload)
    effective_from = requested_from
    effective_to = requested_to

    if scope_from and (effective_from is None or effective_from < scope_from):
        effective_from = scope_from
    if scope_to and (effective_to is None or effective_to > scope_to):
        effective_to = scope_to
    if effective_from and effective_to and effective_from > effective_to:
        return effective_from, effective_to, True

    if years and effective_from and effective_to:
        overlapping = [y for y in years if effective_from.year <= y <= effective_to.year]
        if not overlapping:
            return effective_from, effective_to, True

    return effective_from, effective_to, False


def get_lockout(db: Session, lock_key: str) -> Optional[AccessLockout]:
    return db.query(AccessLockout).filter(AccessLockout.lock_key == lock_key).first()


def check_lockout(db: Session, lock_key: str) -> Tuple[bool, Optional[datetime]]:
    row = get_lockout(db, lock_key)
    now = _now_naive()
    if row and row.blocked_until and row.blocked_until > now:
        return True, row.blocked_until
    return False, None


def record_failed_attempt(db: Session, lock_key: str) -> AccessLockout:
    row = get_lockout(db, lock_key)
    now = _now_naive()
    if row is None:
        row = AccessLockout(lock_key=lock_key, failed_attempts=0)
        db.add(row)
        db.flush()

    row.failed_attempts = int(row.failed_attempts or 0) + 1
    row.last_failed_at = now
    if row.failed_attempts >= LOCKOUT_MAX_ATTEMPTS:
        row.blocked_until = now + timedelta(minutes=max(1, LOCKOUT_MINUTES))
        row.failed_attempts = 0
    db.commit()
    db.refresh(row)
    return row


def clear_failed_attempts(db: Session, lock_key: str) -> None:
    row = get_lockout(db, lock_key)
    if not row:
        return
    row.failed_attempts = 0
    row.blocked_until = None
    row.last_failed_at = None
    db.commit()


def write_audit_log(
    db: Session,
    *,
    action: str,
    success: bool,
    scope_id: Optional[int] = None,
    user_id: Optional[int] = None,
    ip_address: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    entry = AccessAuditLog(
        action=action[:80],
        success=bool(success),
        scope_id=scope_id,
        user_id=user_id,
        ip_address=(ip_address or "")[:64] or None,
        details_json=json.dumps(details or {}, ensure_ascii=False) if details else None,
    )
    db.add(entry)
    db.commit()
