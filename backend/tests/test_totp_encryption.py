"""Unit tests for TOTP Fernet encryption in totp_service."""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Skip entire module if cryptography or pyotp are unavailable.
pytest.importorskip("cryptography")
pytest.importorskip("pyotp")
pytest.importorskip("qrcode")


def _fresh_module(env: dict[str, str]):
    """Import a clean copy of totp_service with the given environment."""
    # Reload is needed because module-level globals cache state.
    import services.totp_service as mod
    importlib.reload(mod)
    return mod


@pytest.fixture()
def enc_key() -> str:
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


@pytest.fixture()
def totp_mod_with_key(enc_key, monkeypatch):
    monkeypatch.setenv("TOTP_ENC_KEY", enc_key)
    import services.totp_service as mod
    importlib.reload(mod)
    yield mod
    importlib.reload(mod)  # reset after test


@pytest.fixture()
def totp_mod_no_key(monkeypatch):
    monkeypatch.delenv("TOTP_ENC_KEY", raising=False)
    import services.totp_service as mod
    importlib.reload(mod)
    yield mod
    importlib.reload(mod)


class TestFernetHelpers:
    def test_encrypt_decrypt_roundtrip(self, totp_mod_with_key):
        mod = totp_mod_with_key
        plaintext = "JBSWY3DPEHPK3PXP"
        ciphertext = mod._encrypt(plaintext)
        assert ciphertext.startswith("fernet:")
        assert ciphertext != plaintext
        assert mod._decrypt(ciphertext) == plaintext

    def test_decrypt_plaintext_passthrough(self, totp_mod_with_key):
        mod = totp_mod_with_key
        # Values without the prefix must pass through unchanged (legacy rows).
        assert mod._decrypt("JBSWY3DPEHPK3PXP") == "JBSWY3DPEHPK3PXP"

    def test_no_key_encrypt_returns_plaintext(self, totp_mod_no_key):
        mod = totp_mod_no_key
        plaintext = "JBSWY3DPEHPK3PXP"
        assert mod._encrypt(plaintext) == plaintext

    def test_no_key_decrypt_passthrough(self, totp_mod_no_key):
        mod = totp_mod_no_key
        assert mod._decrypt("JBSWY3DPEHPK3PXP") == "JBSWY3DPEHPK3PXP"

    def test_encrypted_value_without_key_raises(self, totp_mod_no_key):
        mod = totp_mod_no_key
        with pytest.raises(EnvironmentError, match="TOTP_ENC_KEY is unset"):
            mod._decrypt("fernet:someencryptedblob")

    def test_wrong_key_raises_value_error(self, enc_key, monkeypatch):
        from cryptography.fernet import Fernet
        # Encrypt with key A, attempt decrypt with key B.
        key_a = enc_key
        key_b = Fernet.generate_key().decode()
        monkeypatch.setenv("TOTP_ENC_KEY", key_a)
        import services.totp_service as mod
        importlib.reload(mod)
        ciphertext = mod._encrypt("secret")

        monkeypatch.setenv("TOTP_ENC_KEY", key_b)
        importlib.reload(mod)
        with pytest.raises(ValueError, match="could not be decrypted"):
            mod._decrypt(ciphertext)
        importlib.reload(mod)


def _make_user(db_session, username: str, **kwargs):
    """Create a minimal User row without importing hash_password (avoids JWT_SECRET requirement)."""
    from database.models import User
    user = User(
        username=username,
        password_hash="x",
        salt="x",
        role="operator",
        display_name=username,
        allowed_tabs="[]",
        allowed_folders="[]",
        forbidden_periods="[]",
        allowed_sources="[]",
        is_active=True,
        **kwargs,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


class TestBackupCodeRoundtrip:
    def test_set_and_read_backup_codes_encrypted(self, totp_mod_with_key, db_session):
        mod = totp_mod_with_key
        user = _make_user(db_session, "enc_test")

        codes = ["AABBCCDD11223344", "EEFF00112233AABB"]
        mod._set_backup_codes(user, codes)
        db_session.commit()

        # The stored value should be Fernet-encrypted.
        assert str(user.backup_codes).startswith("fernet:")

        # Reading back must return the original codes.
        recovered = mod._read_backup_codes(user)
        assert recovered == [c.upper() for c in codes]

    def test_set_and_read_backup_codes_plaintext(self, totp_mod_no_key, db_session):
        mod = totp_mod_no_key
        user = _make_user(db_session, "plain_test")

        codes = ["AABB1122CCDD3344"]
        mod._set_backup_codes(user, codes)
        db_session.commit()

        # Without encryption, raw value is plain JSON.
        assert not str(user.backup_codes).startswith("fernet:")
        recovered = mod._read_backup_codes(user)
        assert recovered == [c.upper() for c in codes]


class TestVerifyWithEncryptedSecret:
    def test_verify_totp_encrypted_secret(self, totp_mod_with_key, db_session):
        """verify_2fa_code must work when totp_secret is Fernet-encrypted."""
        import pyotp
        mod = totp_mod_with_key
        user = _make_user(db_session, "totp_enc_user", totp_enabled=True)

        raw_secret = pyotp.random_base32()
        user.totp_secret = mod._encrypt(raw_secret)
        mod._set_backup_codes(user, ["DEADBEEF01020304"])
        db_session.commit()

        totp = pyotp.TOTP(raw_secret)
        code = totp.now()
        ok, method = mod.verify_2fa_code(db_session, user, code)
        assert ok is True
        assert method == "totp"

    def test_backup_code_verify_encrypted(self, totp_mod_with_key, db_session):
        import pyotp
        mod = totp_mod_with_key
        user = _make_user(db_session, "totp_bkp_user", totp_enabled=True)

        raw_secret = pyotp.random_base32()
        user.totp_secret = mod._encrypt(raw_secret)
        backup_code = "DEADBEEF01020304"
        mod._set_backup_codes(user, [backup_code])
        db_session.commit()

        ok, method = mod.verify_2fa_code(db_session, user, backup_code)
        assert ok is True
        assert method == "backup_code"

        # Code must be consumed (single-use).
        ok2, _ = mod.verify_2fa_code(db_session, user, backup_code)
        assert ok2 is False


class TestBackupCodeLength:
    def test_backup_code_is_16_hex_chars(self, totp_mod_with_key):
        mod = totp_mod_with_key
        codes = mod.generate_backup_codes(count=5)
        assert len(codes) == 5
        for code in codes:
            # token_hex(8) → 16 hex chars, uppercased
            assert len(code) == 16
            assert code == code.upper()
