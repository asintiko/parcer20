from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")

from database.models import AgentReport, AgentReportItem, Transaction
from services.ai_agent.navigation_service import locate_transaction
from services.ai_agent.report_service import build_previous_week_window, claim_report_item, release_report_item
from services.ai_agent.session_service import create_message, create_run, create_thread, list_messages, list_threads


def _add_tx(db_session, idx: int, dt: datetime) -> Transaction:
    tx = Transaction(
        raw_message=f"agent-tx-{idx}",
        source_type="AUTO",
        source_chat_id=777,
        source_message_id=idx,
        transaction_date=dt,
        amount=Decimal("-100.00"),
        currency="UZS",
        card_last_4="1111",
        operator_raw=f"Operator {idx}",
        application_mapped="App",
        transaction_type="DEBIT",
        parsing_method="REGEX_SMS",
        fingerprint=f"agent-fp-{idx}",
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    return tx


def test_session_service_roundtrip(db_session):
    thread = create_thread(db_session, user_id=7, title="Проверка")
    assert thread.title == "Проверка"

    message = create_message(
        db_session,
        thread_id=thread.id,
        role="user",
        message_type="text",
        content={"message": "test"},
    )
    run = create_run(
        db_session,
        thread_id=thread.id,
        user_id=7,
        tool_name="db_inspector",
        status="queued",
        progress={"percent": 0},
    )

    threads = list_threads(db_session, user_id=7)
    messages = list_messages(db_session, thread_id=thread.id)

    assert len(threads) == 1
    assert threads[0]["title"] == "Проверка"
    assert len(messages) == 1
    assert messages[0]["id"] == str(message.id)
    assert run.tool_name == "db_inspector"


def test_build_previous_week_window_uses_completed_calendar_week():
    start_dt, end_dt = build_previous_week_window(datetime(2026, 3, 27, 15, 0, 0))

    assert start_dt == datetime(2026, 3, 16, 0, 0, 0)
    assert end_dt == datetime(2026, 3, 22, 23, 59, 59, 999999)


def test_claim_and_release_report_item_create_expected_state(db_session):
    report = AgentReport(
        id=uuid4(),
        created_by_user_id=1,
        scope="team",
        title="Командный отчет",
        status="published",
        summary_json="{}",
        payload_json="{}",
    )
    db_session.add(report)
    db_session.commit()

    item = AgentReportItem(
        id=uuid4(),
        report_id=report.id,
        issue_type="failed_parse",
        severity="high",
        entity_type="receipt_processing_task",
        entity_id="55",
        title="Ошибка",
        description="test",
        suggested_action_json="{}",
        status="open",
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    claimed = claim_report_item(db_session, item_id=item.id, user_id=11)
    assert claimed is not None
    assert claimed["status"] == "claimed"
    assert claimed["assignee_user_id"] == 11

    with pytest.raises(ValueError, match="claim_conflict"):
        claim_report_item(db_session, item_id=item.id, user_id=12)

    released = release_report_item(db_session, item_id=item.id, user_id=11)
    assert released is not None
    assert released["status"] == "released"
    assert released["assignee_user_id"] is None


def test_locate_transaction_returns_page_hint_and_target(monkeypatch, db_session):
    import api.routes.transactions as transaction_routes

    first = _add_tx(db_session, 1, datetime(2026, 3, 20, 10, 0, 0))
    second = _add_tx(db_session, 2, datetime(2026, 3, 21, 10, 0, 0))
    target = _add_tx(db_session, 3, datetime(2026, 3, 22, 10, 0, 0))

    monkeypatch.setattr(
        transaction_routes,
        "_build_filtered_transactions_query",
        lambda *args, **kwargs: (db_session.query(Transaction), None),
    )
    monkeypatch.setattr(
        transaction_routes,
        "_resolve_transactions_sort_column",
        lambda sort_by: Transaction.transaction_date,
    )

    result = locate_transaction(
        db=db_session,
        current_user={"id": 1, "role": "admin"},
        scope=None,
        transaction_id=int(target.id),
        sort_by="transaction_date",
        sort_dir="desc",
        page_size=2,
    )

    assert result["exists"] is True
    assert result["row_id"] == int(target.id)
    assert result["page_hint"] == 1
    assert result["column_id"] == "amount"

    second_result = locate_transaction(
        db=db_session,
        current_user={"id": 1, "role": "admin"},
        scope=None,
        transaction_id=int(first.id),
        sort_by="transaction_date",
        sort_dir="desc",
        page_size=2,
    )
    assert second_result["page_hint"] == 2
    assert second.id != first.id
