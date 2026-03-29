import json
from datetime import datetime

import pytest

pytest.importorskip("fastapi")

from api.routes.reconciliation import _queue_message_for_parsing
from database.models import TgChatMessage


def test_queue_message_for_parsing_uses_force_false_and_returns_false_on_race(db_session, monkeypatch):
    msg = TgChatMessage(
        chat_id=111,
        message_id=222,
        message_date=datetime.utcnow(),
        is_outgoing=False,
        text="fallback text",
        raw_json=json.dumps(
            {
                "id": 222,
                "date": 1700000000,
                "content": {
                    "@type": "messageText",
                    "text": {"@type": "formattedText", "text": "💸 500000 UZS"},
                },
            }
        ),
    )
    db_session.add(msg)
    db_session.commit()

    seen = {}

    def fake_queue(task_data, force=False):
        seen["force"] = force
        raise ValueError("already processed")

    monkeypatch.setattr("api.routes.reconciliation.queue_receipt_task", fake_queue)

    queued = _queue_message_for_parsing(db_session, chat_id=111, message_id=222)
    assert queued is False
    assert seen["force"] is False


def test_queue_message_for_parsing_extracts_nested_tdlib_text(db_session, monkeypatch):
    msg = TgChatMessage(
        chat_id=333,
        message_id=444,
        message_date=datetime.utcnow(),
        is_outgoing=False,
        text=None,
        raw_json=json.dumps(
            {
                "id": 444,
                "date": 1700000000,
                "content": {
                    "@type": "messageText",
                    "text": {"@type": "formattedText", "text": "Pokupka: TEST, 10000.00 UZS"},
                },
            }
        ),
    )
    db_session.add(msg)
    db_session.commit()

    seen = {}

    def fake_queue(task_data, force=False):
        seen["task_data"] = task_data
        seen["force"] = force
        return "task-id"

    monkeypatch.setattr("api.routes.reconciliation.queue_receipt_task", fake_queue)

    queued = _queue_message_for_parsing(db_session, chat_id=333, message_id=444)
    assert queued is True
    assert seen["force"] is False
    assert seen["task_data"]["raw_text"] == "Pokupka: TEST, 10000.00 UZS"
