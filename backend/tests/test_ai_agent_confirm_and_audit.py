from __future__ import annotations

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")

from database.models import (
    AgentNotification,
    DuplicateSuggestion,
    MonitoredBotChat,
    ReceiptProcessingTask,
    TgChatMessage,
    TgHistoryCursor,
    Transaction,
)
from services.ai_agent.confirm_service import execute_confirmation_for_run
from services.ai_agent.report_service import generate_report
from services.ai_agent.session_service import create_run, create_thread, update_run
from services.ai_agent.tools.cache_tools import monitored_chat_sync_audit
from services.telegram_cache_service import TelegramCacheService


def _seed_transaction(db_session, *, idx: int, amount: str = "-100.00", operator: str | None = None) -> Transaction:
    row = Transaction(
        raw_message=f"tx-{idx}",
        source_type="AUTO",
        source_chat_id=700 + idx,
        source_message_id=idx,
        transaction_date=datetime(2026, 2, 10 + idx, 10, 0, 0),
        amount=Decimal(amount),
        currency="UZS",
        card_last_4="1111",
        operator_raw=operator or f"Operator {idx}",
        application_mapped="App",
        transaction_type="DEBIT",
        parsing_method="REGEX_SMS",
        parsing_confidence=0.8,
        fingerprint=f"confirm-fp-{idx}",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_duplicate_merge_confirm_applies_and_is_idempotent(db_session):
    primary = _seed_transaction(db_session, idx=1, amount="-100.00", operator="Primary")
    duplicate = _seed_transaction(db_session, idx=2, amount="-100.00", operator="Duplicate")

    suggestion = DuplicateSuggestion(
        id=uuid4(),
        primary_transaction_id=int(primary.id),
        duplicate_transaction_id=int(duplicate.id),
        confidence=0.98,
        status="pending",
        reasoning="Same receipt fingerprint",
    )
    linked_task = ReceiptProcessingTask(
        task_id="dup-task-1",
        chat_id=int(duplicate.source_chat_id),
        message_id=int(duplicate.source_message_id),
        status="failed",
        transaction_id=int(duplicate.id),
    )
    linked_message = TgChatMessage(
        chat_id=int(duplicate.source_chat_id),
        message_id=int(duplicate.source_message_id),
        message_date=duplicate.transaction_date,
        is_outgoing=False,
        sender_id=1,
        text="duplicate row",
        raw_json="{}",
        receipt_transaction_id=int(duplicate.id),
    )
    db_session.add_all([suggestion, linked_task, linked_message])
    db_session.commit()

    thread = create_thread(db_session, user_id=1, title="Confirm merge")
    run = create_run(
        db_session,
        thread_id=thread.id,
        user_id=1,
        tool_name="duplicate_merge_preview",
        status="awaiting_confirmation",
        requires_confirmation=True,
    )
    payload = {
        "confirmation_payload": {
            "action": "merge_duplicates",
            "args": {"suggestion_ids": [str(suggestion.id)]},
            "idempotency_key": f"merge_duplicates:{suggestion.id}",
        }
    }
    update_run(db_session, run_id=run.id, result=payload, requires_confirmation=True)
    db_session.refresh(run)

    result = execute_confirmation_for_run(db_session, run=run, current_user={"id": 1, "role": "admin"})

    assert result["confirmation_result"]["action"] == "merge_duplicates"
    assert result["confirmation_result"]["applied"] == 1
    assert db_session.get(Transaction, duplicate.id) is None
    assert db_session.get(Transaction, primary.id) is not None
    db_session.refresh(linked_task)
    db_session.refresh(linked_message)
    assert linked_task.transaction_id == int(primary.id)
    assert linked_message.receipt_transaction_id == int(primary.id)
    db_session.refresh(suggestion)
    assert suggestion.status == "approved"

    update_run(
        db_session,
        run_id=run.id,
        result={**payload, "confirmation_result": result["confirmation_result"]},
        requires_confirmation=False,
    )
    run = db_session.get(type(run), run.id)
    second = execute_confirmation_for_run(db_session, run=run, current_user={"id": 1, "role": "admin"})
    assert second["confirmation_result"]["action"] == "merge_duplicates"
    assert second["confirmation_result"]["applied"] == 1


def test_receipt_reparse_confirm_enqueues_once_and_is_idempotent(db_session, monkeypatch):
    captured: list[tuple[dict, bool]] = []

    def _fake_queue(task_data: dict, force: bool = False) -> str:
        captured.append((task_data, force))
        return "queued-task-1"

    monkeypatch.setattr("services.ai_agent.confirm_service.queue_receipt_task", _fake_queue)

    row = TgChatMessage(
        chat_id=-100500,
        message_id=4455,
        message_date=datetime(2026, 3, 12, 14, 0, 0),
        is_outgoing=False,
        sender_id=1,
        text="receipt caption",
        raw_json=json.dumps(
            {
                "content": {
                    "@type": "messageDocument",
                    "document": {
                        "document": {"id": 998877},
                        "mime_type": "application/pdf",
                        "file_name": "receipt.pdf",
                    },
                    "caption": {"text": "receipt caption"},
                }
            },
            ensure_ascii=False,
        ),
        content_type="messageDocument",
        looks_like_receipt=True,
    )
    db_session.add(row)
    db_session.commit()

    thread = create_thread(db_session, user_id=1, title="Confirm reparse")
    run = create_run(
        db_session,
        thread_id=thread.id,
        user_id=1,
        tool_name="receipt_reparse_preview",
        status="awaiting_confirmation",
        requires_confirmation=True,
    )
    payload = {
        "confirmation_payload": {
            "action": "reparse_receipt",
            "args": {"chat_id": -100500, "message_id": 4455},
            "idempotency_key": "reparse_receipt:-100500:4455",
        }
    }
    update_run(db_session, run_id=run.id, result=payload, requires_confirmation=True)
    db_session.refresh(run)

    result = execute_confirmation_for_run(db_session, run=run, current_user={"id": 1, "role": "admin"})

    assert result["confirmation_result"]["action"] == "reparse_receipt"
    assert result["confirmation_result"]["task_id"] == "queued-task-1"
    assert len(captured) == 1
    task_data, force = captured[0]
    assert force is True
    assert task_data["source_chat_id"] == -100500
    assert task_data["source_message_id"] == 4455
    assert task_data["document"]["file_id"] == 998877

    update_run(
        db_session,
        run_id=run.id,
        result={**payload, "confirmation_result": result["confirmation_result"]},
        requires_confirmation=False,
    )
    run = db_session.get(type(run), run.id)
    second = execute_confirmation_for_run(db_session, run=run, current_user={"id": 1, "role": "admin"})
    assert second["confirmation_result"]["task_id"] == "queued-task-1"
    assert len(captured) == 1


def test_report_publish_confirm_publishes_team_notification_and_is_idempotent(db_session):
    preview = generate_report(
        db_session,
        created_by_user_id=1,
        scope="team",
        publish_team_notification=False,
        publish_immediately=False,
    )
    assert preview["status"] == "ready"
    assert db_session.query(AgentNotification).count() == 0

    thread = create_thread(db_session, user_id=1, title="Publish report")
    run = create_run(
        db_session,
        thread_id=thread.id,
        user_id=1,
        tool_name="report_publish_tool",
        status="awaiting_confirmation",
        requires_confirmation=True,
    )
    payload = {
        "confirmation_payload": {
            "action": "publish_report",
            "args": {"report_id": preview["id"]},
            "idempotency_key": f"publish_report:{preview['id']}",
        }
    }
    update_run(db_session, run_id=run.id, result=payload, requires_confirmation=True)
    db_session.refresh(run)

    result = execute_confirmation_for_run(db_session, run=run, current_user={"id": 1, "role": "admin"})

    assert result["confirmation_result"]["action"] == "publish_report"
    assert result["confirmation_result"]["published"] is True
    notifications = db_session.query(AgentNotification).all()
    assert len(notifications) == 1
    assert notifications[0].scope == "team"

    update_run(
        db_session,
        run_id=run.id,
        result={**payload, "confirmation_result": result["confirmation_result"]},
        requires_confirmation=False,
    )
    run = db_session.get(type(run), run.id)
    second = execute_confirmation_for_run(db_session, run=run, current_user={"id": 1, "role": "admin"})
    assert second["confirmation_result"]["published"] is True
    assert db_session.query(AgentNotification).count() == 1


def test_monitored_chat_sync_audit_without_period_returns_background_job(db_session):
    db_session.add(MonitoredBotChat(chat_id=-100700, enabled=True, chat_type="supergroup", chat_title="Audit Chat"))
    db_session.add(TgHistoryCursor(chat_id=-100700, status="completed", cursor_message_id=1, loaded_count=1))
    db_session.add(
        TgChatMessage(
            chat_id=-100700,
            message_id=1,
            message_date=datetime(2026, 2, 10, 10, 0, 0),
            is_outgoing=False,
            sender_id=1,
            text="CardXabar summa: 150000 UZS karta: *6714",
            raw_json="{}",
            looks_like_receipt=True,
        )
    )
    db_session.commit()

    result = asyncio.run(monitored_chat_sync_audit(db_session, {"id": 1, "role": "admin"}, None, {}))

    assert result["cards"][0]["type"] == "progress"
    assert result["background_job"]["job_type"] == "monitored_chat_sync_audit"
    assert result["background_job"]["payload"]["estimated_candidates"] == 1


def test_chunked_audit_emits_progress_and_finds_missing_issue(db_session):
    db_session.add(MonitoredBotChat(chat_id=-100900, enabled=True, chat_type="supergroup", chat_title="Chunk Chat"))
    db_session.add(TgHistoryCursor(chat_id=-100900, status="completed", cursor_message_id=3, loaded_count=3))
    db_session.add_all(
        [
            TgChatMessage(
                chat_id=-100900,
                message_id=3,
                message_date=datetime(2026, 2, 12, 10, 0, 0),
                is_outgoing=False,
                sender_id=1,
                text="receipt 3",
                raw_json="{}",
                looks_like_receipt=True,
            ),
            TgChatMessage(
                chat_id=-100900,
                message_id=2,
                message_date=datetime(2026, 2, 11, 10, 0, 0),
                is_outgoing=False,
                sender_id=1,
                text="receipt 2",
                raw_json="{}",
                looks_like_receipt=True,
            ),
        ]
    )
    db_session.commit()

    progress_events: list[dict] = []
    summary = TelegramCacheService(db_session).audit_monitored_chats_chunked(
        chat_ids=[-100900],
        date_from=datetime(2026, 2, 1, 0, 0, 0),
        date_to=datetime(2026, 2, 28, 23, 59, 59),
        chunk_size=1,
        progress_callback=lambda payload: progress_events.append(payload),
    )

    assert summary["categories"]["MISSING_IN_DB"] >= 2
    assert progress_events
    assert any(event.get("phase") == "scan_chunk" for event in progress_events)
    assert any(event.get("cursor") for event in progress_events)
