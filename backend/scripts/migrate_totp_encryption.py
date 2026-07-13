"""Re-encrypt existing plaintext totp_secret and backup_codes rows with Fernet.

Run this ONCE after setting TOTP_ENC_KEY in your environment.
The script is idempotent: already-encrypted values (prefixed "fernet:") are skipped.
No data is modified if TOTP_ENC_KEY is unset.

Usage:
    TOTP_ENC_KEY=<your-key> python -m scripts.migrate_totp_encryption [--dry-run]

Generate a key if you don't have one:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _migrate(*, dry_run: bool) -> None:
    totp_enc_key = os.environ.get("TOTP_ENC_KEY", "").strip()
    if not totp_enc_key:
        print("ERROR: TOTP_ENC_KEY is not set. Set it before running this script.")
        sys.exit(1)

    # Import after sys.path is set so project packages resolve correctly.
    from cryptography.fernet import Fernet
    from database.connection import SessionLocal
    from database.models import User

    try:
        fernet = Fernet(totp_enc_key.encode())
    except Exception as exc:
        print(f"ERROR: TOTP_ENC_KEY is not a valid Fernet key: {exc}")
        sys.exit(1)

    _PREFIX = "fernet:"

    def _needs_encryption(value: str | None) -> bool:
        if not value:
            return False
        return not str(value).startswith(_PREFIX)

    def _encrypt(plaintext: str) -> str:
        return f"{_PREFIX}{fernet.encrypt(plaintext.encode()).decode()}"

    db = SessionLocal()
    try:
        users = db.query(User).filter(
            (User.totp_secret.isnot(None)) | (User.backup_codes.isnot(None))
        ).all()

        total = len(users)
        updated = 0
        skipped = 0

        for user in users:
            changed = False

            if user.totp_secret and _needs_encryption(user.totp_secret):
                if not dry_run:
                    user.totp_secret = _encrypt(str(user.totp_secret))
                changed = True
                print(f"  [{'DRY' if dry_run else 'ENC'}] user_id={user.id} totp_secret")

            if user.backup_codes and _needs_encryption(user.backup_codes):
                if not dry_run:
                    user.backup_codes = _encrypt(str(user.backup_codes))
                changed = True
                print(f"  [{'DRY' if dry_run else 'ENC'}] user_id={user.id} backup_codes")

            if changed:
                updated += 1
            else:
                skipped += 1

        if not dry_run and updated > 0:
            db.commit()

        print(
            f"\nDone. total={total}, re-encrypted={updated}, already-encrypted/empty={skipped}"
            + (" (DRY RUN — no changes written)" if dry_run else "")
        )
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate plaintext TOTP secrets to Fernet encryption")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without writing")
    args = parser.parse_args()
    _migrate(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
