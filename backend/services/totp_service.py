"""TOTP 2FA service."""
from __future__ import annotations

import base64
import io
import json
import os
import secrets
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pyotp
import qrcode
from sqlalchemy.orm import Session

from database.models import User


TOTP_ISSUER_NAME = os.getenv("TOTP_ISSUER_NAME", "PARCER 2.0").strip() or "PARCER 2.0"
TOTP_BACKUP_CODES_COUNT = max(1, int(os.getenv("TOTP_BACKUP_CODES_COUNT", "10")))
TOTP_VALID_WINDOW = max(0, int(os.getenv("TOTP_VALID_WINDOW", "1")))


def _utcnow() -> datetime:
    return datetime.utcnow()


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def get_totp_uri(user: User) -> str:
    if not user.totp_secret:
        raise ValueError("totp_secret is not set")
    totp = pyotp.TOTP(user.totp_secret)
    account_name = (user.username or f"user-{user.id}").strip() or f"user-{user.id}"
    return totp.provisioning_uri(name=account_name, issuer_name=TOTP_ISSUER_NAME)


def generate_qr_base64(uri: str) -> str:
    image = qrcode.make(uri)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def generate_backup_codes(count: int = TOTP_BACKUP_CODES_COUNT) -> List[str]:
    return [secrets.token_hex(4).upper() for _ in range(max(1, int(count)))]


def _set_backup_codes(user: User, codes: List[str]) -> None:
    user.backup_codes = json.dumps([str(code).strip().upper() for code in codes], ensure_ascii=False)


def _read_backup_codes(user: User) -> List[str]:
    raw = user.backup_codes
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [str(item).strip().upper() for item in payload if str(item).strip()]


def enable_2fa_setup(db: Session, user: User) -> Dict[str, object]:
    secret = generate_totp_secret()
    user.totp_secret = secret
    user.totp_enabled = False
    user.totp_confirmed_at = None
    codes = generate_backup_codes()
    _set_backup_codes(user, codes)
    db.commit()
    db.refresh(user)

    uri = get_totp_uri(user)
    return {
        "secret": secret,
        "otpauth_uri": uri,
        "qr_code_base64": generate_qr_base64(uri),
        "backup_codes": codes,
    }


def _verify_totp(user: User, code: str) -> bool:
    if not user.totp_secret:
        return False
    normalized = str(code or "").strip()
    if not normalized:
        return False
    totp = pyotp.TOTP(user.totp_secret)
    return bool(totp.verify(normalized, valid_window=TOTP_VALID_WINDOW))


def _use_backup_code(db: Session, user: User, code: str) -> bool:
    normalized = str(code or "").strip().upper()
    if not normalized:
        return False
    codes = _read_backup_codes(user)
    if normalized not in codes:
        return False
    codes.remove(normalized)
    _set_backup_codes(user, codes)
    db.commit()
    db.refresh(user)
    return True


def confirm_2fa(db: Session, user: User, code: str) -> bool:
    if not user.totp_secret:
        return False
    if not _verify_totp(user, code):
        return False
    user.totp_enabled = True
    user.totp_confirmed_at = _utcnow()
    db.commit()
    db.refresh(user)
    return True


def verify_2fa_code(db: Session, user: User, code: str) -> Tuple[bool, str]:
    if not user.totp_enabled or not user.totp_secret:
        return False, "2fa_not_enabled"
    if _verify_totp(user, code):
        return True, "totp"
    if _use_backup_code(db, user, code):
        return True, "backup_code"
    return False, "invalid_code"


def regenerate_backup_codes(db: Session, user: User, *, count: int = TOTP_BACKUP_CODES_COUNT) -> List[str]:
    codes = generate_backup_codes(count=count)
    _set_backup_codes(user, codes)
    db.commit()
    db.refresh(user)
    return codes


def disable_2fa(db: Session, user: User) -> None:
    user.totp_secret = None
    user.totp_enabled = False
    user.totp_confirmed_at = None
    user.backup_codes = None
    user.force_2fa = False
    db.commit()
    db.refresh(user)


def is_2fa_required(user: User) -> bool:
    return bool(user.totp_enabled and user.totp_secret)
