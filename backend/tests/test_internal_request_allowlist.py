"""Unit tests for is_internal_request key+network binding (fix 2.2).

A leaked INTERNAL_API_KEY must not grant a bypass from the public internet. The
only legitimate callers (celery_worker, auth_bot) connect straight to
http://backend:8000 from inside the docker network and never carry reverse-proxy
headers. Anything arriving through Caddy gets X-Forwarded-* stamped on it.
"""
import pytest

pytest.importorskip("starlette")
from starlette.datastructures import Headers

from services.internal_api_key_service import is_internal_request


class _Client:
    def __init__(self, host):
        self.host = host


class _Conn:
    """Minimal stand-in for a Starlette Request / HTTPConnection."""

    def __init__(self, headers, host):
        self.headers = Headers(headers)
        self.client = _Client(host) if host is not None else None


@pytest.fixture(autouse=True)
def _internal_env(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "internal-secret")
    monkeypatch.setenv("INTERNAL_API_KEY_PREVIOUS", "")
    monkeypatch.setenv("INTERNAL_API_KEYS", "")
    monkeypatch.setenv(
        "INTERNAL_API_ALLOWED_CIDRS",
        "127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
    )


def test_accepts_direct_in_cluster_call():
    conn = _Conn({"x-internal-api-key": "internal-secret"}, "172.18.0.5")
    assert is_internal_request(conn) is True


def test_rejects_when_x_forwarded_for_present():
    # Valid key, but the request was routed through Caddy (which appends XFF).
    conn = _Conn(
        {"x-internal-api-key": "internal-secret", "x-forwarded-for": "203.0.113.9"},
        "172.18.0.5",
    )
    assert is_internal_request(conn) is False


def test_rejects_when_x_real_ip_present():
    conn = _Conn(
        {"x-internal-api-key": "internal-secret", "x-real-ip": "203.0.113.9"},
        "172.18.0.5",
    )
    assert is_internal_request(conn) is False


def test_rejects_when_forwarded_header_present():
    conn = _Conn(
        {"x-internal-api-key": "internal-secret", "forwarded": "for=203.0.113.9"},
        "172.18.0.5",
    )
    assert is_internal_request(conn) is False


def test_rejects_ip_outside_allowlist():
    conn = _Conn({"x-internal-api-key": "internal-secret"}, "203.0.113.9")
    assert is_internal_request(conn) is False


def test_rejects_invalid_key():
    conn = _Conn({"x-internal-api-key": "wrong-secret"}, "172.18.0.5")
    assert is_internal_request(conn) is False


def test_rejects_missing_key():
    conn = _Conn({}, "172.18.0.5")
    assert is_internal_request(conn) is False


def test_rejects_missing_client():
    conn = _Conn({"x-internal-api-key": "internal-secret"}, None)
    assert is_internal_request(conn) is False


def test_accepts_previous_key_during_rotation(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY_PREVIOUS", "old-secret")
    conn = _Conn({"x-internal-api-key": "old-secret"}, "10.1.2.3")
    assert is_internal_request(conn) is True


def test_accepts_loopback():
    conn = _Conn({"x-internal-api-key": "internal-secret"}, "127.0.0.1")
    assert is_internal_request(conn) is True
