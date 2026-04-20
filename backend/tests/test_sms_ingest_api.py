import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict

import pytest

pytest.importorskip("fastapi")
fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from api.main import app
from database.connection import get_db_session
from database.models import AccessAuditLog, Transaction
from services.fingerprint import compute_fingerprint_v1
from services.root_access_config_service import hash_password_pbkdf2, reset_root_access_cache


def _sms_payload(*, device_id: str = "android-1", message_id: str = "msg-1", text: str = "PAY 100") -> Dict[str, Any]:
    return {
        "device_id": device_id,
        "messages": [
            {
                "device_sms_id": message_id,
                "sender": "+998900000001",
                "text": text,
                "received_at": "2026-02-14T10:31:00",
                "sim_slot": 0,
            }
        ],
    }


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
    monkeypatch.setenv("MOBILE_SMS_INGEST_KEY", "sms-test-key")
    monkeypatch.setenv("MOBILE_SMS_INGEST_RATE_LIMIT_PER_MIN", "50")
    monkeypatch.setenv("MOBILE_SMS_INGEST_MAX_BATCH", "50")
    reset_root_access_cache()

    class FakeParserOrchestrator:
        def __init__(self, _db):
            pass

        def parse_text(self, raw_text: str):
            if "SKIP" in raw_text.upper():
                return None
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

    class FakeRedis:
        def __init__(self):
            self.counters = {}

        async def incr(self, key: str) -> int:
            self.counters[key] = self.counters.get(key, 0) + 1
            return self.counters[key]

        async def expire(self, key: str, _ttl: int) -> bool:
            return key in self.counters

    fake_redis = FakeRedis()

    async def fake_get_redis():
        return fake_redis

    monkeypatch.setattr("api.routes.sms.ParserOrchestrator", FakeParserOrchestrator)
    monkeypatch.setattr("api.routes.sms.get_redis", fake_get_redis)
    monkeypatch.setattr("database.connection.SessionLocal", lambda: db_session)

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = noop_lifespan

    def override_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_db

    try:
        with TestClient(app) as test_client:
            yield test_client, system_token
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.router.lifespan_context = original_lifespan
        reset_root_access_cache()


def test_ingest_requires_mobile_key(client):
    test_client, _ = client
    response = test_client.post(
        "/api/sms/ingest",
        json=_sms_payload(),
    )
    assert response.status_code == 403


def test_ingest_does_not_require_system_access(client):
    test_client, _ = client
    response = test_client.post(
        "/api/sms/ingest",
        headers={"X-Mobile-Ingest-Key": "sms-test-key"},
        json=_sms_payload(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["created"] == 1


def test_ingest_created_flow(client):
    test_client, _ = client
    response = test_client.post(
        "/api/sms/ingest",
        headers={
            "X-Mobile-Ingest-Key": "sms-test-key",
        },
        json=_sms_payload(message_id="created-1", text="PAY 100"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] == 1
    assert body["duplicates"] == 0
    assert body["skipped"] == 0
    assert body["errors"] == 0
    assert body["results"][0]["status"] == "created"


def test_ingest_duplicate_flow(client):
    test_client, _ = client
    headers = {
        "X-Mobile-Ingest-Key": "sms-test-key",
    }

    first = test_client.post(
        "/api/sms/ingest",
        headers=headers,
        json=_sms_payload(message_id="dup-1", text="PAY 100"),
    )
    assert first.status_code == 200, first.text
    assert first.json()["created"] == 1

    second = test_client.post(
        "/api/sms/ingest",
        headers=headers,
        json=_sms_payload(message_id="dup-2", text="PAY 100"),
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["created"] == 0
    assert body["duplicates"] == 1
    assert body["results"][0]["status"] == "duplicate"


def test_ingest_skipped_flow(client):
    test_client, _ = client
    response = test_client.post(
        "/api/sms/ingest",
        headers={
            "X-Mobile-Ingest-Key": "sms-test-key",
        },
        json=_sms_payload(message_id="skip-1", text="skip this message"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] == 0
    assert body["duplicates"] == 0
    assert body["skipped"] == 1
    assert body["results"][0]["status"] == "skipped"


def test_ingest_respects_batch_limit(client, monkeypatch):
    test_client, _ = client
    monkeypatch.setenv("MOBILE_SMS_INGEST_MAX_BATCH", "1")

    payload = {
        "device_id": "android-1",
        "messages": [
            {
                "device_sms_id": "batch-1",
                "sender": "+998900000001",
                "text": "PAY 100",
                "received_at": "2026-02-14T10:31:00",
                "sim_slot": 0,
            },
            {
                "device_sms_id": "batch-2",
                "sender": "+998900000001",
                "text": "PAY 200",
                "received_at": "2026-02-14T10:32:00",
                "sim_slot": 0,
            },
        ],
    }
    response = test_client.post(
        "/api/sms/ingest",
        headers={
            "X-Mobile-Ingest-Key": "sms-test-key",
        },
        json=payload,
    )
    assert response.status_code == 422
    assert "Maximum 1 messages per request" in response.text


def test_ingest_rate_limit_429(client, monkeypatch):
    test_client, _ = client
    monkeypatch.setenv("MOBILE_SMS_INGEST_RATE_LIMIT_PER_MIN", "1")

    headers = {
        "X-Mobile-Ingest-Key": "sms-test-key",
    }
    first = test_client.post("/api/sms/ingest", headers=headers, json=_sms_payload(message_id="rate-1"))
    assert first.status_code == 200, first.text

    second = test_client.post("/api/sms/ingest", headers=headers, json=_sms_payload(message_id="rate-2"))
    assert second.status_code == 429


def test_ingest_writes_success_audit_log(client, db_session):
    test_client, _ = client
    response = test_client.post(
        "/api/sms/ingest",
        headers={"X-Mobile-Ingest-Key": "sms-test-key"},
        json=_sms_payload(message_id="audit-1", text="PAY 100"),
    )
    assert response.status_code == 200, response.text
    row = (
        db_session.query(AccessAuditLog)
        .filter(AccessAuditLog.action == "sms_ingest")
        .order_by(AccessAuditLog.id.desc())
        .first()
    )
    assert row is not None
    assert row.success is True


def test_ingest_dual_mode_detects_legacy_fingerprint_duplicates(client, db_session, monkeypatch):
    test_client, _ = client
    monkeypatch.setenv("FINGERPRINT_DEDUP_MODE", "dual")
    # Fake parser produces this amount/date/card/operator.
    legacy_fp = compute_fingerprint_v1(
        amount="100000.00",
        transaction_date=datetime.fromisoformat("2026-02-14T10:30:00"),
        card_last4="0907",
    )
    db_session.add(
        Transaction(
            raw_message="legacy row",
            source_type="AUTO",
            source_chat_id=1,
            source_message_id=1,
            transaction_date=datetime.fromisoformat("2026-02-14T10:30:00"),
            amount=-100000,
            currency="UZS",
            card_last_4="0907",
            operator_raw="SMS SHOP",
            application_mapped="Legacy",
            transaction_type="DEBIT",
            balance_after=None,
            is_p2p=False,
            parsing_method="REGEX_SMS",
            parsing_confidence=0.8,
            fingerprint=legacy_fp,
        )
    )
    db_session.commit()

    response = test_client.post(
        "/api/sms/ingest",
        headers={"X-Mobile-Ingest-Key": "sms-test-key"},
        json=_sms_payload(message_id="legacy-dup", text="PAY 100"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["duplicates"] == 1
    assert body["results"][0]["status"] == "duplicate"


def test_normalize_datetime_uses_configured_timezone(monkeypatch):
    from api.routes.sms import _normalize_datetime

    monkeypatch.setenv("APP_TIMEZONE", "UTC")
    normalized = _normalize_datetime("2026-02-14T10:30:00+05:00")
    assert normalized is not None
    assert normalized.hour == 5
    assert normalized.minute == 30
