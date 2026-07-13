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
from database.models import AccessScope, Transaction
from services.access_control_service import hash_password, years_to_json
from services.root_access_config_service import hash_password_pbkdf2, reset_root_access_cache
from fake_auth_redis import install_fake_auth_redis, issue_active_app_token, seed_test_user


@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

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
        seed_test_user(db_session, username="scope-test-admin")
    )

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
                    "Authorization": f"Bearer {app_user_token}",
                }
            )
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.router.lifespan_context = original_lifespan
        reset_root_access_cache()


def _add_tx(db_session, *, year: int, idx: int):
    tx = Transaction(
        raw_message=f"tx-{idx}",
        source_type="AUTO",
        source_chat_id=100,
        source_message_id=idx,
        transaction_date=datetime(year, 1, 15, 10, 30, 0),
        amount=Decimal("-100.00"),
        currency="UZS",
        card_last_4="1111",
        operator_raw="Operator",
        application_mapped="App",
        transaction_type="DEBIT",
        parsing_method="REGEX_SMS",
        fingerprint=f"fp-{idx}",
    )
    db_session.add(tx)
    db_session.commit()


def _add_scope(
    db_session,
    *,
    name: str,
    password: str,
    years=None,
    period_start=None,
    period_end=None,
    allow_transactions=True,
    allow_sources=False,
):
    pwd_hash, salt = hash_password(password)
    scope = AccessScope(
        name=name,
        password_hash=pwd_hash,
        salt=salt,
        years_json=years_to_json(years or []),
        period_start=period_start,
        period_end=period_end,
        allow_transactions=allow_transactions,
        allow_sources=allow_sources,
        is_active=True,
    )
    db_session.add(scope)
    db_session.commit()
    return scope


def _unlock(client, *, password: str, action: str = "transactions", target_year=None):
    payload = {"password": password, "action": action}
    if target_year is not None:
        payload["target_year"] = target_year
    res = client.post("/api/security/unlock", json=payload)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data.get("token")
    return data["token"]


def test_years_endpoint_open_without_active_scopes(client, db_session):
    _add_tx(db_session, year=2025, idx=1)
    _add_tx(db_session, year=2026, idx=2)

    res = client.get("/api/transactions/years")
    assert res.status_code == 200
    years = [item["year"] for item in res.json()["items"]]
    assert years == [2025, 2026]


def test_transactions_require_scope_token_when_scope_enabled(client, db_session):
    _add_tx(db_session, year=2026, idx=10)
    _add_scope(db_session, name="tx-only", password="1234", years=[2026], allow_transactions=True, allow_sources=False)

    operator = seed_test_user(
        db_session,
        username="scope-missing-token-operator",
        role="operator",
    )
    operator_token = issue_active_app_token(operator)

    res = client.get(
        "/api/transactions/years",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert res.status_code == 403
    assert "Scoped access token required" in res.text


def test_unlock_filters_transaction_years(client, db_session):
    _add_tx(db_session, year=2025, idx=20)
    _add_tx(db_session, year=2026, idx=21)
    _add_scope(db_session, name="y2026", password="4321", years=[2026], allow_transactions=True, allow_sources=False)

    token = _unlock(client, password="4321", action="transactions", target_year=2026)
    headers = {"X-Access-Token": token}

    years_res = client.get("/api/transactions/years", headers=headers)
    assert years_res.status_code == 200
    assert years_res.json()["items"] == [{"year": 2026, "count": 1}]

    list_res = client.get("/api/transactions/", params={"page": 1, "page_size": 100}, headers=headers)
    assert list_res.status_code == 200
    items = list_res.json()["items"]
    assert len(items) == 1
    assert items[0]["transaction_date"].startswith("2026-")


def test_transactions_scope_cannot_access_sources(client, db_session):
    _add_scope(db_session, name="tx-access", password="1111", years=[2026], allow_transactions=True, allow_sources=False)

    token = _unlock(client, password="1111", action="transactions", target_year=2026)
    res = client.get("/api/userbot/config", headers={"X-Access-Token": token})
    assert res.status_code == 403
    assert "Scope does not allow source access" in res.text


def test_sources_scope_cannot_access_transactions(client, db_session):
    _add_tx(db_session, year=2026, idx=40)
    _add_scope(db_session, name="src-access", password="2222", years=[2026], allow_transactions=False, allow_sources=True)

    token = _unlock(client, password="2222", action="sources", target_year=2026)
    tx_res = client.get("/api/transactions/years", headers={"X-Access-Token": token})
    assert tx_res.status_code == 403
    assert "Scope does not allow transaction access" in tx_res.text

    src_res = client.get("/api/userbot/config", headers={"X-Access-Token": token})
    assert src_res.status_code == 200


def test_security_status_includes_years_from_period_range(client, db_session):
    _add_scope(
        db_session,
        name="period-scope",
        password="3333",
        years=[],
        period_start=datetime(2025, 3, 1, 0, 0, 0),
        period_end=datetime(2026, 2, 1, 0, 0, 0),
    )

    res = client.get("/api/security/status")
    assert res.status_code == 200
    body = res.json()
    assert body["scopes_enabled"] is True
    assert body["available_years"] == [2025, 2026]


def test_unlock_respects_partial_period_bounds(client, db_session):
    _add_scope(
        db_session,
        name="from-2026",
        password="4444",
        years=[],
        period_start=datetime(2026, 1, 1, 0, 0, 0),
        period_end=None,
        allow_transactions=True,
        allow_sources=False,
    )

    fail_res = client.post(
        "/api/security/unlock",
        json={"password": "4444", "target_year": 2025, "action": "transactions"},
    )
    assert fail_res.status_code == 401

    ok_res = client.post(
        "/api/security/unlock",
        json={"password": "4444", "target_year": 2026, "action": "transactions"},
    )
    assert ok_res.status_code == 200
