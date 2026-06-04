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


def _seed_tx(db, *, amount, ttype, source_type, card, chat_id=0, currency="UZS",
             date="2026-05-10T12:00:00", operator="SHOP"):
    from services.fingerprint import compute_fingerprint
    from datetime import datetime as _dt
    d = _dt.fromisoformat(date)
    tx = Transaction(
        raw_message="seed", source_type=source_type, source_chat_id=chat_id,
        source_message_id=None, transaction_date=d, amount=amount, currency=currency,
        card_last_4=card, operator_raw=operator, transaction_type=ttype,
        parsing_method="REGEX_SMS", parsing_confidence=0.9,
        fingerprint=compute_fingerprint(amount=abs(amount), transaction_date=d,
                                        card_last4=card, operator_raw=operator,
                                        transaction_type=ttype),
    )
    db.add(tx)
    db.flush()
    return tx


def test_stats_requires_mobile_key(client):
    test_client, _ = client
    resp = test_client.get("/api/sms/stats")
    assert resp.status_code == 403


def test_stats_aggregates_volume_and_counts(client, db_session):
    test_client, _ = client
    _seed_tx(db_session, amount=-100000, ttype="DEBIT", source_type="SMS", card="0907")
    _seed_tx(db_session, amount=-50000, ttype="DEBIT", source_type="AUTO", card="0907", chat_id=-100)
    _seed_tx(db_session, amount=20000, ttype="CREDIT", source_type="SMS", card="4862")
    db_session.commit()

    resp = test_client.get("/api/sms/stats", headers={"X-Mobile-Ingest-Key": "sms-test-key"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["transaction_count"] == 3
    assert body["debit_count"] == 2
    assert body["credit_count"] == 1
    assert body["total_volume"] == "170000.00"
    assert body["debit_volume"] == "150000.00"
    assert body["credit_volume"] == "20000.00"
    sources = {row["source"]: row for row in body["by_source"]}
    assert sources["SMS"]["count"] == 2
    assert sources["TELEGRAM"]["count"] == 1
    cards = {row["card_last_4"]: row for row in body["by_card"]}
    assert cards["0907"]["count"] == 2


def test_stats_filter_by_source_and_card(client, db_session):
    test_client, _ = client
    _seed_tx(db_session, amount=-100000, ttype="DEBIT", source_type="SMS", card="0907")
    _seed_tx(db_session, amount=-50000, ttype="DEBIT", source_type="AUTO", card="0907", chat_id=-100)
    _seed_tx(db_session, amount=-30000, ttype="DEBIT", source_type="SMS", card="4862")
    db_session.commit()
    h = {"X-Mobile-Ingest-Key": "sms-test-key"}

    only_sms = test_client.get("/api/sms/stats?source=sms", headers=h).json()
    assert only_sms["transaction_count"] == 2
    assert only_sms["total_volume"] == "130000.00"

    only_card = test_client.get("/api/sms/stats?card=0907", headers=h).json()
    assert only_card["transaction_count"] == 2
    assert only_card["total_volume"] == "150000.00"

    tg_chat = test_client.get("/api/sms/stats?source=telegram&source_chat_id=-100", headers=h).json()
    assert tg_chat["transaction_count"] == 1
    assert tg_chat["total_volume"] == "50000.00"


def test_stats_filter_by_period(client, db_session):
    test_client, _ = client
    _seed_tx(db_session, amount=-100000, ttype="DEBIT", source_type="SMS", card="0907", date="2026-05-01T10:00:00")
    _seed_tx(db_session, amount=-200000, ttype="DEBIT", source_type="SMS", card="0907", date="2026-05-20T10:00:00")
    db_session.commit()
    h = {"X-Mobile-Ingest-Key": "sms-test-key"}

    body = test_client.get("/api/sms/stats?date_from=2026-05-15T00:00:00", headers=h).json()
    assert body["transaction_count"] == 1
    assert body["total_volume"] == "200000.00"


def test_sources_lists_telegram_chats(client, db_session):
    test_client, _ = client
    _seed_tx(db_session, amount=-100000, ttype="DEBIT", source_type="AUTO", card="0907", chat_id=-100, operator="A")
    _seed_tx(db_session, amount=-50000, ttype="DEBIT", source_type="AUTO", card="0907", chat_id=-100, operator="B")
    _seed_tx(db_session, amount=-30000, ttype="DEBIT", source_type="AUTO", card="4862", chat_id=-200, operator="C")
    _seed_tx(db_session, amount=-10000, ttype="DEBIT", source_type="SMS", card="4862")
    db_session.commit()

    resp = test_client.get("/api/sms/sources", headers={"X-Mobile-Ingest-Key": "sms-test-key"})
    assert resp.status_code == 200
    items = {row["chat_id"]: row for row in resp.json()["items"]}
    assert items[-100]["count"] == 2
    assert items[-200]["count"] == 1
    assert -1 not in items
    assert 0 not in items


class _TextSensitiveParser:
    """Parser whose amount (and thus fingerprint) varies with the SMS text, so a
    test can tell device_sms_id idempotency apart from fingerprint dedup."""

    def __init__(self, _db):
        pass

    def parse_text(self, raw_text: str):
        digits = "".join(c for c in raw_text if c.isdigit()) or "100"
        return {
            "transaction_date": "2026-02-14T10:30:00",
            "amount": f"{int(digits)}000.00",
            "currency": "UZS",
            "card_last_4": "0907",
            "operator_raw": "SMS SHOP",
            "transaction_type": "DEBIT",
            "parsing_method": "REGEX_SMS",
            "parsing_confidence": 0.91,
        }


def test_ingest_idempotent_by_device_sms_id_even_with_different_content(client, db_session, monkeypatch):
    # A re-sent (device_id, device_sms_id) must short-circuit to duplicate BEFORE
    # parsing — even if the new content would hash to a different fingerprint —
    # and must not create a second row. This is what blocks fingerprint-forgery
    # suppression and WorkManager replays from double-counting.
    test_client, _ = client
    monkeypatch.setattr("api.routes.sms.ParserOrchestrator", _TextSensitiveParser)
    headers = {"X-Mobile-Ingest-Key": "sms-test-key"}

    first = test_client.post(
        "/api/sms/ingest",
        headers=headers,
        json=_sms_payload(device_id="dev-A", message_id="same-id", text="PAY 100"),
    )
    assert first.status_code == 200, first.text
    assert first.json()["created"] == 1

    second = test_client.post(
        "/api/sms/ingest",
        headers=headers,
        json=_sms_payload(device_id="dev-A", message_id="same-id", text="PAY 999"),
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["created"] == 0
    assert body["duplicates"] == 1
    assert body["results"][0]["status"] == "duplicate"
    assert db_session.query(Transaction).count() == 1


def test_ingest_same_device_sms_id_distinct_per_device(client, db_session, monkeypatch):
    # The idempotency key is (device_id, device_sms_id): the same local id from a
    # different device is a different message. Distinct content keeps fingerprint
    # dedup out of the picture so we isolate the keying behaviour.
    test_client, _ = client
    monkeypatch.setattr("api.routes.sms.ParserOrchestrator", _TextSensitiveParser)
    headers = {"X-Mobile-Ingest-Key": "sms-test-key"}

    a = test_client.post(
        "/api/sms/ingest",
        headers=headers,
        json=_sms_payload(device_id="dev-A", message_id="shared-id", text="PAY 111"),
    )
    assert a.status_code == 200, a.text
    assert a.json()["created"] == 1

    b = test_client.post(
        "/api/sms/ingest",
        headers=headers,
        json=_sms_payload(device_id="dev-B", message_id="shared-id", text="PAY 222"),
    )
    assert b.status_code == 200, b.text
    assert b.json()["created"] == 1
    assert db_session.query(Transaction).count() == 2


def test_ingest_persists_source_device_columns(client, db_session):
    test_client, _ = client
    resp = test_client.post(
        "/api/sms/ingest",
        headers={"X-Mobile-Ingest-Key": "sms-test-key"},
        json=_sms_payload(device_id="dev-Z", message_id="persist-1", text="PAY 100"),
    )
    assert resp.status_code == 200, resp.text
    row = (
        db_session.query(Transaction)
        .filter(Transaction.source_device_sms_id == "persist-1")
        .first()
    )
    assert row is not None
    assert row.source_device_id == "dev-Z"
    assert row.source_device_sms_id == "persist-1"


# ---------------------------------------------------------------------------
# SmsParsedSummary tests
# ---------------------------------------------------------------------------

HEADERS = {"X-Mobile-Ingest-Key": "sms-test-key"}


def test_created_result_includes_parsed_summary(client):
    test_client, _ = client
    resp = test_client.post(
        "/api/sms/ingest",
        headers=HEADERS,
        json=_sms_payload(message_id="parsed-1", text="PAY 100"),
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["results"][0]
    assert item["status"] == "created"
    p = item["parsed"]
    assert p is not None
    # Fake parser returns amount 100000.00, DEBIT, UZS, card 0907, operator SMS SHOP
    assert p["amount"] == "100000.00"
    assert p["direction"] == "debit"
    assert p["transaction_type"] == "DEBIT"
    assert p["card_last_4"] == "0907"
    assert p["operator"] == "SMS SHOP"
    assert p["currency"] == "UZS"
    assert p["transaction_date"].startswith("2026-02-14")


def test_fingerprint_duplicate_parsed_populated(client):
    test_client, _ = client
    # First ingest creates the row
    r1 = test_client.post(
        "/api/sms/ingest",
        headers=HEADERS,
        json=_sms_payload(device_id="dev-fp", message_id="fp-1", text="PAY 100"),
    )
    assert r1.json()["created"] == 1

    # Second ingest: different device_sms_id but same fingerprint content
    r2 = test_client.post(
        "/api/sms/ingest",
        headers=HEADERS,
        json=_sms_payload(device_id="dev-fp", message_id="fp-2", text="PAY 100"),
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["duplicates"] == 1
    item = body["results"][0]
    assert item["status"] == "duplicate"
    p = item["parsed"]
    assert p is not None
    assert p["amount"] == "100000.00"
    assert p["direction"] == "debit"


def test_device_duplicate_parsed_populated(client):
    test_client, _ = client
    # First request creates the row
    r1 = test_client.post(
        "/api/sms/ingest",
        headers=HEADERS,
        json=_sms_payload(device_id="dev-dedup", message_id="dev-1", text="PAY 100"),
    )
    assert r1.json()["created"] == 1

    # Second request: same (device_id, device_sms_id) → device-idempotency branch
    r2 = test_client.post(
        "/api/sms/ingest",
        headers=HEADERS,
        json=_sms_payload(device_id="dev-dedup", message_id="dev-1", text="PAY 100"),
    )
    assert r2.status_code == 200
    item = r2.json()["results"][0]
    assert item["status"] == "duplicate"
    p = item["parsed"]
    assert p is not None
    assert p["amount"] == "100000.00"
    assert p["direction"] == "debit"


def test_credit_transaction_direction(client, monkeypatch):
    class CreditParser:
        def __init__(self, _db):
            pass

        def parse_text(self, raw_text: str):
            return {
                "transaction_date": "2026-02-14T10:30:00",
                "amount": "50000.00",
                "currency": "UZS",
                "card_last_4": "1234",
                "operator_raw": "CREDIT BANK",
                "transaction_type": "CREDIT",
                "parsing_method": "REGEX_SMS",
                "parsing_confidence": 0.95,
            }

    test_client, _ = client
    monkeypatch.setattr("api.routes.sms.ParserOrchestrator", CreditParser)
    resp = test_client.post(
        "/api/sms/ingest",
        headers=HEADERS,
        json=_sms_payload(message_id="credit-1", text="CREDIT 50000"),
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()["results"][0]
    assert item["status"] == "created"
    p = item["parsed"]
    assert p["direction"] == "credit"
    assert p["amount"] == "50000.00"


def test_logger_resilience_on_log_processed_raise(client, monkeypatch):
    """log_processed raising must not prevent a 200 response with created==1."""
    import api.routes.sms as sms_module

    monkeypatch.setattr(
        sms_module.receipt_logger,
        "log_processed",
        lambda **_kw: (_ for _ in ()).throw(RuntimeError("logger exploded")),
    )
    test_client, _ = client
    resp = test_client.post(
        "/api/sms/ingest",
        headers=HEADERS,
        json=_sms_payload(message_id="resilient-1", text="PAY 100"),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1


def test_logger_spy_fires_for_created_duplicate_failed(client, monkeypatch):
    """Logger functions are called once per outcome after commit."""
    import api.routes.sms as sms_module

    calls: Dict[str, int] = {"created": 0, "duplicate": 0, "failed": 0}

    def spy_processed(**_kw):
        calls["created"] += 1

    def spy_duplicate(**_kw):
        calls["duplicate"] += 1

    def spy_failed(**_kw):
        calls["failed"] += 1

    monkeypatch.setattr(sms_module.receipt_logger, "log_processed", spy_processed)
    monkeypatch.setattr(sms_module.receipt_logger, "log_duplicate", spy_duplicate)
    monkeypatch.setattr(sms_module.receipt_logger, "log_failed", spy_failed)

    test_client, _ = client

    # First message → created
    r1 = test_client.post(
        "/api/sms/ingest",
        headers=HEADERS,
        json=_sms_payload(device_id="spy-dev", message_id="spy-1", text="PAY 100"),
    )
    assert r1.json()["created"] == 1
    assert calls["created"] == 1

    # Same device_sms_id → device duplicate
    r2 = test_client.post(
        "/api/sms/ingest",
        headers=HEADERS,
        json=_sms_payload(device_id="spy-dev", message_id="spy-1", text="PAY 100"),
    )
    assert r2.json()["duplicates"] == 1
    assert calls["duplicate"] == 1

    # SKIP text → failed (skipped path)
    r3 = test_client.post(
        "/api/sms/ingest",
        headers=HEADERS,
        json=_sms_payload(device_id="spy-dev", message_id="spy-3", text="SKIP this"),
    )
    assert r3.json()["skipped"] == 1
    assert calls["failed"] == 1
