import asyncio
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException, Request, Response

from api import main
from database.models import AccessAuditLog, AppLaunchConfig, TgChatMessage, Transaction
from services import auth_bot_service, receipt_processor


class _SessionRedis:
    def __init__(self, *, data=None, revoked=False, error=False):
        self.data = data or {}
        self.revoked = revoked
        self.error = error

    async def exists(self, key):
        if self.error:
            raise ConnectionError("redis down")
        return int(self.revoked and "revoked:" in key)

    async def hgetall(self, _key):
        if self.error:
            raise ConnectionError("redis down")
        return dict(self.data)


def test_auth_bot_active_session_is_registered_kind_bound_and_fail_closed(monkeypatch):
    async def active_redis():
        return _SessionRedis(data={"token_kind": "launch_session"})

    monkeypatch.setattr(auth_bot_service, "get_redis", active_redis)
    assert asyncio.run(
        auth_bot_service.is_active_session("sid", expected_kind="launch_session")
    ) is True
    assert asyncio.run(
        auth_bot_service.is_active_session("sid", expected_kind="app_user")
    ) is False

    async def unavailable_redis():
        return _SessionRedis(error=True)

    monkeypatch.setattr(auth_bot_service, "get_redis", unavailable_redis)
    with pytest.raises(auth_bot_service.SessionStoreUnavailableError):
        asyncio.run(auth_bot_service.is_active_session("sid"))

    monkeypatch.setattr(
        auth_bot_service,
        "_get_sync_redis",
        lambda: (_ for _ in ()).throw(ConnectionError("redis down")),
    )
    assert auth_bot_service.is_session_revoked("sid") is True


def _request(path="/api/transactions/years"):
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"x-launch-session", b"signed")],
            "client": ("127.0.0.1", 50000),
            "server": ("test", 80),
        }
    )


def test_launch_middleware_requires_registered_session(db_session, monkeypatch):
    db_session.add(AppLaunchConfig(id=1, password_hash="hash", salt="salt"))
    db_session.commit()

    @contextmanager
    def fake_get_db():
        yield db_session

    monkeypatch.setattr(main, "_get_launch_gate_enabled_runtime", lambda: True)
    monkeypatch.setattr(main, "is_internal_request", lambda _request: False)
    monkeypatch.setattr(main, "verify_launch_session_token", lambda _token: {"sid": "sid"})
    monkeypatch.setattr("database.connection.get_db", fake_get_db)

    called = False

    async def call_next(_request):
        nonlocal called
        called = True
        return Response(status_code=204)

    async def inactive(_sid, *, expected_kind=None):
        return False

    monkeypatch.setattr(main, "is_active_session", inactive)
    middleware = main.LaunchSessionMiddleware(lambda *_args, **_kwargs: None)
    response = asyncio.run(middleware.dispatch(_request(), call_next))
    assert response.status_code == 403
    assert called is False

    async def unavailable(_sid, *, expected_kind=None):
        raise main.SessionStoreUnavailableError("down")

    monkeypatch.setattr(main, "is_active_session", unavailable)
    response = asyncio.run(middleware.dispatch(_request(), call_next))
    assert response.status_code == 503
    assert called is False

    async def active(_sid, *, expected_kind=None):
        return expected_kind == "launch_session"

    monkeypatch.setattr(main, "is_active_session", active)
    response = asyncio.run(middleware.dispatch(_request(), call_next))
    assert response.status_code == 204
    assert called is True


class _Manager:
    async def get_message(self, _chat_id, _message_id):
        return {"text": "receipt", "date": 1_768_214_400}


def _parsed(date_value):
    return {
        "transaction_date": date_value,
        "amount": Decimal("100000.00"),
        "currency": "UZS",
        "card_last_4": "1234",
        "operator_raw": "PAYME",
        "transaction_type": "DEBIT",
        "parsing_method": "REGEX_SMS",
        "parsing_confidence": 0.95,
    }


def test_receipt_authorization_runs_before_transaction_metadata_and_audit_commit(db_session, monkeypatch):
    message = TgChatMessage(
        chat_id=10,
        message_id=20,
        raw_json="{}",
        processing_status="queued",
    )
    db_session.add(message)
    db_session.commit()
    monkeypatch.setattr(
        receipt_processor,
        "_parse_text_in_worker",
        lambda *_args: _parsed(datetime(2025, 12, 31, 10, 0)),
    )

    def deny_final(values):
        assert values["source_chat_id"] == 10
        raise HTTPException(status_code=403, detail="outside_scope")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            receipt_processor.process_tdlib_message(
                10,
                20,
                False,
                db_session,
                _Manager(),
                authorize_result=deny_final,
            )
        )
    assert exc.value.status_code == 403
    db_session.expire_all()
    assert db_session.query(Transaction).count() == 0
    assert db_session.query(AccessAuditLog).count() == 0
    stored_message = db_session.query(TgChatMessage).filter_by(chat_id=10, message_id=20).one()
    assert stored_message.processing_status == "queued"
    assert stored_message.receipt_transaction_id is None


def test_force_reparse_denial_leaves_existing_transaction_and_metadata_unchanged(db_session, monkeypatch):
    existing = Transaction(
        raw_message="old",
        source_type="AUTO",
        source_chat_id=30,
        source_message_id=40,
        transaction_date=datetime(2026, 1, 2, 10, 0),
        amount=Decimal("-100000.00"),
        currency="UZS",
        operator_raw="OLD",
        transaction_type="DEBIT",
    )
    db_session.add(existing)
    db_session.flush()
    message = TgChatMessage(
        chat_id=30,
        message_id=40,
        raw_json="{}",
        processing_status="done",
        receipt_transaction_id=int(existing.id),
    )
    db_session.add(message)
    db_session.commit()
    transaction_id = int(existing.id)
    monkeypatch.setattr(
        receipt_processor,
        "_parse_text_in_worker",
        lambda *_args: {**_parsed(datetime(2025, 12, 31, 10, 0)), "operator_raw": "NEW"},
    )

    def authorize(values):
        if values["transaction_date"].year < 2026:
            raise HTTPException(status_code=403, detail="outside_scope")

    with pytest.raises(HTTPException):
        asyncio.run(
            receipt_processor.process_tdlib_message(
                30,
                40,
                True,
                db_session,
                _Manager(),
                authorize_result=authorize,
            )
        )
    db_session.expire_all()
    stored = db_session.get(Transaction, transaction_id)
    assert stored.operator_raw == "OLD"
    assert stored.transaction_date == datetime(2026, 1, 2, 10, 0)
    assert db_session.query(AccessAuditLog).count() == 0
    stored_message = db_session.query(TgChatMessage).filter_by(chat_id=30, message_id=40).one()
    assert stored_message.processing_status == "done"
    assert stored_message.receipt_transaction_id == transaction_id
