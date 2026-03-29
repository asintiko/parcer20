"""Create initial admin user.

Usage:
    python scripts/create_admin.py <username> <password> [display_name]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database.connection import SessionLocal
from database.models import User
from services.access_control_service import hash_password

ALL_TABS = ["dashboard", "reference", "automation", "userbot", "logs", "admin"]


def create_admin(username: str, password: str, display_name: str = "Админ") -> int:
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            print(f"User '{username}' already exists (id={existing.id})")
            return int(existing.id)

        password_hash, salt = hash_password(password)
        user = User(
            username=username,
            password_hash=password_hash,
            salt=salt,
            hash_method="pbkdf2_sha256",
            role="admin",
            display_name=display_name,
            is_active=True,
            allowed_tabs='["dashboard","reference","automation","userbot","logs","admin"]',
            allowed_folders="[]",
            forbidden_periods="[]",
            allowed_sources="[]",
            can_toggle_sources=True,
            permissions_version=1,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"Admin '{username}' created (id={user.id})")
        return int(user.id)
    finally:
        db.close()


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python scripts/create_admin.py <username> <password> [display_name]")
        raise SystemExit(1)

    username = sys.argv[1].strip()
    password = sys.argv[2]
    display_name = sys.argv[3].strip() if len(sys.argv) > 3 else "Админ"

    if not username:
        print("username is empty")
        raise SystemExit(1)
    if not password:
        print("password is empty")
        raise SystemExit(1)

    create_admin(username=username, password=password, display_name=display_name)


if __name__ == "__main__":
    main()
