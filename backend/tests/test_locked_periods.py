import json
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal

import pytest

pytest.importorskip("fastapi")
fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from api.main import app
from database.connection import get_db_session
from database.models import LockedPeriod, Transaction
from services.auth_bot_service import create_launch_session_token
from services.root_access_config_service import hash_password_pbkdf2, reset_root_access_cache
from fake_auth_redis import install_fake_auth_redis, issue_active_app_token, seed_test_user


def _add_tx(db_session, idx: int, day: int) -> Transaction:
    tx = Transaction(
        raw_message=f"locked-period-tx-{idx}",
        source_type="AUTO",
        source_chat_id=555,
        source_message_id=idx,
        transaction_date=datetime(2026, 1, day, 10, 0, 0),
        amount=Decimal("-100.00"),
        currency="UZS",
        card_last_4="2222",
        operator_raw="Operator",
        application_mapped="App",
        transaction_type="DEBIT",
        parsing_method="REGEX_SMS",
        fingerprint=f"locked-fp-{idx}",
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    return tx


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
        seed_test_user(db_session, username="locked-period-test-admin")
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
                    "X-Launch-Session": create_launch_session_token(ip_address="127.0.0.1"),
                    "Authorization": f"Bearer {app_user_token}",
                }
            )
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.router.lifespan_context = original_lifespan
        reset_root_access_cache()


def test_locked_period_filters_transactions_and_blocks_create(client, db_session):
    open_tx = _add_tx(db_session, idx=1, day=10)
    _add_tx(db_session, idx=2, day=20)

    db_session.add(
        LockedPeriod(
            date_from=date(2026, 1, 15),
            date_to=date(2026, 1, 25),
            reason="audit",
            locked_by_tg_id=1,
            is_active=True,
        )
    )
    db_session.commit()

    years_res = client.get("/api/transactions/years")
    assert years_res.status_code == 200
    assert years_res.json()["items"] == [{"year": 2026, "count": 1}]

    list_res = client.get(
        "/api/transactions/",
        params={
            "page": 1,
            "page_size": 100,
            "date_from": "2026-01-01T00:00:00",
            "date_to": "2026-01-31T23:59:59",
        },
    )
    assert list_res.status_code == 200, list_res.text
    body = list_res.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == open_tx.id
    assert body["locked_notice"] == "Часть запрошенного периода заблокирована"

    create_blocked = client.post(
        "/api/transactions/",
        json={
            "datetime": "2026-01-20T12:00:00",
            "operator": "Manual operator",
            "amount": "150000",
            "card_last4": "1234",
            "transaction_type": "DEBIT",
            "currency": "UZS",
            "app": "Demo",
        },
    )
    assert create_blocked.status_code == 403
    assert "locked period" in create_blocked.text.lower()
