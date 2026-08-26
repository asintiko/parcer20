import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal

import pytest

pytest.importorskip("fastapi")
fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from api.main import app
from database.connection import get_db_session
from database.models import Transaction, User
from services import description_service
from services.access_control_service import hash_password
from services.root_access_config_service import hash_password_pbkdf2, reset_root_access_cache
from fake_auth_redis import install_fake_auth_redis, issue_active_app_token


def _seed_admin(db_session, username: str = "admin") -> User:
    password_hash, salt = hash_password("Strong!123")
    user = User(
        username=username,
        password_hash=password_hash,
        salt=salt,
        role="admin",
        display_name=username,
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
    return user


def _make_tx(db_session, operator_raw: str, amount: str = "-1000.00") -> Transaction:
    tx = Transaction(
        uuid=uuid.uuid4(),
        raw_message=f"receipt {operator_raw}",
        source_type="SMS",
        source_chat_id=0,
        transaction_date=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        amount=Decimal(amount),
        currency="UZS",
        operator_raw=operator_raw,
        transaction_type="DEBIT",
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    return tx


@pytest.fixture(autouse=True)
def _clear_cache():
    description_service.invalidate_descriptions_cache()
    yield
    description_service.invalidate_descriptions_cache()


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

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = noop_lifespan

    def override_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_db
    try:
        with TestClient(app) as test_client:
            test_client.headers.update({"X-System-Access": system_token})
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.router.lifespan_context = original_lifespan
        reset_root_access_cache()


def _auth_headers(admin: User) -> dict:
    token = issue_active_app_token(admin)
    return {"Authorization": f"Bearer {token}"}


# --- service-level ---------------------------------------------------------

def test_normalize_key_and_resolve_case_whitespace(db_session):
    description_service.set_for_operator(db_session, "Korzinka Market", "Продукты")

    assert description_service.normalize_key("korzinka   market") == description_service.normalize_key("KORZINKA MARKET")
    assert description_service.resolve(db_session, "korzinka   market") == "Продукты"
    assert description_service.resolve(db_session, "  Korzinka-Market ") == "Продукты"
    assert description_service.resolve(db_session, "unknown") is None


def test_set_for_operator_create_update_clear(db_session):
    desc = description_service.set_for_operator(db_session, "Payme", "Платёж")
    assert desc is not None
    assert description_service.resolve(db_session, "PAYME") == "Платёж"

    description_service.set_for_operator(db_session, "payme", "Обновлено")
    assert description_service.resolve(db_session, "Payme") == "Обновлено"

    description_service.set_for_operator(db_session, "Payme", "")
    assert description_service.resolve(db_session, "Payme") is None


def test_shared_entity_two_operators_one_description(db_session):
    desc = description_service.set_for_operator(db_session, "OperatorA", "Общий текст")
    description_service.link_operators(
        db_session, description_id=int(desc.id), operator_raws=["OperatorB"], source="manual"
    )

    assert description_service.resolve(db_session, "OperatorA") == "Общий текст"
    assert description_service.resolve(db_session, "OperatorB") == "Общий текст"

    # Edit via either operator updates both (one shared Description row).
    description_service.set_for_operator(db_session, "operatorb", "Новый общий текст")
    assert description_service.resolve(db_session, "OperatorA") == "Новый общий текст"
    assert description_service.resolve(db_session, "OperatorB") == "Новый общий текст"


def test_resolve_batch_no_duplicates(db_session):
    description_service.set_for_operator(db_session, "Click", "Оплата")
    out = description_service.resolve_batch(db_session, ["Click", "click", "nope", None])
    assert out["Click"] == "Оплата"
    assert out["click"] == "Оплата"
    assert out["nope"] is None
    assert out[None] is None


def test_remove_for_operators_only_source_agent(db_session):
    description_service.set_for_operator(db_session, "ManualOp", "ручное", source="manual")
    description_service.set_for_operator(db_session, "AgentOp", "агентское", source="agent")

    removed = description_service.remove_for_operators(
        db_session, ["ManualOp", "AgentOp"], only_source="agent"
    )
    assert removed == 1
    assert description_service.resolve(db_session, "ManualOp") == "ручное"
    assert description_service.resolve(db_session, "AgentOp") is None


# --- transaction integration ----------------------------------------------

def test_update_transaction_description_is_retroactive(client, db_session):
    admin = _seed_admin(db_session)
    headers = _auth_headers(admin)

    tx1 = _make_tx(db_session, "Uzum Market")
    tx2 = _make_tx(db_session, "uzum   market")  # same normalized operator

    res = client.put(
        f"/api/transactions/{tx1.id}",
        headers=headers,
        json={"description": "Маркетплейс"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["transaction"]["description"] == "Маркетплейс"

    # The other transaction with the same operator gets it retroactively.
    list_res = client.get("/api/transactions", headers=headers)
    assert list_res.status_code == 200, list_res.text
    by_id = {item["id"]: item for item in list_res.json()["items"]}
    assert by_id[tx2.id]["description"] == "Маркетплейс"
    assert by_id[tx1.id]["description"] == "Маркетплейс"


def test_update_transaction_clear_description(client, db_session):
    admin = _seed_admin(db_session)
    headers = _auth_headers(admin)
    tx = _make_tx(db_session, "ClearMe")

    client.put(f"/api/transactions/{tx.id}", headers=headers, json={"description": "X"})
    assert description_service.resolve(db_session, "ClearMe") == "X"

    res = client.put(f"/api/transactions/{tx.id}", headers=headers, json={"description": ""})
    assert res.status_code == 200, res.text
    assert res.json()["transaction"]["description"] is None


# --- API CRUD --------------------------------------------------------------

def test_descriptions_crud_and_link_unlink(client, db_session):
    admin = _seed_admin(db_session)
    headers = _auth_headers(admin)

    create = client.post(
        "/api/descriptions",
        headers=headers,
        json={"text": "Кафе", "operator_raws": ["Cafe One", "Cafe Two"]},
    )
    assert create.status_code == 200, create.text
    body = create.json()
    desc_id = body["id"]
    assert body["operator_count"] == 2
    assert description_service.resolve(db_session, "cafe one") == "Кафе"

    patch = client.patch(
        f"/api/descriptions/{desc_id}", headers=headers, json={"text": "Ресторан"}
    )
    assert patch.status_code == 200, patch.text
    assert description_service.resolve(db_session, "Cafe Two") == "Ресторан"

    link = client.post(
        f"/api/descriptions/{desc_id}/operators",
        headers=headers,
        json={"operator_raws": ["Cafe Three"]},
    )
    assert link.status_code == 200, link.text
    assert link.json()["operator_count"] == 3

    unlink = client.request(
        "DELETE",
        f"/api/descriptions/{desc_id}/operators",
        headers=headers,
        json={"operator_raws": ["Cafe Three"]},
    )
    assert unlink.status_code == 200, unlink.text
    assert description_service.resolve(db_session, "Cafe Three") is None

    listing = client.get("/api/descriptions?search=Cafe", headers=headers)
    assert listing.status_code == 200
    assert any(item["id"] == desc_id for item in listing.json()["items"])

    delete = client.delete(f"/api/descriptions/{desc_id}", headers=headers)
    assert delete.status_code == 200, delete.text
    assert description_service.resolve(db_session, "Cafe One") is None


# --- AI-agent description tools --------------------------------------------

@pytest.mark.asyncio
async def test_auto_describe_operators_writes_agent_descriptions(db_session, monkeypatch):
    from services.ai_agent.tools import description_tools

    _make_tx(db_session, "Korzinka Market")
    _make_tx(db_session, "korzinka   market")  # same normalized operator
    _make_tx(db_session, "Yandex Taxi")
    # Pre-described operator must be skipped under only_missing.
    description_service.set_for_operator(db_session, "Payme", "уже описано", source="manual")
    _make_tx(db_session, "Payme")

    async def fake_snippets(operator_raw, **_kw):
        if "korzinka" in operator_raw.lower():
            return ["Korzinka — сеть супермаркетов в Узбекистане"]
        return ["Yandex Taxi — сервис заказа такси"]

    async def fake_summary(operator_raw, snippets):
        return f"описание для {operator_raw}"

    monkeypatch.setattr(description_tools, "search_operator_snippets", fake_snippets)
    monkeypatch.setattr(description_tools, "_summarize_operator", fake_summary)

    events = []
    res = await description_tools.auto_describe_operators(
        db_session,
        {"user_id": 1, "role": "admin"},
        None,
        {"limit": 10, "only_missing": True, "_progress_callback": events.append},
    )

    assert res["data"]["described"] == 2
    assert description_service.resolve(db_session, "Korzinka Market") == "описание для Korzinka Market"
    assert description_service.resolve(db_session, "Yandex Taxi") == "описание для Yandex Taxi"
    # Pre-described manual operator untouched.
    assert description_service.resolve(db_session, "Payme") == "уже описано"
    # Progress emitted a web_search step and a final done.
    assert any(e.get("step") == "web_search" for e in events)
    assert events[-1] == {"step": "done", "percent": 100, "completed": True}


@pytest.mark.asyncio
async def test_auto_describe_skips_when_no_snippets(db_session, monkeypatch):
    from services.ai_agent.tools import description_tools

    _make_tx(db_session, "Ghost Operator")

    async def empty_snippets(operator_raw, **_kw):
        return []

    monkeypatch.setattr(description_tools, "search_operator_snippets", empty_snippets)

    res = await description_tools.auto_describe_operators(
        db_session, {"user_id": 1}, None, {"limit": 5, "only_missing": True}
    )
    assert res["data"]["described"] == 0
    assert res["data"]["skipped"] == 1
    assert description_service.resolve(db_session, "Ghost Operator") is None


@pytest.mark.asyncio
async def test_rollback_operator_descriptions_only_agent(db_session):
    from services.ai_agent.tools import description_tools

    description_service.set_for_operator(db_session, "ManualOp", "ручное", source="manual")
    description_service.set_for_operator(db_session, "AgentOpA", "агент A", source="agent")
    description_service.set_for_operator(db_session, "AgentOpB", "агент B", source="agent")

    res = await description_tools.rollback_operator_descriptions(
        db_session, {"user_id": 1}, None, {"all_agent": True}
    )
    assert res["data"]["removed"] == 2
    assert description_service.resolve(db_session, "ManualOp") == "ручное"
    assert description_service.resolve(db_session, "AgentOpA") is None
    assert description_service.resolve(db_session, "AgentOpB") is None
