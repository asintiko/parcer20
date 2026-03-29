"""Root access config loading and verification helpers.

This module centralizes:
- mandatory server config loading
- system access token verification
- scope source-of-truth loading from config
- Argon2 + legacy PBKDF2 compatibility checks
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
    ARGON2_AVAILABLE = True
except Exception:  # pragma: no cover - optional runtime dependency fallback
    PasswordHasher = None  # type: ignore
    InvalidHashError = VerificationError = VerifyMismatchError = Exception  # type: ignore
    ARGON2_AVAILABLE = False


SERVER_CONFIG_ENV = "ROOT_ACCESS_SERVER_CONFIG_PATH"
SERVER_CONFIG_DEFAULT = "security/root-access.server.json"
SYSTEM_ACCESS_ENFORCED_ENV = "SYSTEM_ACCESS_ENFORCED"
SCOPES_MANAGED_BY_CONFIG_ENV = "SCOPES_MANAGED_BY_CONFIG"

# Keep PBKDF2 params aligned with existing access_control_service legacy hashing.
PBKDF2_ITERATIONS = 200_000

# Tuned to a practical default for desktop/server verification.
ARGON2_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4) if ARGON2_AVAILABLE else None


_lock = threading.Lock()
_cache: Dict[str, Any] = {
    "path": None,
    "mtime": None,
    "loaded": False,
    "error": "not_loaded",
    "data": None,
}


def reset_root_access_cache() -> None:
    with _lock:
        _cache.update(
            {
                "path": None,
                "mtime": None,
                "loaded": False,
                "error": "not_loaded",
                "data": None,
            }
        )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def scopes_managed_by_config() -> bool:
    return _env_bool(SCOPES_MANAGED_BY_CONFIG_ENV, True)


def system_access_enforced() -> bool:
    return _env_bool(SYSTEM_ACCESS_ENFORCED_ENV, True)


def get_server_config_path() -> str:
    return (os.getenv(SERVER_CONFIG_ENV) or SERVER_CONFIG_DEFAULT).strip()


def _dt_from_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _to_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat()


def _normalize_years(values: Any) -> List[int]:
    if not isinstance(values, list):
        return []
    out: List[int] = []
    for item in values:
        try:
            year = int(item)
        except Exception:
            continue
        if 1970 <= year <= 2200:
            out.append(year)
    return sorted(set(out))


def hash_password_pbkdf2(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    generated_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        generated_salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    )
    encoded = base64.b64encode(digest).decode("ascii")
    return encoded, generated_salt


def verify_password_pbkdf2(password: str, stored_hash: str, salt: str) -> bool:
    candidate, _ = hash_password_pbkdf2(password=password, salt=salt)
    return secrets.compare_digest(candidate, stored_hash)


def hash_password_argon2(password: str) -> str:
    if not ARGON2_AVAILABLE or ARGON2_HASHER is None:
        raise RuntimeError("argon2-cffi is not installed")
    return ARGON2_HASHER.hash(password)


def _verify_argon2(secret: str, stored_hash: str) -> bool:
    if not ARGON2_AVAILABLE or ARGON2_HASHER is None:
        return False
    try:
        return ARGON2_HASHER.verify(stored_hash, secret)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def _normalize_secret_record(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    kind = str(payload.get("kind") or "argon2id").strip().lower()
    active = bool(payload.get("active", True))

    if kind == "argon2id":
        hash_value = str(payload.get("hash") or "").strip()
        if not hash_value:
            return None
        return {
            "kind": "argon2id",
            "hash": hash_value,
            "active": active,
            "rotated": bool(payload.get("rotated", False)),
        }

    if kind in {"pbkdf2_sha256", "legacy_pbkdf2"}:
        hash_value = str(payload.get("hash") or "").strip()
        salt = str(payload.get("salt") or "").strip()
        if not hash_value or not salt:
            return None
        return {
            "kind": "pbkdf2_sha256",
            "hash": hash_value,
            "salt": salt,
            "active": active,
            "rotated": bool(payload.get("rotated", False)),
        }

    return None


def verify_secret(secret: str, secret_record: Optional[Dict[str, Any]]) -> bool:
    if not secret_record:
        return False
    kind = secret_record.get("kind")
    if kind == "argon2id":
        return _verify_argon2(secret, str(secret_record.get("hash") or ""))
    if kind == "pbkdf2_sha256":
        hash_value = str(secret_record.get("hash") or "")
        salt = str(secret_record.get("salt") or "")
        if not hash_value or not salt:
            return False
        return verify_password_pbkdf2(secret, hash_value, salt)
    return False


def _normalize_scope(item: Dict[str, Any], fallback_id: int) -> Optional[Dict[str, Any]]:
    name = str(item.get("name") or "").strip()
    if not name:
        return None

    # Password record can be either nested under "password" or legacy flat fields.
    password_record_raw = item.get("password")
    if isinstance(password_record_raw, dict):
        secret_record = _normalize_secret_record(password_record_raw)
    else:
        legacy_payload = {
            "kind": item.get("password_kind") or ("pbkdf2_sha256" if item.get("password_hash") and item.get("salt") else "argon2id"),
            "hash": item.get("password_hash") or item.get("hash"),
            "salt": item.get("salt"),
            "active": item.get("is_active", True),
            "rotated": item.get("rotated", False),
        }
        secret_record = _normalize_secret_record(legacy_payload)

    if not secret_record:
        return None

    years = _normalize_years(item.get("years") or [])
    period_start = _dt_from_iso(item.get("period_start"))
    period_end = _dt_from_iso(item.get("period_end"))
    if period_start and period_end and period_start > period_end:
        period_start, period_end = period_end, period_start

    raw_id = item.get("id")
    try:
        scope_id = int(raw_id)
    except Exception:
        scope_id = fallback_id

    return {
        "id": scope_id,
        "name": name,
        "years": years,
        "period_start": _to_iso(period_start),
        "period_end": _to_iso(period_end),
        "allow_transactions": bool(item.get("allow_transactions", True)),
        "allow_sources": bool(item.get("allow_sources", False)),
        "is_active": bool(item.get("is_active", True)),
        "password": secret_record,
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }


def _normalize_tokens(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    system_access = payload.get("system_access")
    source = system_access if isinstance(system_access, dict) else payload
    tokens_raw = source.get("tokens")
    if not isinstance(tokens_raw, list):
        return []

    tokens: List[Dict[str, Any]] = []
    for idx, token in enumerate(tokens_raw, start=1):
        if not isinstance(token, dict):
            continue
        token_id = str(token.get("id") or f"token-{idx}").strip()
        secret_record = _normalize_secret_record(token)
        if not secret_record:
            continue
        tokens.append(
            {
                "id": token_id,
                "active": bool(token.get("active", True)),
                "secret": secret_record,
            }
        )
    return tokens


def read_existing_tokens(path: Path | str) -> List[Dict[str, Any]]:
    """
    Best-effort read of existing token records from a config file.
    Returns normalized records suitable to place under system_access.tokens.
    """
    try:
        raw_path = Path(path)
        if not raw_path.exists() or not raw_path.is_file():
            return []
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return []
        normalized = _normalize_tokens(payload)
        out: List[Dict[str, Any]] = []
        for token in normalized:
            secret = token.get("secret") or {}
            record = {
                "id": token.get("id"),
                "kind": secret.get("kind"),
                "hash": secret.get("hash"),
                "active": bool(token.get("active", True)),
                "rotated": bool(secret.get("rotated", False)),
            }
            if secret.get("salt"):
                record["salt"] = secret.get("salt")
            out.append(record)
        return out
    except Exception:
        return []


def _normalize_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    tokens = _normalize_tokens(payload)

    scopes_raw = payload.get("scopes")
    if not isinstance(scopes_raw, list):
        scopes_raw = []

    scopes: List[Dict[str, Any]] = []
    for idx, item in enumerate(scopes_raw, start=1):
        if not isinstance(item, dict):
            continue
        normalized = _normalize_scope(item, fallback_id=idx)
        if normalized:
            scopes.append(normalized)

    config_enforced = True
    if isinstance(payload.get("system_access"), dict):
        config_enforced = bool(payload["system_access"].get("enforced", True))

    return {
        "version": int(payload.get("version") or 1),
        "system_access": {
            "enforced": config_enforced,
            "tokens": tokens,
        },
        "scopes": scopes,
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    }


def _read_config_file(path: str) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[float]]:
    config_path = Path(path)
    if not config_path.exists():
        return None, f"Root access config not found: {path}", None
    if not config_path.is_file():
        return None, f"Root access config path is not a file: {path}", None

    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except Exception as exc:
        return None, f"Failed to read root access config: {exc}", None

    try:
        payload = json.loads(raw_text)
    except Exception as exc:
        return None, f"Invalid JSON in root access config: {exc}", None

    if not isinstance(payload, dict):
        return None, "Root access config must be a JSON object", None

    try:
        normalized = _normalize_config(payload)
    except Exception as exc:
        return None, f"Invalid root access config structure: {exc}", None

    if not normalized["system_access"]["tokens"]:
        return None, "Root access config has no active system tokens", None

    return normalized, None, config_path.stat().st_mtime


def get_server_config_state(force_reload: bool = False) -> Dict[str, Any]:
    path = get_server_config_path()
    enforced = system_access_enforced()

    if not enforced:
        return {
            "enforced": False,
            "path": path,
            "loaded": True,
            "error": None,
            "data": None,
        }

    with _lock:
        if not force_reload and _cache["path"] == path:
            try:
                current_mtime = Path(path).stat().st_mtime
            except Exception:
                current_mtime = None
            if _cache["loaded"] and _cache["mtime"] == current_mtime:
                return {
                    "enforced": True,
                    "path": path,
                    "loaded": True,
                    "error": None,
                    "data": _cache["data"],
                }
            if not _cache["loaded"] and current_mtime is None:
                return {
                    "enforced": True,
                    "path": path,
                    "loaded": False,
                    "error": _cache["error"],
                    "data": None,
                }

        data, error, mtime = _read_config_file(path)
        _cache.update(
            {
                "path": path,
                "mtime": mtime,
                "loaded": error is None,
                "error": error,
                "data": data,
            }
        )
        return {
            "enforced": True,
            "path": path,
            "loaded": error is None,
            "error": error,
            "data": data,
        }


def is_system_blocked() -> Tuple[bool, Optional[str]]:
    state = get_server_config_state()
    if not state["enforced"]:
        return False, None
    if not state["loaded"]:
        return True, state.get("error") or "root_access_config_missing"
    return False, None


def verify_system_access_token(token: Optional[str]) -> Tuple[bool, Optional[str], Optional[str]]:
    state = get_server_config_state()
    if not state["enforced"]:
        return True, None, None

    if not state["loaded"]:
        return False, None, state.get("error") or "root_access_config_missing"

    token = (token or "").strip()
    if not token:
        return False, None, "Missing X-System-Access token"

    tokens = state["data"]["system_access"]["tokens"]
    for entry in tokens:
        if not entry.get("active", True):
            continue
        if verify_secret(token, entry.get("secret")):
            return True, str(entry.get("id") or "token"), None

    return False, None, "Invalid X-System-Access token"


def get_config_scopes(active_only: bool = False) -> List[Dict[str, Any]]:
    state = get_server_config_state()
    if not state["loaded"] or not state.get("data"):
        return []

    scopes = list(state["data"].get("scopes") or [])
    if active_only:
        scopes = [scope for scope in scopes if bool(scope.get("is_active", True))]
    return scopes


def has_active_config_scopes() -> bool:
    return any(bool(scope.get("is_active", True)) for scope in get_config_scopes(active_only=True))


def find_scope_for_unlock(
    password: str,
    *,
    target_year: Optional[int],
    action: str,
) -> Optional[Dict[str, Any]]:
    if not password:
        return None

    for scope in get_config_scopes(active_only=True):
        years = _normalize_years(scope.get("years") or [])
        start = _dt_from_iso(scope.get("period_start"))
        end = _dt_from_iso(scope.get("period_end"))

        if target_year is not None:
            if years and target_year not in years:
                continue
            if start and target_year < start.year:
                continue
            if end and target_year > end.year:
                continue

        if action == "sources" and not bool(scope.get("allow_sources", False)):
            continue
        if action == "transactions" and not bool(scope.get("allow_transactions", True)):
            continue

        if verify_secret(password, scope.get("password")):
            return scope

    return None


def get_available_scope_years() -> List[int]:
    years: set[int] = set()
    for scope in get_config_scopes(active_only=True):
        for year in _normalize_years(scope.get("years") or []):
            years.add(year)
        start = _dt_from_iso(scope.get("period_start"))
        end = _dt_from_iso(scope.get("period_end"))
        if start is None and end is None:
            continue
        if start is None:
            start = end
        if end is None:
            end = start
        if start is None or end is None:
            continue
        lo, hi = sorted((start.year, end.year))
        if hi - lo > 50:
            continue
        for year in range(lo, hi + 1):
            years.add(year)
    return sorted(years)


def get_system_access_status() -> Dict[str, Any]:
    state = get_server_config_state()
    return {
        "enforced": bool(state.get("enforced", False)),
        "path": state.get("path"),
        "loaded": bool(state.get("loaded", False)),
        "error": state.get("error"),
        "scopes_managed_by_config": scopes_managed_by_config(),
        "available_scope_count": len(get_config_scopes(active_only=False)) if state.get("loaded") else 0,
    }
