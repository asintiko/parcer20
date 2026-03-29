"""Helpers for INTERNAL_API_KEY validation with rotation support."""
from __future__ import annotations

import os
import secrets
from typing import List


def configured_internal_api_keys() -> List[str]:
    """
    Return normalized list of active internal API keys.

    Rotation strategy:
    - INTERNAL_API_KEY: current primary key
    - INTERNAL_API_KEY_PREVIOUS: previous key accepted during rollout
    - INTERNAL_API_KEYS: optional comma-separated extra keys (for staged rotation)
    """
    values: List[str] = []
    for key in (
        os.getenv("INTERNAL_API_KEY", ""),
        os.getenv("INTERNAL_API_KEY_PREVIOUS", ""),
    ):
        normalized = str(key or "").strip()
        if normalized:
            values.append(normalized)

    extra = str(os.getenv("INTERNAL_API_KEYS", "")).strip()
    if extra:
        for item in extra.split(","):
            normalized = item.strip()
            if normalized:
                values.append(normalized)

    # Preserve order but deduplicate.
    dedup: List[str] = []
    seen = set()
    for item in values:
        if item in seen:
            continue
        dedup.append(item)
        seen.add(item)
    return dedup


def has_configured_internal_api_key() -> bool:
    return len(configured_internal_api_keys()) > 0


def is_valid_internal_api_key(candidate: str | None) -> bool:
    normalized = str(candidate or "").strip()
    if not normalized:
        return False
    for key in configured_internal_api_keys():
        if secrets.compare_digest(normalized, key):
            return True
    return False

