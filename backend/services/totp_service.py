"""TOTP 2FA service."""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import secrets
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pyotp
import qrcode
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from database.models import User


TOTP_ISSUER_NAME = os.getenv("TOTP_ISSUER_NAME", "PARCER 2.0").strip() or "PARCER 2.0"
TOTP_BACKUP_CODES_COUNT = max(1, int(os.getenv("TOTP_BACKUP_CODES_COUNT", "10")))
TOTP_VALID_WINDOW = max(0, int(os.getenv("TOTP_VALID_WINDOW", "1")))

logger = logging.getLogger(__name__)

# Fernet key for encrypting TOTP secrets and backup codes at rest.
# Must be a URL-safe base64-encoded 32-byte key, generated with Fernet.generate_key().
# If unset, secrets are stored in plaintext (transition mode) and a warning is emitted once.
# Set TOTP_ENC_KEY to enable encryption. All newly written rows will be encrypted;
# use scripts/migrate_totp_encryption.py to re-encrypt existing plaintext rows.
_TOTP_ENC_KEY_RAW: Optional[str] = os.getenv("TOTP_ENC_KEY", "").strip() or None
_fernet_instance: Optional[Fernet] = None
_totp_enc_warned = False

# Prefix used to distinguish Fernet-encrypted ciphertext from plaintext values.
_FERNET_PREFIX = "fernet:"


def _get_fernet() -> Optional[Fernet]:
    """Return the Fernet cipher, or None if TOTP_ENC_KEY is not configured."""
    global _fernet_instance, _totp_enc_warned
    if _TOTP_ENC_KEY_RAW:
        if _fernet_instance is None:
            try:
                key_bytes = _TOTP_ENC_KEY_RAW.encode()
                _fernet_instance = Fernet(key_bytes)
            except Exception as exc:
                raise EnvironmentError(
                    f"TOTP_ENC_KEY is set but is not a valid Fernet key: {exc}"
                ) from exc
        return _fernet_instance
    if not _totp_enc_warned:
        logger.warning(
            "TOTP_ENC_KEY is not set — TOTP secrets and backup codes are stored in plaintext. "
            "Generate a key with 'python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"' "
            "and set TOTP_ENC_KEY to enable encryption at rest."
        )
        _totp_enc_warned = True
    return None


def _encrypt(plaintext: str) -> str:
    """Encrypt a string, returning a prefixed ciphertext. Falls back to plaintext if key unset."""
    fernet = _get_fernet()
    if fernet is None:
        return plaintext
    ciphertext = fernet.encrypt(plaintext.encode()).decode()
    return f"{_FERNET_PREFIX}{ciphertext}"


def _decrypt(value: str) -> str:
    """Decrypt a value produced by _encrypt. Returns plaintext for unencrypted legacy values."""
    if not value.startswith(_FERNET_PREFIX):
        return value
    fernet = _get_fernet()
    if fernet is None:
        # Key was removed after encryption — we cannot decrypt. Raise to surface misconfiguration.
        raise EnvironmentError(
            "TOTP_ENC_KEY is unset but an encrypted TOTP value was found in the database. "
            "Restore TOTP_ENC_KEY to the key used when the value was encrypted."
        )
    try:
        return fernet.decrypt(value[len(_FERNET_PREFIX):].encode()).decode()
    except InvalidToken as exc:
        raise ValueError("TOTP value could not be decrypted — key mismatch or corrupted value") from exc


def _utcnow() -> datetime:
    return datetime.utcnow()


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def get_totp_uri(user: User) -> str:
    if not user.totp_secret:
        raise ValueError("totp_secret is not set")
    raw_secret = _decrypt(str(user.totp_secret))
    totp = pyotp.TOTP(raw_secret)
    account_name = (user.username or f"user-{user.id}").strip() or f"user-{user.id}"
    return totp.provisioning_uri(name=account_name, issuer_name=TOTP_ISSUER_NAME)


def generate_qr_base64(uri: str) -> str:
    image = qrcode.make(uri)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def generate_backup_codes(count: int = TOTP_BACKUP_CODES_COUNT) -> List[str]:
    return [secrets.token_hex(8).upper() for _ in range(max(1, int(count)))]


def _set_backup_codes(user: User, codes: List[str]) -> None:
    normalized = [str(code).strip().upper() for code in codes]
    serialized = json.dumps(normalized, ensure_ascii=False)
    user.backup_codes = _encrypt(serialized)


def _read_backup_codes(user: User) -> List[str]:
    raw = user.backup_codes
    if not raw:
        return []
    try:
        serialized = _decrypt(str(raw))
        payload = json.loads(serialized)
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [str(item).strip().upper() for item in payload if str(item).strip()]


def enable_2fa_setup(db: Session, user: User) -> Dict[str, object]:
    secret = generate_totp_secret()
    user.totp_secret = _encrypt(secret)
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
    raw_secret = _decrypt(str(user.totp_secret))
    totp = pyotp.TOTP(raw_secret)
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
