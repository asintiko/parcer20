import json
from contextlib import asynccontextmanager

import pytest

pytest.importorskip("fastapi")
fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from api.main import app
from api.routes.telegram_client import tdlib_manager_dep
from database.connection import get_db_session
from services.auth_bot_service import create_launch_session_token
from services.root_access_config_service import hash_password_pbkdf2, reset_root_access_cache
from fake_auth_redis import (
    install_fake_auth_redis,
    issue_active_app_token,
    register_launch_session,
    seed_test_user,
)


class FakeTDLibManager:
    async def get_messages(self, chat_id: int, limit: int = 50, from_message_id: int = 0, fetch_all: bool = False, **kwargs):  # noqa: ARG002
        return {
            "total": 1,
            "items": [
                {
                    "id": 99,
                    "date": 1_735_689_600,
                    "is_outgoing": False,
                    "text": "hello",
                    "chat_id": chat_id,
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
    install_fake_auth_redis(monkeypatch)
    reset_root_access_cache()

    app_user_token = issue_active_app_token(
        seed_test_user(db_session, username="chat-password-test-admin")
    )

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = noop_lifespan

    def override_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[tdlib_manager_dep] = lambda: FakeTDLibManager()

    try:
        with TestClient(app) as test_client:
            test_client.headers.update(
                {
                    "X-System-Access": system_token,
                    "X-Launch-Session": register_launch_session(
                        create_launch_session_token(ip_address="127.0.0.1")
                    ),
                    "Authorization": f"Bearer {app_user_token}",
                }
            )
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(tdlib_manager_dep, None)
        app.router.lifespan_context = original_lifespan
        reset_root_access_cache()


def test_chat_password_protects_messages_endpoint(client):
    chat_id = 5005

    set_res = client.post(f"/api/tg/chats/{chat_id}/password", json={"password": "secret"})
    assert set_res.status_code == 200, set_res.text
    assert set_res.json()["protected"] is True

    status_res = client.get(f"/api/tg/chats/{chat_id}/password/status")
    assert status_res.status_code == 200
    assert status_res.json()["protected"] is True

    blocked = client.get(f"/api/tg/chats/{chat_id}/messages", params={"limit": 20})
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["error"] == "chat_locked"

    verify_res = client.post(f"/api/tg/chats/{chat_id}/password/verify", json={"password": "secret"})
    assert verify_res.status_code == 200, verify_res.text
    token = verify_res.json().get("session_token")
    assert token

    allowed = client.get(
        f"/api/tg/chats/{chat_id}/messages",
        params={"limit": 20},
        headers={"X-Chat-Access": token},
    )
    assert allowed.status_code == 200, allowed.text
    body = allowed.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == 99
