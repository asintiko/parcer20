import json
import asyncio
from contextlib import asynccontextmanager

import pytest

pytest.importorskip("fastapi")
fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from api.main import app
from database.connection import get_db_session
from database.models import User
from services.access_control_service import hash_password
from services.auth_bot_service import register_active_session, revoke_active_session
from services.auth_service import verify_jwt_token
from services.root_access_config_service import hash_password_pbkdf2, reset_root_access_cache
from fake_auth_redis import install_fake_auth_redis


def _seed_user(db_session, username: str = "operator") -> User:
    password_hash, salt = hash_password("Strong!123")
    user = User(
        username=username,
        password_hash=password_hash,
        salt=salt,
        role="operator",
        display_name=username,
        allowed_tabs='["dashboard"]',
        allowed_folders="[]",
        forbidden_periods="[]",
        allowed_sources="[]",
        can_toggle_sources=False,
        permissions_version=1,
        is_active=True,
        force_2fa=False,
        totp_enabled=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


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


def test_refresh_token_rotation(client, db_session):
    _seed_user(db_session, username="operator")

    login_res = client.post("/api/auth/login", json={"username": "operator", "password": "Strong!123"})
    assert login_res.status_code == 200, login_res.text
    login_payload = login_res.json()
    assert login_payload["ok"] is True
    old_refresh = login_payload.get("refresh_token")
    assert old_refresh

    refresh_res = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert refresh_res.status_code == 200, refresh_res.text
    refresh_payload = refresh_res.json()
    assert refresh_payload["ok"] is True
    new_refresh = refresh_payload.get("refresh_token")
    assert new_refresh
    assert new_refresh != old_refresh

    old_again = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert old_again.status_code == 401


def test_refresh_rejected_for_revoked_session(client, db_session):
    _seed_user(db_session, username="revoked-operator")

    login_res = client.post("/api/auth/login", json={"username": "revoked-operator", "password": "Strong!123"})
    assert login_res.status_code == 200, login_res.text
    login_payload = login_res.json()
    access_token = login_payload["token"]
    refresh_token = login_payload["refresh_token"]

    decoded_access = verify_jwt_token(access_token)
    assert decoded_access and decoded_access.get("sid")

    asyncio.run(
        register_active_session(
            token_payload=decoded_access,
            token_kind="app_user",
            user_id=int(decoded_access["user_id"]),
            ip_address="127.0.0.1",
            subject="revoked-operator",
        )
    )
    ok, _ = asyncio.run(revoke_active_session(str(decoded_access["sid"])))
    assert ok is True

    refresh_res = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_res.status_code == 401
    assert "session_revoked" in refresh_res.text
