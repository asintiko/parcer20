import json
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal

import pytest

pytest.importorskip("fastapi")
fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from api.main import app
from database.connection import get_db_session
from database.models import Transaction
from services.root_access_config_service import (
    hash_password_pbkdf2,
    reset_root_access_cache,
)
from fake_auth_redis import install_fake_auth_redis, issue_active_app_token, seed_test_user


def _add_tx(db_session, *, year: int, idx: int):
    tx = Transaction(
        raw_message=f"tx-{idx}",
        source_type="AUTO",
        source_chat_id=500,
        source_message_id=idx,
        transaction_date=datetime(year, 1, 1, 8, 0, 0),
        amount=Decimal("-100.00"),
        currency="UZS",
        card_last_4="0001",
        operator_raw="Operator",
        application_mapped="App",
        transaction_type="DEBIT",
        parsing_method="REGEX_SMS",
        fingerprint=f"system-fp-{idx}",
    )
    db_session.add(tx)
    db_session.commit()


def _make_config(path, *, system_token: str, scopes=None):
    token_hash, token_salt = hash_password_pbkdf2(system_token, "system-test-salt")
    payload = {
        "version": 1,
        "system_access": {
            "enforced": True,
            "tokens": [
                {
                    "id": "system-test",
                    "kind": "pbkdf2_sha256",
                    "hash": token_hash,
                    "salt": token_salt,
                    "active": True,
                }
            ],
        },
        "scopes": scopes or [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _client_with_env(db_session, monkeypatch, *, config_path, with_token=None, scopes_managed="false"):
    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    monkeypatch.setenv("SYSTEM_ACCESS_ENFORCED", "true")
    monkeypatch.setenv("SCOPES_MANAGED_BY_CONFIG", scopes_managed)
    monkeypatch.setenv("ROOT_ACCESS_SERVER_CONFIG_PATH", str(config_path))
    install_fake_auth_redis(monkeypatch)
    reset_root_access_cache()

    app_user_token = issue_active_app_token(
        seed_test_user(db_session, username="system-access-test-admin")
    )

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = noop_lifespan

    def override_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_db
    client = TestClient(app)
    if with_token:
        client.headers.update({"X-System-Access": with_token})
    client.headers.update({"Authorization": f"Bearer {app_user_token}"})
    original_close = client.close

    def close_with_cleanup():
        original_close()
        app.dependency_overrides.pop(get_db_session, None)
        app.router.lifespan_context = original_lifespan
        reset_root_access_cache()

    client.close = close_with_cleanup
    return client


def test_blocked_when_server_config_missing(db_session, monkeypatch, tmp_path):
    missing_path = tmp_path / "missing-root-config.json"

    client = _client_with_env(
        db_session,
        monkeypatch,
        config_path=missing_path,
        with_token=None,
        scopes_managed="false",
    )
    try:
        res = client.get("/api/transactions/years")
        assert res.status_code == 503
        assert "root access config" in res.text.lower()
    finally:
        client.close()


def test_requires_system_token_when_config_present(db_session, monkeypatch, tmp_path):
    config_path = tmp_path / "root-access.server.json"
    _make_config(config_path, system_token="token-123")

    client = _client_with_env(
        db_session,
        monkeypatch,
        config_path=config_path,
        with_token=None,
        scopes_managed="false",
    )
    try:
        res = client.get("/api/transactions/years")
        assert res.status_code == 403
        assert "x-system-access" in res.text.lower()
    finally:
        client.close()


def test_allows_api_with_valid_system_token(db_session, monkeypatch, tmp_path):
    _add_tx(db_session, year=2026, idx=1)
    config_path = tmp_path / "root-access.server.json"
    _make_config(config_path, system_token="token-abc")

    client = _client_with_env(
        db_session,
        monkeypatch,
        config_path=config_path,
        with_token="token-abc",
        scopes_managed="false",
    )
    try:
        res = client.get("/api/transactions/years")
        assert res.status_code == 200
        assert res.json()["items"] == [{"year": 2026, "count": 1}]
    finally:
        client.close()


def test_config_managed_scope_filters_years(db_session, monkeypatch, tmp_path):
    _add_tx(db_session, year=2025, idx=10)
    _add_tx(db_session, year=2026, idx=11)

    scope_hash, scope_salt = hash_password_pbkdf2("scope-2025-pass", "scope-salt")
    config_path = tmp_path / "root-access.server.json"
    _make_config(
        config_path,
        system_token="token-scope",
        scopes=[
            {
                "id": 2025,
                "name": "Папка 2025",
                "password": {
                    "kind": "pbkdf2_sha256",
                    "hash": scope_hash,
                    "salt": scope_salt,
                    "active": True,
                },
                "years": [2025],
                "allow_transactions": True,
                "allow_sources": False,
                "is_active": True,
            }
        ],
    )

    client = _client_with_env(
        db_session,
        monkeypatch,
        config_path=config_path,
        with_token="token-scope",
        scopes_managed="true",
    )
    try:
        unlock = client.post(
            "/api/security/unlock",
            json={"password": "scope-2025-pass", "action": "transactions", "target_year": 2025},
        )
        assert unlock.status_code == 200, unlock.text
        access_token = unlock.json()["token"]

        years_res = client.get("/api/transactions/years", headers={"X-Access-Token": access_token})
        assert years_res.status_code == 200
        assert years_res.json()["items"] == [{"year": 2025, "count": 1}]
    finally:
        client.close()
