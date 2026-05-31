"""Runtime global security settings service."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from database.models import SystemSettings


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, str(default))).strip().lower()
    return raw in {"1", "true", "yes", "on"}


SETTINGS_CACHE_TTL_SECONDS = int(os.getenv("SYSTEM_SETTINGS_CACHE_TTL_SECONDS", "10"))

_cache_lock = Lock()
_cache_expires_at: Optional[datetime] = None
_cache_data: Optional[Dict[str, Any]] = None


def _utcnow() -> datetime:
    return datetime.utcnow()


def invalidate_settings_cache() -> None:
    global _cache_data, _cache_expires_at
    with _cache_lock:
        _cache_data = None
        _cache_expires_at = None


def _row_to_dict(row: SystemSettings) -> Dict[str, Any]:
    return {
        "id": int(row.id),
        "otp_enabled": bool(row.otp_enabled),
        "bot_control_enabled": bool(row.bot_control_enabled),
        "totp_2fa_enabled": bool(row.totp_2fa_enabled),
        "launch_gate_enabled": bool(row.launch_gate_enabled),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "updated_by": int(row.updated_by) if row.updated_by is not None else None,
    }


def get_settings(db: Session) -> SystemSettings:
    row = db.get(SystemSettings, 1)
    if row is not None:
        return row

    row = SystemSettings(
        id=1,
        otp_enabled=_env_bool("OTP_ENABLED_DEFAULT", True),
        bot_control_enabled=_env_bool("BOT_CONTROL_ENABLED_DEFAULT", True),
        totp_2fa_enabled=_env_bool("TOTP_2FA_ENABLED_DEFAULT", False),
        launch_gate_enabled=_env_bool("LAUNCH_GATE_ENABLED_DEFAULT", False),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    invalidate_settings_cache()
    return row


def get_settings_snapshot(db: Session, *, fresh: bool = False) -> Dict[str, Any]:
    global _cache_data, _cache_expires_at

    if not fresh:
        with _cache_lock:
            if _cache_data is not None and _cache_expires_at is not None and _cache_expires_at > _utcnow():
                return dict(_cache_data)

    row = get_settings(db)
    snapshot = _row_to_dict(row)
    with _cache_lock:
        _cache_data = dict(snapshot)
        _cache_expires_at = _utcnow() + timedelta(seconds=max(1, SETTINGS_CACHE_TTL_SECONDS))
    return snapshot


def update_settings(
    db: Session,
    *,
    otp_enabled: Optional[bool] = None,
    bot_control_enabled: Optional[bool] = None,
    totp_2fa_enabled: Optional[bool] = None,
    launch_gate_enabled: Optional[bool] = None,
    updated_by: Optional[int] = None,
) -> SystemSettings:
    row = get_settings(db)
    if otp_enabled is not None:
        row.otp_enabled = bool(otp_enabled)
    if bot_control_enabled is not None:
        row.bot_control_enabled = bool(bot_control_enabled)
    if totp_2fa_enabled is not None:
        row.totp_2fa_enabled = bool(totp_2fa_enabled)
    if launch_gate_enabled is not None:
        row.launch_gate_enabled = bool(launch_gate_enabled)
    if updated_by is not None:
        row.updated_by = int(updated_by)

    db.commit()
    db.refresh(row)
    invalidate_settings_cache()
    return row


def is_otp_enabled(db: Session) -> bool:
    return bool(get_settings_snapshot(db).get("otp_enabled", True))


def is_bot_control_enabled(db: Session) -> bool:
    return bool(get_settings_snapshot(db).get("bot_control_enabled", True))


def is_totp_2fa_enabled(db: Session) -> bool:
    return bool(get_settings_snapshot(db).get("totp_2fa_enabled", False))


def is_launch_gate_enabled(db: Session) -> bool:
    return bool(get_settings_snapshot(db).get("launch_gate_enabled", False))
