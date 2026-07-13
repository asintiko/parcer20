from datetime import datetime, timezone

import pytest

from database.models import HiddenBotChat
from services.telegram_tdlib_manager import TelegramTDLibManager


@pytest.mark.asyncio
async def test_hidden_chats_filtered_by_default(db_session, monkeypatch):
    manager = TelegramTDLibManager()

    async def fake_fetch_bot_chats(search, limit, allowed_types):  # noqa: ARG001
        return [
            {
                "chat_id": 1001,
                "title": "Visible chat",
                "chat_type": "bot",
            },
            {
                "chat_id": 2002,
                "title": "Hidden chat",
                "chat_type": "group",
            },
        ]

    monkeypatch.setattr(manager, "_fetch_bot_chats", fake_fetch_bot_chats)
    db_session.add(
        HiddenBotChat(
            chat_id=2002,
            title_snapshot="Hidden chat",
            hidden_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    visible_only = await manager.list_chats(db=db_session, include_hidden=False, limit=50, offset=0)
    visible_ids = [item["chat_id"] for item in visible_only["items"]]
    assert visible_ids == [1001]

    include_hidden = await manager.list_chats(db=db_session, include_hidden=True, limit=50, offset=0)
    hidden_lookup = {item["chat_id"]: item["is_hidden"] for item in include_hidden["items"]}
    assert set(hidden_lookup.keys()) == {1001, 2002}
    assert hidden_lookup[1001] is False
    assert hidden_lookup[2002] is True


@pytest.mark.asyncio
async def test_all_hidden_chats_return_empty_visible_list(db_session, monkeypatch):
    manager = TelegramTDLibManager()

    async def fake_fetch_bot_chats(search, limit, allowed_types):  # noqa: ARG001
        return [
            {"chat_id": 11, "title": "A", "chat_type": "bot"},
            {"chat_id": 22, "title": "B", "chat_type": "group"},
        ]

    monkeypatch.setattr(manager, "_fetch_bot_chats", fake_fetch_bot_chats)
    db_session.add_all(
        [
            HiddenBotChat(chat_id=11, title_snapshot="A", hidden_at=datetime.now(timezone.utc)),
            HiddenBotChat(chat_id=22, title_snapshot="B", hidden_at=datetime.now(timezone.utc)),
        ]
    )
    db_session.commit()

    visible_only = await manager.list_chats(db=db_session, include_hidden=False, limit=50, offset=0)
    assert visible_only["total"] == 0
    assert visible_only["items"] == []


@pytest.mark.asyncio
async def test_hidden_filter_applies_before_pagination(db_session, monkeypatch):
    manager = TelegramTDLibManager()

    async def fake_fetch_bot_chats(search, limit, allowed_types):  # noqa: ARG001
        return [
            {"chat_id": 101, "title": "Hidden first", "chat_type": "bot"},
            {"chat_id": 202, "title": "Visible second", "chat_type": "bot"},
            {"chat_id": 303, "title": "Visible third", "chat_type": "group"},
        ]

    monkeypatch.setattr(manager, "_fetch_bot_chats", fake_fetch_bot_chats)
    db_session.add(
        HiddenBotChat(
            chat_id=101,
            title_snapshot="Hidden first",
            hidden_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    page_1 = await manager.list_chats(db=db_session, include_hidden=False, limit=1, offset=0)
    assert page_1["total"] == 2
    assert [item["chat_id"] for item in page_1["items"]] == [202]

    page_2 = await manager.list_chats(db=db_session, include_hidden=False, limit=1, offset=1)
    assert page_2["total"] == 2
    assert [item["chat_id"] for item in page_2["items"]] == [303]


@pytest.mark.asyncio
async def test_search_result_does_not_leak_hidden_chat(db_session, monkeypatch):
    manager = TelegramTDLibManager()

    async def fake_fetch_bot_chats(search, limit, allowed_types):  # noqa: ARG001
        if search == "secret":
            return [{"chat_id": 909, "title": "Secret", "chat_type": "bot"}]
        return []

    monkeypatch.setattr(manager, "_fetch_bot_chats", fake_fetch_bot_chats)
    db_session.add(
        HiddenBotChat(
            chat_id=909,
            title_snapshot="Secret",
            hidden_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    visible_only = await manager.list_chats(
        db=db_session,
        include_hidden=False,
        search="secret",
        limit=50,
        offset=0,
    )
    assert visible_only["total"] == 0
    assert visible_only["items"] == []
