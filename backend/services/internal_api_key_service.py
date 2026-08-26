"""Helpers for INTERNAL_API_KEY validation with rotation support."""
from __future__ import annotations

import ipaddress
import os
import secrets
from typing import Any, List

# Loopback + RFC1918 private ranges. The internal API key is only ever used for
# service-to-service calls inside the docker network (celery -> backend, auth
# bot -> backend, both targeting http://backend:8000 directly). Public clients
# can only reach the backend through Caddy, never from these source addresses.
_DEFAULT_INTERNAL_CIDRS = "127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fd00::/8"

# Headers a reverse proxy attaches. Caddy sets X-Forwarded-* on every proxied
# /api/* request; legit in-cluster callers connect straight to the backend and
# never set them. Their presence means the request crossed the public edge.
_PROXY_HEADERS = ("x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded")


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


def _allowed_internal_networks() -> List[Any]:
    raw = os.getenv("INTERNAL_API_ALLOWED_CIDRS", "") or _DEFAULT_INTERNAL_CIDRS
    networks: List[Any] = []
    for token in raw.split(","):
        item = token.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return networks


def _ip_in_allowlist(host: str | None) -> bool:
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(str(host).strip())
    except ValueError:
        return False
    return any(addr in net for net in _allowed_internal_networks())


def is_internal_request(conn: Any) -> bool:
    """
    True only for trusted in-cluster service-to-service calls.

    Three conditions must all hold:
    1. a valid internal API key is presented;
    2. the request carries no reverse-proxy headers — Caddy adds X-Forwarded-*
       to every proxied /api/* request, so their presence proves the call came
       through the public edge (where client.host would be Caddy's own private
       docker IP, defeating a plain allowlist);
    3. the peer address is in the private/loopback allowlist.

    A leaked INTERNAL_API_KEY used from the internet is rejected: it can only
    arrive via Caddy, which trips condition 2.
    """
    headers = getattr(conn, "headers", None)
    if headers is None:
        return False
    if not is_valid_internal_api_key(headers.get("x-internal-api-key")):
        return False
    for name in _PROXY_HEADERS:
        if headers.get(name):
            return False
    client = getattr(conn, "client", None)
    host = getattr(client, "host", None) if client is not None else None
    return _ip_in_allowlist(host)
