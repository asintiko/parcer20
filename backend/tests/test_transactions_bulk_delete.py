import json
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal

import pytest

pytest.importorskip("fastapi")
fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from api.main import app
from api.dependencies import get_current_app_user
from database.connection import get_db_session
from database.models import AccessScope, LockedPeriod, SyncDeletion, Transaction
from services.access_control_service import create_scope_token, hash_password, years_to_json
from services.auth_bot_service import create_launch_session_token
from services.root_access_config_service import hash_password_pbkdf2, reset_root_access_cache
from services.sync_deletion_service import register_sync_deletion_listeners


ADMIN_USER = {
    "id": 1,
    "user_id": 1,
    "username": "admin",
    "display_name": "Admin",
    "role": "admin",
    "allowed_tabs": ["dashboard"],
    "allowed_folders": [],
    "forbidden_periods": [],
    "allowed_sources": [],
    "can_toggle_sources": True,
    "permissions_version": 1,
    "session_ttl_days": 7,
}


def _seed_tx(db_session, *, idx: int, day: int = 10, source_chat_id: int = 100) -> Transaction:
    tx = Transaction(
        raw_message=f"del-tx-{idx}",
        source_type="AUTO",
        source_chat_id=source_chat_id,
        source_message_id=idx,
        transaction_date=datetime(2026, 1, day, 12, 0, 0),
        amount=Decimal("-100.00"),
        currency="UZS",
        card_last_4="1111",
        operator_raw="Operator",
        application_mapped="App",
        transaction_type="DEBIT",
        parsing_method="REGEX_SMS",
        fingerprint=f"del-fp-{idx}",
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    return tx


def _add_lock(db_session, *, date_from: date, date_to: date) -> None:
    db_session.add(
        LockedPeriod(
            date_from=date_from,
            date_to=date_to,
            reason="audit",
            locked_by_tg_id=1,
            is_active=True,
        )
    )
    db_session.commit()


@pytest.fixture
def user_holder():
    return {"user": dict(ADMIN_USER)}


@pytest.fixture
def client(db_session, monkeypatch, tmp_path, user_holder):
    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    register_sync_deletion_listeners()

    system_token = "test-system-token"
    token_hash, token_salt = hash_password_pbkdf2(system_token, "testsalt")
    config_path = tmp_path / "root-access.server.json"
    config_path.write_text(
        json.dumps(
            {
                "version": 1,
                "system_access": {
                    "enforced": True,
                    "tokens": [
                        {
                            "id": "tests",
                            "kind": "pbkdf2_sha256",
                            "hash": token_hash,
                            "salt": token_salt,
                            "active": True,
                        }
                    ],
                },
                "scopes": [],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("SYSTEM_ACCESS_ENFORCED", "true")
    monkeypatch.setenv("SCOPES_MANAGED_BY_CONFIG", "false")
    monkeypatch.setenv("ROOT_ACCESS_SERVER_CONFIG_PATH", str(config_path))
    reset_root_access_cache()

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = noop_lifespan

    def override_db():
        yield db_session

    async def override_current_app_user():
        return user_holder["user"]

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_current_app_user] = override_current_app_user
    try:
        with TestClient(app) as test_client:
            test_client.headers.update(
                {
                    "X-System-Access": system_token,
                    "X-Launch-Session": create_launch_session_token(ip_address="127.0.0.1"),
                }
            )
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_current_app_user, None)
        app.router.lifespan_context = original_lifespan
        reset_root_access_cache()


def _recorded_deletions(db_session) -> set[int]:
    rows = (
        db_session.query(SyncDeletion.record_id)
        .filter(SyncDeletion.table_name == "transactions")
        .all()
    )
    return {int(r[0]) for r in rows}


def test_bulk_delete_records_sync_deletions(client, db_session):
    t1 = _seed_tx(db_session, idx=1)
    t2 = _seed_tx(db_session, idx=2)
    ids = [int(t1.id), int(t2.id)]

    res = client.post("/api/transactions/bulk-delete", json={"ids": ids})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["success"] is True
    assert body["deleted_count"] == 2
    assert body["failed_ids"] == []

    # actually removed from the database
    assert db_session.query(Transaction).filter(Transaction.id.in_(ids)).count() == 0
    # sync_deletions populated so clients learn about the removal on next sync
    # (the /api/sync endpoint surfacing deleted_ids is covered in test_sync_api)
    assert set(ids).issubset(_recorded_deletions(db_session))


def test_bulk_delete_admin_bypasses_locked_period(client, db_session):
    tx = _seed_tx(db_session, idx=3, day=15)
    _add_lock(db_session, date_from=date(2026, 1, 10), date_to=date(2026, 1, 20))

    res = client.post("/api/transactions/bulk-delete", json={"ids": [int(tx.id)]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["success"] is True
    assert body["deleted_count"] == 1
    assert db_session.get(Transaction, int(tx.id)) is None
    assert int(tx.id) in _recorded_deletions(db_session)


def test_bulk_delete_operator_blocked_by_locked_period(client, db_session, user_holder):
    password_hash, salt = hash_password("1234")
    scope = AccessScope(
        name="op-2026",
        password_hash=password_hash,
        salt=salt,
        years_json=years_to_json([2026]),
        allow_transactions=True,
        allow_sources=False,
        is_active=True,
    )
    db_session.add(scope)
    db_session.commit()
    db_session.refresh(scope)

    user_holder["user"] = {
        **ADMIN_USER,
        "id": 2,
        "user_id": 2,
        "username": "operator",
        "role": "operator",
        "allowed_folders": [int(scope.id)],
        "allowed_sources": [100],
    }

    tx = _seed_tx(db_session, idx=4, day=15)
    _add_lock(db_session, date_from=date(2026, 1, 10), date_to=date(2026, 1, 20))

    res = client.post(
        "/api/transactions/bulk-delete",
        json={"ids": [int(tx.id)]},
        headers={"X-Access-Token": create_scope_token(scope)},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["success"] is False
    assert body["deleted_count"] == 0
    assert int(tx.id) in body["failed_ids"]
    assert any("locked period" in str(e).lower() for e in body["errors"])
    # the row is still there because the lock blocked the delete
    assert db_session.get(Transaction, int(tx.id)) is not None
    assert int(tx.id) not in _recorded_deletions(db_session)
