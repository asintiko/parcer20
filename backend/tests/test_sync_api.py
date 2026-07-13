import json
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")
fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from api.main import app
from api.routes.sync import _dt_to_iso
from database.connection import get_db_session
from database.models import AccessScope, ParsingLog, Transaction
from services.access_control_service import create_scope_token, hash_password, years_to_json
from services.auth_bot_service import create_launch_session_token
from services.root_access_config_service import hash_password_pbkdf2, reset_root_access_cache
from services.sync_deletion_service import register_sync_deletion_listeners
from fake_auth_redis import install_fake_auth_redis, issue_active_app_token, seed_test_user


def _add_tx(db_session, idx: int, year: int = 2026) -> Transaction:
    tx = Transaction(
        raw_message=f"sync-tx-{idx}",
        source_type="AUTO",
        source_chat_id=777,
        source_message_id=idx,
        transaction_date=datetime(year, 1, 10, 12, 0, 0),
        amount=Decimal("-100.00"),
        currency="UZS",
        card_last_4="1111",
        operator_raw="Operator",
        application_mapped="App",
        transaction_type="DEBIT",
        parsing_method="REGEX_SMS",
        fingerprint=f"sync-fp-{idx}",
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    return tx


def _add_scope(
    db_session,
    *,
    name: str = "sync-scope",
    years: list[int] | None = None,
    allow_transactions: bool = True,
    allow_sources: bool = False,
) -> AccessScope:
    password_hash, salt = hash_password("1234")
    scope = AccessScope(
        name=name,
        password_hash=password_hash,
        salt=salt,
        years_json=years_to_json(years or [2026]),
        allow_transactions=allow_transactions,
        allow_sources=allow_sources,
        is_active=True,
    )
    db_session.add(scope)
    db_session.commit()
    db_session.refresh(scope)
    return scope


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
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
    install_fake_auth_redis(monkeypatch)
    reset_root_access_cache()

    app_user_token = issue_active_app_token(
        seed_test_user(db_session, username="sync-test-admin")
    )

    class FakeRedis:
        def __init__(self):
            self.values = {}

        async def incr(self, key):
            self.values[key] = self.values.get(key, 0) + 1
            return self.values[key]

        async def expire(self, key, _ttl):
            return key in self.values

    fake_redis = FakeRedis()

    async def fake_get_redis():
        return fake_redis

    monkeypatch.setattr("api.routes.sync.get_redis", fake_get_redis)

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = noop_lifespan

    def override_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_db
    try:
        with TestClient(app) as test_client:
            test_client.headers.update(
                {
                    "X-System-Access": system_token,
                    "X-Launch-Session": create_launch_session_token(ip_address="127.0.0.1"),
                    "Authorization": f"Bearer {app_user_token}",
                }
            )
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.router.lifespan_context = original_lifespan
        reset_root_access_cache()


def test_sync_manifest_exposes_tables(client, db_session):
    _add_tx(db_session, idx=1)
    response = client.get("/api/sync/manifest")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "server_time" in payload
    assert "transactions" in payload["tables"]
    assert "checksum" in payload["tables"]["transactions"]


def test_sync_table_returns_deleted_ids(client, db_session):
    tx = _add_tx(db_session, idx=2)
    tx_id = int(tx.id)

    db_session.delete(tx)
    db_session.commit()

    response = client.get("/api/sync/transactions", params={"limit": 100, "offset": 0})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "deleted_ids" in payload
    assert tx_id in payload["deleted_ids"]
    assert "server_checksum" in payload
    assert "server_time" in payload


def test_sync_scope_without_sources_hides_service_tables(client, db_session):
    _add_tx(db_session, idx=3, year=2026)
    db_session.add(
        ParsingLog(
            raw_message="sync hidden",
            parsing_method="REGEX_SMS",
            success=True,
            created_at=datetime.utcnow(),
        )
    )
    db_session.commit()

    scope = _add_scope(
        db_session,
        name="tx-only-sync",
        years=[2026],
        allow_transactions=True,
        allow_sources=False,
    )
    token = create_scope_token(scope)
    headers = {"X-Access-Token": token}

    manifest_res = client.get("/api/sync/manifest", headers=headers)
    assert manifest_res.status_code == 200, manifest_res.text
    manifest = manifest_res.json()
    assert manifest["tables"]["transactions"]["row_count"] == 1
    assert manifest["tables"]["parsingLogs"]["row_count"] == 0

    logs_res = client.get("/api/sync/parsingLogs", headers=headers)
    assert logs_res.status_code == 200, logs_res.text
    logs_payload = logs_res.json()
    assert logs_payload["rows"] == []
    assert logs_payload["total_count"] == 0


def test_sync_cursor_pagination_returns_next_cursor(client, db_session):
    _add_tx(db_session, idx=101, year=2026)
    _add_tx(db_session, idx=102, year=2026)

    response = client.get(
        "/api/sync/transactions",
        params={
            "limit": 1,
            "cursor_updated_at": "1970-01-01T00:00:00Z",
            "cursor_id": 0,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["rows"]) == 1
    assert payload["has_more"] is True
    assert payload["next_cursor"] is not None
    assert int(payload["next_cursor"]["id"]) > 0
    assert payload["next_cursor"]["updated_at"]


def test_sync_rate_limit_fail_closed_when_redis_unavailable(client, monkeypatch):
    async def _boom():
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr("api.routes.sync.get_redis", _boom)
    response = client.get("/api/sync/manifest")
    assert response.status_code == 503, response.text
    assert "temporarily unavailable" in str(response.text).lower()


def test_dt_to_iso_serializes_uuid():
    value = uuid4()
    assert _dt_to_iso(value) == str(value)
