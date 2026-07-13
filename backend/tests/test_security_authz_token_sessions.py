import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers

from api import dependencies


class _Conn:
    def __init__(self, token: str = "token"):
        self.headers = Headers({"authorization": f"Bearer {token}"})


def test_auth_can_only_be_disabled_in_explicit_test_environment(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    monkeypatch.setenv("ALLOW_INSECURE_NO_AUTH", "true")
    monkeypatch.setenv("APP_ENV", "development")
    assert dependencies._resolve_auth_required() is True
    monkeypatch.setenv("APP_ENV", "test")
    assert dependencies._resolve_auth_required() is False


def test_session_registry_positive_revoked_and_unavailable(monkeypatch):
    payload = {"sid": "sid-1"}

    async def registered(_sid, *, expected_kind=None):
        return True

    monkeypatch.setattr(dependencies, "is_active_session", registered)
    assert asyncio.run(dependencies.require_session_active(payload)) == "sid-1"

    async def revoked(_sid, *, expected_kind=None):
        return False

    monkeypatch.setattr(dependencies, "is_active_session", revoked)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependencies.require_session_active(payload))
    assert exc.value.status_code == 401
    assert exc.value.detail == "session_inactive"

    async def unavailable(_sid, *, expected_kind=None):
        raise dependencies.SessionStoreUnavailableError("redis down")

    monkeypatch.setattr(dependencies, "is_active_session", unavailable)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependencies.require_session_active(payload))
    assert exc.value.status_code == 503


def test_refresh_token_is_rejected_before_user_reconstruction(monkeypatch):
    monkeypatch.setattr(
        dependencies,
        "verify_jwt_token",
        lambda _token: {"kind": "refresh_token", "sub": "7", "sid": "refresh-sid"},
    )

    class _Db:
        def get(self, *_args, **_kwargs):
            raise AssertionError("DB lookup must not happen for the wrong token purpose")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependencies.get_current_user(conn=_Conn(), db=_Db()))
    assert exc.value.status_code == 401
    assert exc.value.detail == "invalid_token_purpose"


def test_get_current_app_user_requires_app_or_local_kind():
    app_user = {"role": "operator", "token_kind": "app_user"}
    assert asyncio.run(dependencies.get_current_app_user(app_user)) is app_user
    with pytest.raises(HTTPException) as exc:
        asyncio.run(dependencies.get_current_app_user({"role": "operator", "token_kind": "qr_legacy"}))
    assert exc.value.status_code == 401
