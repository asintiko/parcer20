"""Export DB access scopes into root-access server config JSON.

Usage:
  python -m scripts.export_scopes_to_root_config
  python -m scripts.export_scopes_to_root_config --output ../security/root-access.server.json
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from database.connection import SessionLocal
from database.models import AccessScope
from services.root_access_config_service import (
    get_server_config_path,
    hash_password_pbkdf2,
    read_existing_tokens,
)


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    return str(value)


def _years_from_json(value: str | None) -> List[int]:
    if not value:
        return []
    try:
        payload = json.loads(value)
    except Exception:
        return []
    years: List[int] = []
    if isinstance(payload, list):
        for item in payload:
            try:
                year = int(item)
            except Exception:
                continue
            if 1970 <= year <= 2200:
                years.append(year)
    return sorted(set(years))


def _default_tokens() -> List[Dict[str, Any]]:
    # Bootstrap token for immediate use; rotate to Argon2 after setup.
    token_hash, token_salt = hash_password_pbkdf2("change_me_system_token", "sys_salt_2026")
    return [
        {
            "id": "desktop-main",
            "kind": "pbkdf2_sha256",
            "hash": token_hash,
            "salt": token_salt,
            "active": True,
            "rotated": False,
        }
    ]


def export_scopes(output_path: Path) -> None:
    session = SessionLocal()
    try:
        rows = session.query(AccessScope).order_by(AccessScope.id.asc()).all()
        scopes: List[Dict[str, Any]] = []
        for row in rows:
            scopes.append(
                {
                    "id": int(row.id),
                    "name": row.name,
                    "password": {
                        "kind": "pbkdf2_sha256",
                        "hash": row.password_hash,
                        "salt": row.salt,
                        "active": True,
                        "rotated": False,
                    },
                    "years": _years_from_json(row.years_json),
                    "period_start": _to_iso(row.period_start),
                    "period_end": _to_iso(row.period_end),
                    "allow_transactions": bool(row.allow_transactions),
                    "allow_sources": bool(row.allow_sources),
                    "is_active": bool(row.is_active),
                    "created_at": _to_iso(row.created_at),
                    "updated_at": _to_iso(row.updated_at),
                }
            )
    finally:
        session.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    existing_tokens = read_existing_tokens(output_path)
    tokens = existing_tokens if existing_tokens else _default_tokens()

    payload = {
        "version": 1,
        "metadata": {
            "exported_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "exported_by": "scripts.export_scopes_to_root_config",
            "note": "Scopes exported from DB. Rotate passwords/tokens to Argon2 before production.",
        },
        "system_access": {
            "enforced": True,
            "tokens": tokens,
        },
        "scopes": scopes,
    }

    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export DB access scopes to root-access server config")
    parser.add_argument(
        "--output",
        default=get_server_config_path(),
        help="Output JSON path (default from ROOT_ACCESS_SERVER_CONFIG_PATH)",
    )
    args = parser.parse_args()

    output_path = Path(args.output).expanduser().resolve()
    export_scopes(output_path)
    print(f"Exported scopes to: {output_path}")


if __name__ == "__main__":
    main()
