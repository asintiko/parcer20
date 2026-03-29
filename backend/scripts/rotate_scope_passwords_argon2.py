"""Rotate root-access config secrets from PBKDF2 to Argon2id.

Examples:
  python -m scripts.rotate_scope_passwords_argon2 \
    --scope "Папка 2025=myPassword" \
    --scope "Папка 2026=myPassword2" \
    --token "desktop-main=change_me_system_token"
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Tuple

from services.root_access_config_service import (
    get_server_config_path,
    hash_password_argon2,
    verify_secret,
)


def _parse_pairs(values: list[str]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for item in values:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            result[key] = value
    return result


def _normalize_secret_record(secret: Dict[str, str]) -> Dict[str, str]:
    return {
        "kind": str(secret.get("kind") or ""),
        "hash": str(secret.get("hash") or ""),
        "salt": str(secret.get("salt") or ""),
    }


def rotate(path: Path, scope_passwords: Dict[str, str], token_values: Dict[str, str]) -> Tuple[int, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Config JSON root must be object")

    rotated_scopes = 0
    rotated_tokens = 0

    scopes = payload.get("scopes")
    if isinstance(scopes, list):
        for scope in scopes:
            if not isinstance(scope, dict):
                continue
            name = str(scope.get("name") or "").strip()
            if not name:
                continue
            if name not in scope_passwords:
                continue

            secret = scope.get("password") if isinstance(scope.get("password"), dict) else {
                "kind": scope.get("password_kind") or "pbkdf2_sha256",
                "hash": scope.get("password_hash"),
                "salt": scope.get("salt"),
            }
            normalized = _normalize_secret_record(secret)
            plain_password = scope_passwords[name]
            if not verify_secret(plain_password, normalized):
                raise ValueError(f"Password mismatch for scope: {name}")

            scope["password"] = {
                "kind": "argon2id",
                "hash": hash_password_argon2(plain_password),
                "active": True,
                "rotated": True,
            }
            scope.pop("password_hash", None)
            scope.pop("password_kind", None)
            scope.pop("salt", None)
            rotated_scopes += 1

    system_access = payload.get("system_access")
    tokens = system_access.get("tokens") if isinstance(system_access, dict) else None
    if isinstance(tokens, list):
        for token in tokens:
            if not isinstance(token, dict):
                continue
            token_id = str(token.get("id") or "").strip()
            if token_id not in token_values:
                continue

            normalized = _normalize_secret_record(token)
            plain_value = token_values[token_id]
            if not verify_secret(plain_value, normalized):
                raise ValueError(f"Token mismatch for id: {token_id}")

            token["kind"] = "argon2id"
            token["hash"] = hash_password_argon2(plain_value)
            token["active"] = bool(token.get("active", True))
            token["rotated"] = True
            token.pop("salt", None)
            rotated_tokens += 1

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rotated_scopes, rotated_tokens


def main() -> None:
    parser = argparse.ArgumentParser(description="Rotate root-access secrets from PBKDF2 to Argon2id")
    parser.add_argument("--config", default=get_server_config_path(), help="Path to root-access server config")
    parser.add_argument("--scope", action="append", default=[], help="Scope password mapping: <scope_name>=<plain_password>")
    parser.add_argument("--token", action="append", default=[], help="System token mapping: <token_id>=<plain_token>")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    scope_passwords = _parse_pairs(args.scope)
    token_values = _parse_pairs(args.token)
    if not scope_passwords and not token_values:
        raise ValueError("Nothing to rotate: provide --scope and/or --token mappings")

    scope_count, token_count = rotate(config_path, scope_passwords, token_values)
    print(f"Rotated scopes: {scope_count}, rotated system tokens: {token_count}")
    print(f"Updated: {config_path}")


if __name__ == "__main__":
    main()
