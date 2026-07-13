from __future__ import annotations

import json
import asyncio
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from database.models import (
    AGENT_RUN_EVENT_TYPES,
    AccessScope,
    AgentRoutine,
    AgentRunEvent,
    Transaction,
    User,
)
from services.ai_agent.authorization import (
    AgentAuthorizationError,
    current_agent_authorization,
    require_same_source_set,
)
from services.ai_agent.confirm_service import _confirm_bulk_update_transactions
from workers.celery_worker import _authorize_deferred_receipt_task


def _scope(db_session, *, scope_id: int = 1) -> AccessScope:
    row = AccessScope(
        id=scope_id,
        name=f"scope-{scope_id}",
        password_hash="hash",
        salt="salt",
        years_json="[2026]",
        allow_transactions=True,
        allow_sources=True,
        is_active=True,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _user(
    db_session,
    *,
    user_id: int,
    role: str = "operator",
    sources: list[int] | None = None,
    folders: list[int] | None = None,
    active: bool = True,
    telegram_id: int | None = None,
) -> User:
    row = User(
        id=user_id,
        username=f"user-{user_id}",
        password_hash="hash",
        salt="salt",
        role=role,
        is_active=active,
        allowed_tabs='["dashboard"]',
        allowed_folders=json.dumps(folders or []),
        forbidden_periods="[]",
        allowed_sources=json.dumps(sources or []),
        telegram_id=telegram_id,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _transaction(db_session, *, source: int, message: int) -> Transaction:
    row = Transaction(
        raw_message=f"tx-{source}-{message}",
        source_type="AUTO",
        source_chat_id=source,
        source_message_id=message,
        transaction_date=datetime(2026, 6, 1, 12, 0),
        amount=Decimal("-100.00"),
        currency="UZS",
        card_last_4="1111",
        operator_raw="Operator",
        application_mapped="App",
        transaction_type="DEBIT",
        parsing_method="REGEX_SMS",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_empty_operator_source_scope_is_deny_all(db_session):
    _scope(db_session)
    _user(db_session, user_id=10, sources=[], folders=[1])
    auth = current_agent_authorization(db_session, 10)

    assert auth.allowed_sources == frozenset()
    with pytest.raises(AgentAuthorizationError, match="source_forbidden"):
        auth.authorize_chat(500)


def test_bulk_confirmation_is_all_or_nothing_on_unauthorized_row(db_session):
    _scope(db_session)
    _user(db_session, user_id=11, sources=[10], folders=[1])
    allowed = _transaction(db_session, source=10, message=1)
    forbidden = _transaction(db_session, source=20, message=2)
    auth = current_agent_authorization(db_session, 11)

    with pytest.raises(AgentAuthorizationError, match="source_forbidden"):
        _confirm_bulk_update_transactions(
            db_session,
            args={
                "transaction_ids": [allowed.id, forbidden.id],
                "patch": {"operator_raw": "Changed"},
            },
            auth=auth,
        )
    db_session.rollback()
    db_session.refresh(allowed)
    db_session.refresh(forbidden)
    assert allowed.operator_raw == "Operator"
    assert forbidden.operator_raw == "Operator"


def test_deferred_reparse_rechecks_current_actor_and_immutable_source(db_session):
    _scope(db_session)
    user = _user(db_session, user_id=12, sources=[10], folders=[1])
    payload = {
        "requested_action": "agent_receipt_reparse",
        "requested_by_user_id": user.id,
        "source_chat_id": 10,
        "source_message_id": 1,
        "original_source_chat_id": 10,
        "original_source_message_id": 1,
    }

    assert _authorize_deferred_receipt_task(db_session, payload).user_id == user.id
    with pytest.raises(ValueError, match="source_changed"):
        _authorize_deferred_receipt_task(
            db_session,
            {**payload, "source_chat_id": 20},
        )

    user.is_active = False
    db_session.commit()
    with pytest.raises(AgentAuthorizationError, match="inactive_or_missing_actor"):
        _authorize_deferred_receipt_task(db_session, payload)


def test_background_scope_cannot_expand_or_survive_revocation(db_session):
    _scope(db_session)
    user = _user(db_session, user_id=13, sources=[10, 20], folders=[1])
    original = require_same_source_set(current_agent_authorization(db_session, user.id), [10])
    assert original == (10,)

    user.allowed_sources = "[20]"
    user.permissions_version = 2
    db_session.commit()
    with pytest.raises(AgentAuthorizationError, match="source_forbidden"):
        require_same_source_set(current_agent_authorization(db_session, user.id), original)


def test_agent_run_event_runtime_and_check_constraint_accept_tool_failed(db_session):
    assert "tool_failed" in AGENT_RUN_EVENT_TYPES
    row = AgentRunEvent(
        id=uuid4(),
        run_id=uuid4(),
        event_type="tool_failed",
        label="Tool failed",
        status="failed",
        payload_json="{}",
    )
    db_session.add(row)
    db_session.commit()
    assert db_session.get(AgentRunEvent, row.id).event_type == "tool_failed"

    db_session.add(
        AgentRunEvent(
            id=uuid4(),
            run_id=uuid4(),
            event_type="not_in_runtime_set",
            label="Invalid",
            status="failed",
            payload_json="{}",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_user_routine_executes_with_current_owner_scope(db_session, monkeypatch):
    from services.ai_agent import routine_service

    _scope(db_session)
    owner = _user(db_session, user_id=15, sources=[10], folders=[1])
    routine = AgentRoutine(
        id=uuid4(),
        name="Owner scoped",
        task_prompt="summary",
        cron="0 12 * * 1",
        kind="summary",
        enabled=True,
        deliver_to_channel=False,
        deliver_to_chat=False,
        created_by_user_id=owner.id,
        config_json="{}",
    )
    db_session.add(routine)
    db_session.commit()
    captured = {}

    @contextmanager
    def _session():
        yield db_session

    async def _run_kind(_db, _kind, _config, current_user, scope, task_prompt=None):
        captured.update(current_user=current_user, scope=scope, prompt=task_prompt)
        return {"summary": "ok", "data": {}}

    monkeypatch.setattr(routine_service, "SessionLocal", _session)
    monkeypatch.setattr(routine_service, "_run_kind", _run_kind)

    result = asyncio.run(routine_service.execute_routine(routine.id, trigger="manual"))

    assert result["ok"] is True
    assert captured["current_user"]["id"] == owner.id
    assert captured["current_user"]["role"] == "operator"
    assert captured["scope"]["allowed_chat_ids"] == [10]


def test_codes_off_requires_live_app_admin_and_mutation_control(db_session, monkeypatch):
    auth_bot_handler = pytest.importorskip("services.auth_bot_handler")
    _user(db_session, user_id=14, role="admin", telegram_id=1400)

    class SessionFactory:
        def __call__(self):
            return db_session

    message = SimpleNamespace(from_user=SimpleNamespace(id=1400, username="admin"))
    monkeypatch.setattr(auth_bot_handler, "SessionLocal", SessionFactory())
    monkeypatch.setattr(auth_bot_handler, "AUTH_ADMIN_IDS", {1400})

    assert auth_bot_handler._current_app_admin_id(message) == 14
    db_session.get(User, 14).is_active = False
    db_session.commit()
    assert auth_bot_handler._current_app_admin_id(message) is None

    replies = []

    async def _reply(_message, text, **_kwargs):
        replies.append(text)

    monkeypatch.setattr(auth_bot_handler, "_bot_control_enabled", lambda: False)
    monkeypatch.setattr(auth_bot_handler, "_safe_reply", _reply)
    monkeypatch.setattr(auth_bot_handler, "_audit", lambda *_args, **_kwargs: None)
    assert asyncio.run(
        auth_bot_handler._ensure_mutation_allowed_message(message, "codes_off")
    ) is False
    assert replies and "Read-only" in replies[0]
