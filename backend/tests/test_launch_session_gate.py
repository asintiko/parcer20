import json
from contextlib import asynccontextmanager

import pytest

pytest.importorskip("fastapi")
fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from api.main import app
from database.connection import get_db_session
from database.models import AppLaunchConfig, User
from services.access_control_service import hash_password
from services.auth_bot_service import create_launch_session_token
from services.root_access_config_service import hash_password_pbkdf2, reset_root_access_cache
from fake_auth_redis import (
    install_fake_auth_redis,
    issue_active_app_token,
    register_launch_session,
)


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
    monkeypatch.setenv("LAUNCH_GATE_ENABLED", "true")
    monkeypatch.setattr("api.main._launch_gate_cache_value", None)
    monkeypatch.setattr("api.main._launch_gate_cache_expires_at", 0.0)
    monkeypatch.setattr("api.main._get_launch_gate_enabled_runtime", lambda: True)
    install_fake_auth_redis(monkeypatch)
    reset_root_access_cache()

    password_hash, password_salt = hash_password("Strong!123")
    user = User(
        username="launch-test-admin",
        password_hash=password_hash,
        salt=password_salt,
        role="admin",
        display_name="Launch Test Admin",
        allowed_tabs='["dashboard","reference","automation","userbot","logs","admin"]',
        allowed_folders="[]",
        forbidden_periods="[]",
        allowed_sources="[]",
        can_toggle_sources=True,
        permissions_version=1,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    app_user_token = issue_active_app_token(user)

    # Launch middleware uses SessionLocal directly; point it to our test session.
    monkeypatch.setattr("database.connection.SessionLocal", lambda: db_session)

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


def test_launch_session_required_for_protected_api(client, db_session):
    password_hash, salt = hash_password("launch-secret")
    db_session.add(
        AppLaunchConfig(
            id=1,
            password_hash=password_hash,
            salt=salt,
            failed_attempts=0,
        )
    )
    db_session.commit()

    status_res = client.get("/api/security/app/launch-status")
    assert status_res.status_code == 200
    assert status_res.json()["password_set"] is True

    blocked = client.get("/api/transactions/years")
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["error"] == "launch_required"

    launch_token = register_launch_session(
        create_launch_session_token(ip_address="127.0.0.1")
    )
    allowed = client.get("/api/transactions/years", headers={"X-Launch-Session": launch_token})
    assert allowed.status_code == 200, allowed.text


def test_sms_endpoints_exempt_from_launch_session(client, db_session, monkeypatch):
    password_hash, salt = hash_password("launch-secret")
    db_session.add(
        AppLaunchConfig(
            id=1,
            password_hash=password_hash,
            salt=salt,
            failed_attempts=0,
        )
    )
    db_session.commit()

    mobile_device_id = "android-test-1"
    mobile_key = "sms-test-key-0123456789abcdef0123456789"
    monkeypatch.setenv(
        "MOBILE_DEVICE_KEYS_JSON",
        json.dumps({mobile_device_id: {"current": mobile_key}}),
    )

    class FakeParserOrchestrator:
        def __init__(self, _db):  # noqa: D401, ANN001
            pass

        def parse_text(self, _text, fallback_datetime=None):  # noqa: ARG002
            return {
                "transaction_date": "2026-02-14T10:30:00",
                "amount": "100000.00",
                "currency": "UZS",
                "card_last_4": "0907",
                "operator_raw": "SMS SHOP",
                "transaction_type": "DEBIT",
                "parsing_method": "REGEX_SMS",
                "parsing_confidence": 0.91,
            }

    monkeypatch.setattr("api.routes.sms.ParserOrchestrator", FakeParserOrchestrator)

    mobile_headers = {
        "X-Mobile-Device-Id": mobile_device_id,
        "X-Mobile-Ingest-Key": mobile_key,
    }
    health_res = client.get("/api/sms/health", headers=mobile_headers)
    assert health_res.status_code == 200, health_res.text

    ingest_res = client.post(
        "/api/sms/ingest",
        headers=mobile_headers,
        json={
            "device_id": mobile_device_id,
            "messages": [
                {
                    "device_sms_id": "msg-1",
                    "sender": "+998900000001",
                    "text": "Pokupka 100000 UZS card ***0907",
                    "received_at": "2026-02-14T10:31:00",
                    "sim_slot": 0,
                }
            ],
        },
    )
    assert ingest_res.status_code == 200, ingest_res.text
    body = ingest_res.json()
    assert body["created"] == 1
