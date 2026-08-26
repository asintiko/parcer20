import pytest
from fastapi import HTTPException

from api.routes.telegram_client import (
    CloseWebAppRequest,
    OpenWebAppRequest,
    SendWebAppDataRequest,
    close_web_app,
    open_web_app,
    send_web_app_data,
)


class FakeTDLibManager:
    def __init__(self, bot_user_id: int = 7001):
        self.bot_user_id = bot_user_id
        self.open_calls = []
        self.data_calls = []
        self.close_calls = []

    async def resolve_bot_user_id(self, chat_id: int):  # noqa: ARG002
        return self.bot_user_id

    async def open_web_app(self, **kwargs):
        self.open_calls.append(kwargs)
        return {"url": "https://mini.example/app", "launch_id": 991}

    async def send_web_app_data(self, **kwargs):
        self.data_calls.append(kwargs)

    async def close_web_app(self, launch_id: int):
        self.close_calls.append(launch_id)


def _user(user_id: int):
    return {"user_id": user_id, "role": "admin"}


@pytest.mark.asyncio
async def test_open_web_app_rejects_bot_identity_mismatch():
    manager = FakeTDLibManager(bot_user_id=7001)

    with pytest.raises(HTTPException) as exc_info:
        await open_web_app(
            chat_id=501,
            payload=OpenWebAppRequest(
                url="https://attacker.example/app",
                bot_user_id=9999,
                button_kind="inline",
            ),
            manager=manager,
            current_user=_user(1),
            _chat_access=None,
        )

    assert exc_info.value.status_code == 403
    assert manager.open_calls == []


@pytest.mark.asyncio
async def test_send_web_app_data_rejects_bot_identity_mismatch():
    manager = FakeTDLibManager(bot_user_id=7001)

    with pytest.raises(HTTPException) as exc_info:
        await send_web_app_data(
            chat_id=501,
            payload=SendWebAppDataRequest(
                bot_user_id=9999,
                button_text="Send",
                data="sensitive-data",
            ),
            manager=manager,
            current_user=_user(1),
            _chat_access=None,
        )

    assert exc_info.value.status_code == 403
    assert manager.data_calls == []

    result = await send_web_app_data(
        chat_id=501,
        payload=SendWebAppDataRequest(
            bot_user_id=7001,
            button_text="Send",
            data="legitimate-data",
        ),
        manager=manager,
        current_user=_user(1),
        _chat_access=None,
    )
    assert result == {"ok": True}
    assert manager.data_calls == [
        {
            "bot_user_id": 7001,
            "button_text": "Send",
            "data": "legitimate-data",
        }
    ]


@pytest.mark.asyncio
async def test_launch_can_only_be_closed_by_its_app_user_and_chat():
    manager = FakeTDLibManager()
    opened = await open_web_app(
        chat_id=501,
        payload=OpenWebAppRequest(
            url="https://mini.example/app",
            bot_user_id=7001,
            button_kind="inline",
        ),
        manager=manager,
        current_user=_user(1),
        _chat_access=None,
    )
    assert opened.launch_id == "991"

    with pytest.raises(HTTPException) as exc_info:
        await close_web_app(
            chat_id=501,
            payload=CloseWebAppRequest(launch_id=opened.launch_id),
            manager=manager,
            current_user=_user(2),
            _chat_access=None,
        )
    assert exc_info.value.status_code == 403
    assert manager.close_calls == []

    with pytest.raises(HTTPException) as exc_info:
        await close_web_app(
            chat_id=502,
            payload=CloseWebAppRequest(launch_id=opened.launch_id),
            manager=manager,
            current_user=_user(1),
            _chat_access=None,
        )
    assert exc_info.value.status_code == 403
    assert manager.close_calls == []

    result = await close_web_app(
        chat_id=501,
        payload=CloseWebAppRequest(launch_id=opened.launch_id),
        manager=manager,
        current_user=_user(1),
        _chat_access=None,
    )
    assert result == {"ok": True}
    assert manager.close_calls == [991]
