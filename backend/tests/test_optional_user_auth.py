import asyncio

import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException
from starlette.requests import HTTPConnection

from api import dependencies
from database.models import User


def _connection() -> HTTPConnection:
    return HTTPConnection(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/test",
            "headers": [(b"authorization", b"Bearer test-token")],
        }
    )


def _resolve(db_session, monkeypatch, payload):
    monkeypatch.setattr(dependencies, "verify_jwt_token", lambda _token: payload)

    async def _is_active_session(_sid, *, expected_kind=None):
        return True

    async def _touch_active_session(_sid):
        return None

    monkeypatch.setattr(dependencies, "is_active_session", _is_active_session)
    monkeypatch.setattr(dependencies, "touch_active_session", _touch_active_session)
    return asyncio.run(
        dependencies.get_current_user_optional(conn=_connection(), db=db_session)
    )


def _seed_user(db_session, **overrides) -> User:
    values = {
        "username": "operator",
        "password_hash": "hash",
        "salt": "salt",
        "role": "operator",
        "display_name": "Operator",
        "is_active": True,
        "allowed_tabs": '["dashboard"]',
        "allowed_folders": "[]",
        "forbidden_periods": "[]",
        "allowed_sources": "[]",
        "permissions_version": 1,
    }
    values.update(overrides)
    user = User(**values)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _app_user_payload(user_id: int, **overrides):
    payload = {
        "kind": "app_user",
        "sid": f"test-session-{user_id}",
        "sub": str(user_id),
        "user_id": user_id,
        "username": "claimed-admin",
        "role": "admin",
        "permissions_version": 1,
    }
    payload.update(overrides)
    return payload


def test_deleted_app_user_admin_claim_is_rejected(db_session, monkeypatch):
    result = _resolve(db_session, monkeypatch, _app_user_payload(999))

    assert result is None


def test_app_user_admin_claim_without_subject_is_rejected(db_session, monkeypatch):
    with pytest.raises(HTTPException) as exc:
        _resolve(
            db_session,
            monkeypatch,
            {"kind": "app_user", "role": "admin", "permissions_version": 1},
        )

    assert exc.value.status_code == 401
    assert exc.value.detail == "missing_session_id"


def test_deleted_app_user_admin_claim_cannot_unlock_full_scope(db_session, monkeypatch):
    current_user = _resolve(db_session, monkeypatch, _app_user_payload(999))
    monkeypatch.setattr(dependencies, "is_internal_request", lambda _conn: False)
    monkeypatch.setattr(dependencies, "is_otp_enabled", lambda _db: False)
    monkeypatch.setattr(dependencies, "has_active_scopes", lambda _db: False)

    result = asyncio.run(
        dependencies.get_scope_context_optional(
            conn=_connection(),
            db=db_session,
            current_user=current_user,
            x_access_token=None,
        )
    )

    assert result is None


def test_inactive_app_user_is_rejected(db_session, monkeypatch):
    user = _seed_user(db_session, is_active=False)

    result = _resolve(db_session, monkeypatch, _app_user_payload(user.id))

    assert result is None


def test_outdated_app_user_permissions_are_rejected(db_session, monkeypatch):
    user = _seed_user(db_session, permissions_version=2)

    result = _resolve(db_session, monkeypatch, _app_user_payload(user.id))

    assert result is None


def test_active_app_user_uses_current_database_permissions(db_session, monkeypatch):
    user = _seed_user(db_session)

    result = _resolve(db_session, monkeypatch, _app_user_payload(user.id))

    assert result is not None
    assert result["user_id"] == user.id
    assert result["role"] == "operator"
    assert result["allowed_tabs"] == ["dashboard"]
    assert result["token_kind"] == "app_user"


def test_legacy_qr_user_without_database_row_is_rejected(db_session, monkeypatch):
    result = _resolve(
        db_session,
        monkeypatch,
        {"kind": "qr_user", "user_id": 998, "phone": "+998901234567"},
    )

    assert result is None
