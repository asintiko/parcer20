import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.routes import telegram_client, two_factor


def test_file_id_must_belong_to_requested_message():
    message = {
        "id": 99,
        "content": {
            "document": {"document": {"@type": "file", "id": 123, "local": {}}}
        },
    }
    assert telegram_client._message_contains_file_id(message, 123) is True
    assert telegram_client._message_contains_file_id(message, 99) is False
    assert telegram_client._message_contains_file_id(message, 456) is False


def test_ws_event_source_filter_and_protected_chat_denial(monkeypatch):
    monkeypatch.setattr(telegram_client, "_chat_is_password_protected", lambda _chat_id: False)
    event = {"type": "message", "payload": {"chat_id": 10, "text": "secret"}}
    assert telegram_client._filter_ws_event_for_access(event, {"allowed_sources": {10}}) == event
    assert telegram_client._filter_ws_event_for_access(event, {"allowed_sources": {20}}) is None

    monkeypatch.setattr(telegram_client, "_chat_is_password_protected", lambda _chat_id: True)
    assert telegram_client._filter_ws_event_for_access(event, {"allowed_sources": None}) is None


def test_two_factor_sensitive_actions_require_valid_step_up(monkeypatch):
    user = SimpleNamespace(id=7, totp_enabled=True, totp_secret="encrypted")
    request = SimpleNamespace(client=None)

    async def unlocked(_user_id):
        return None

    async def clear(_user_id):
        return None

    monkeypatch.setattr(two_factor, "_check_2fa_lock", unlocked)
    monkeypatch.setattr(two_factor, "_clear_2fa_failures", clear)
    monkeypatch.setattr(two_factor, "verify_2fa_code", lambda _db, _user, _code: (True, "totp"))
    assert asyncio.run(
        two_factor._require_fresh_2fa_step_up(None, request, user, "123456", action="disable")
    ) == "totp"

    async def failed(_user_id):
        return {"attempts_left": 2, "locked_seconds": 0}

    monkeypatch.setattr(two_factor, "verify_2fa_code", lambda _db, _user, _code: (False, "invalid"))
    monkeypatch.setattr(two_factor, "_mark_2fa_failed", failed)
    monkeypatch.setattr(two_factor, "_audit", lambda *_args, **_kwargs: None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(two_factor._require_fresh_2fa_step_up(None, request, user, "bad", action="disable"))
    assert exc.value.status_code == 401
