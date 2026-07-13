import json
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

import pytest

pytest.importorskip("fastapi")
fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient
openpyxl = pytest.importorskip("openpyxl")

from api.main import app
from api.dependencies import get_current_app_user
from database.connection import get_db_session
from database.models import HiddenBotChat, LockedPeriod, MonitoredBotChat, Transaction
from services.auth_bot_service import create_launch_session_token
from services.root_access_config_service import hash_password_pbkdf2, reset_root_access_cache


def _seed_tx(
    db_session,
    *,
    idx: int,
    day: int,
    amount: str,
    currency: str = "UZS",
    operator: str = "Operator",
    app_name: str = "App",
    source_chat_id: int = 100,
    source_type: str = "AUTO",
    balance_after: str | None = None,
):
    tx = Transaction(
        raw_message=f"export-tx-{idx}",
        source_type=source_type,
        source_chat_id=source_chat_id,
        source_message_id=idx,
        transaction_date=datetime(2026, 1, day, 10, 0, 0),
        amount=Decimal(amount),
        balance_after=Decimal(balance_after) if balance_after is not None else None,
        currency=currency,
        card_last_4="1111",
        operator_raw=operator,
        application_mapped=app_name,
        transaction_type="DEBIT",
        parsing_method="REGEX_SMS",
        fingerprint=f"export-fp-{idx}",
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    return tx


def _seed_monitored_chat(db_session, *, chat_id: int, title: str, chat_type: str = "supergroup"):
    row = MonitoredBotChat(
        chat_id=chat_id,
        enabled=True,
        last_processed_message_id=0,
        chat_title=title,
        chat_type=chat_type,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


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
    reset_root_access_cache()

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = noop_lifespan

    def override_db():
        yield db_session

    async def override_current_app_user():
        return {
            "id": 1,
            "user_id": 1,
            "username": "test-admin",
            "display_name": "Test Admin",
            "role": "admin",
            "allowed_tabs": ["dashboard"],
            "allowed_folders": [],
            "forbidden_periods": [],
            "allowed_sources": [],
            "can_toggle_sources": True,
            "permissions_version": 1,
            "session_ttl_days": 7,
        }

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


def _load_sheet_rows(content: bytes):
    wb = openpyxl.load_workbook(filename=BytesIO(content), data_only=True)
    sheet = wb.active
    rows = list(sheet.iter_rows(values_only=True))
    return rows, sheet


def test_transactions_export_returns_xlsx_and_applies_filters(client, db_session):
    _seed_tx(db_session, idx=1, day=10, amount="-100.00", currency="UZS", operator="Korzinka", app_name="Payme")
    _seed_tx(db_session, idx=2, day=11, amount="-200.00", currency="USD", operator="NBU", app_name="Click")

    res = client.get("/api/transactions/export", params={"currency": "USD"})
    assert res.status_code == 200, res.text
    assert "spreadsheetml.sheet" in res.headers.get("content-type", "")
    assert res.content[:2] == b"PK"

    rows, sheet = _load_sheet_rows(res.content)
    assert rows[0][0] == "№"
    assert rows[0][1] == "№ опер."
    assert rows[0][2] == "Дата и Время"
    assert rows[0][10] == "Сумма"
    assert sheet.auto_filter.ref == "A1:Q1"
    # header + one filtered row
    assert len(rows) == 2
    assert rows[1][15] == "USD"


def test_transactions_export_matches_list_under_locked_periods(client, db_session):
    keep_tx = _seed_tx(db_session, idx=10, day=10, amount="-100.00")
    _seed_tx(db_session, idx=11, day=20, amount="-500.00")

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
    assert list_res.json()["total"] == 1
    assert list_res.json()["items"][0]["id"] == keep_tx.id

    export_res = client.get(
        "/api/transactions/export",
        params={
            "date_from": "2026-01-01T00:00:00",
            "date_to": "2026-01-31T23:59:59",
        },
    )
    assert export_res.status_code == 200, export_res.text
    rows, sheet = _load_sheet_rows(export_res.content)
    assert sheet.auto_filter.ref == "A1:Q1"
    assert len(rows) == 2  # header + 1 row


def test_transactions_export_enforces_row_limit(client, db_session, monkeypatch):
    monkeypatch.setenv("TRANSACTIONS_EXPORT_MAX_ROWS", "1")
    _seed_tx(db_session, idx=21, day=5, amount="-10.00")
    _seed_tx(db_session, idx=22, day=6, amount="-11.00")

    res = client.get("/api/transactions/export")
    assert res.status_code == 413, res.text
    detail = res.json()["detail"]
    assert detail["error"] == "export_limit_exceeded"
    assert detail["limit"] == 1
    assert detail["total"] == 2


def test_transactions_export_empty_dataset_has_only_header(client):
    res = client.get("/api/transactions/export")
    assert res.status_code == 200, res.text
    rows, sheet = _load_sheet_rows(res.content)
    assert len(rows) == 1
    assert sheet.auto_filter.ref == "A1:Q1"
    assert rows[0] == tuple(
        [
            "№",
            "№ опер.",
            "Дата и Время",
            "Дата",
            "Время",
            "День",
            "Оператор/Продавец",
            "Приложение",
            "Получатель",
            "Карта получателя",
            "Сумма",
            "Остаток",
            "ПК",
            "П2П",
            "Тип",
            "Валюта",
            "Источник",
        ]
    )


def test_transactions_export_respects_columns_order_and_whitelist(client, db_session):
    _seed_tx(db_session, idx=31, day=8, amount="-321.00", currency="UZS")

    res = client.get(
        "/api/transactions/export",
        params=[
            ("columns", "currency"),
            ("columns", "amount"),
            ("columns", "operation_number"),
            ("columns", "row_number"),
            ("columns", "unknown"),
            ("columns", "amount"),
        ],
    )
    assert res.status_code == 200, res.text
    rows, sheet = _load_sheet_rows(res.content)
    assert rows[0] == ("Валюта", "Сумма", "№ опер.", "№")
    assert rows[1][0] == "UZS"
    assert rows[1][2] == 1
    assert rows[1][3] == 1
    assert sheet.auto_filter.ref == "A1:D1"


def test_transactions_export_invalid_columns_fallbacks_to_default(client, db_session):
    _seed_tx(db_session, idx=41, day=9, amount="-111.00")
    res = client.get("/api/transactions/export", params=[("columns", "bad"), ("columns", "also_bad")])
    assert res.status_code == 200, res.text
    rows, sheet = _load_sheet_rows(res.content)
    assert rows[0][0] == "№"
    assert rows[0][16] == "Источник"
    assert sheet.auto_filter.ref == "A1:Q1"


def test_transactions_list_filters_by_source_chat_ids_and_returns_chat_title(client, db_session):
    _seed_monitored_chat(db_session, chat_id=-100100, title="UBpay_demo", chat_type="supergroup")
    _seed_monitored_chat(db_session, chat_id=200, title="NBU Card", chat_type="bot")
    _seed_tx(
        db_session,
        idx=51,
        day=12,
        amount="-100.00",
        operator="UB",
        app_name="UB App",
        source_chat_id=-100100,
    )
    tx_other = Transaction(
        raw_message="export-tx-52",
        source_type="AUTO",
        source_chat_id=200,
        source_message_id=52,
        transaction_date=datetime(2026, 1, 12, 11, 0, 0),
        amount=Decimal("-200.00"),
        currency="UZS",
        card_last_4="1111",
        operator_raw="NBU",
        application_mapped="NBU App",
        transaction_type="DEBIT",
        parsing_method="REGEX_SMS",
        fingerprint="export-fp-52",
    )
    db_session.add(tx_other)
    db_session.commit()

    res = client.get("/api/transactions/", params={"page": 1, "page_size": 50, "source_chat_ids": "-100100"})
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["total"] == 1
    assert payload["items"][0]["source_chat_id"] == -100100
    assert payload["items"][0]["source_chat_title"] == "UBpay_demo"
    assert payload["items"][0]["source_display"] == "UBpay_demo"
    assert payload["items"][0]["source_origin_type"] == "supergroup"


def test_transactions_init_returns_telegram_sources(client, db_session):
    _seed_monitored_chat(db_session, chat_id=300, title="HUMO Card", chat_type="bot")
    _seed_monitored_chat(db_session, chat_id=-400, title="UBpay_demo", chat_type="supergroup")
    _seed_tx(db_session, idx=61, day=15, amount="-50.00", operator="HUMO", source_chat_id=300)
    tx_group = Transaction(
        raw_message="export-tx-62",
        source_type="AUTO",
        source_chat_id=-400,
        source_message_id=62,
        transaction_date=datetime(2026, 1, 15, 10, 30, 0),
        amount=Decimal("-60.00"),
        currency="UZS",
        card_last_4="2222",
        operator_raw="UBPAY",
        application_mapped="UB",
        transaction_type="DEBIT",
        parsing_method="REGEX_SMS",
        fingerprint="export-fp-62",
    )
    db_session.add(tx_group)
    db_session.commit()

    res = client.get("/api/transactions/init")
    assert res.status_code == 200, res.text
    payload = res.json()
    titles = {item["title"]: item for item in payload["telegram_sources"]}
    assert "HUMO Card" in titles
    assert "UBpay_demo" in titles
    assert titles["HUMO Card"]["chat_type"] == "bot"
    assert titles["UBpay_demo"]["chat_type"] == "supergroup"


def test_transactions_list_uses_hidden_chat_title_snapshot_when_monitored_row_missing(client, db_session):
    db_session.add(HiddenBotChat(chat_id=-500, title_snapshot="uzumdemo"))
    db_session.commit()
    _seed_tx(db_session, idx=71, day=18, amount="-77.00", source_chat_id=-500)

    res = client.get("/api/transactions/", params={"page": 1, "page_size": 20, "source_chat_ids": "-500"})
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["total"] == 1
    assert payload["items"][0]["source_chat_title"] == "uzumdemo"
    assert payload["items"][0]["source_display"] == "uzumdemo"


def test_transactions_list_supports_source_channel_and_extended_sort_fields(client, db_session):
    _seed_tx(db_session, idx=81, day=10, amount="-500.00", balance_after="900.00", operator="Zeta", source_type="AUTO")
    _seed_tx(db_session, idx=82, day=11, amount="-100.00", balance_after="100.00", operator="Alpha", source_type="SMS", source_chat_id=0)
    _seed_tx(db_session, idx=83, day=12, amount="-300.00", balance_after="400.00", operator="Beta", source_type="MANUAL", source_chat_id=0)

    telegram_res = client.get("/api/transactions/", params={"page": 1, "page_size": 20, "source_channel": "TELEGRAM"})
    assert telegram_res.status_code == 200, telegram_res.text
    telegram_items = telegram_res.json()["items"]
    assert len(telegram_items) == 1
    assert telegram_items[0]["operator_raw"] == "Zeta"

    amount_res = client.get("/api/transactions/", params={"page": 1, "page_size": 20, "sort_by": "amount", "sort_dir": "asc"})
    assert amount_res.status_code == 200, amount_res.text
    assert [item["amount"] for item in amount_res.json()["items"]] == ["100.00", "300.00", "500.00"]

    balance_res = client.get("/api/transactions/", params={"page": 1, "page_size": 20, "sort_by": "balance_after", "sort_dir": "desc"})
    assert balance_res.status_code == 200, balance_res.text
    assert [item["balance_after"] for item in balance_res.json()["items"]] == ["900.00", "400.00", "100.00"]

    operator_res = client.get("/api/transactions/", params={"page": 1, "page_size": 20, "sort_by": "operator_raw", "sort_dir": "asc"})
    assert operator_res.status_code == 200, operator_res.text
    assert [item["operator_raw"] for item in operator_res.json()["items"]] == ["Alpha", "Beta", "Zeta"]
