import asyncio

import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException
from starlette.requests import HTTPConnection

from api import dependencies


def _connection() -> HTTPConnection:
    return HTTPConnection(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/transactions/export.csv",
            "headers": [],
            "client": ("203.0.113.7", 12345),
        }
    )


def _require(db_session, key):
    return asyncio.run(
        dependencies.require_export_key(conn=_connection(), db=db_session, x_export_key=key)
    )


def test_export_key_not_configured_returns_503(db_session, monkeypatch):
    monkeypatch.delenv("TRANSACTIONS_EXPORT_KEY", raising=False)
    monkeypatch.delenv("TRANSACTIONS_EXPORT_KEY_PREVIOUS", raising=False)
    with pytest.raises(HTTPException) as exc:
        _require(db_session, "anything")
    assert exc.value.status_code == 503


def test_export_key_missing_returns_403(db_session, monkeypatch):
    monkeypatch.setenv("TRANSACTIONS_EXPORT_KEY", "s3cret-export-key")
    with pytest.raises(HTTPException) as exc:
        _require(db_session, None)
    assert exc.value.status_code == 403


def test_export_key_wrong_returns_403(db_session, monkeypatch):
    monkeypatch.setenv("TRANSACTIONS_EXPORT_KEY", "s3cret-export-key")
    with pytest.raises(HTTPException) as exc:
        _require(db_session, "wrong-key")
    assert exc.value.status_code == 403


def test_export_key_correct_passes(db_session, monkeypatch):
    monkeypatch.setenv("TRANSACTIONS_EXPORT_KEY", "s3cret-export-key")
    assert _require(db_session, "s3cret-export-key") is None


def test_export_key_previous_still_accepted_during_rotation(db_session, monkeypatch):
    monkeypatch.setenv("TRANSACTIONS_EXPORT_KEY", "new-key")
    monkeypatch.setenv("TRANSACTIONS_EXPORT_KEY_PREVIOUS", "old-key")
    assert _require(db_session, "old-key") is None
