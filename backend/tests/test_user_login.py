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
from services.auth_service import create_app_user_token
from services.auth_service import verify_jwt_token
from services.root_access_config_service import hash_password_pbkdf2, reset_root_access_cache
from fake_auth_redis import install_fake_auth_redis


def _seed_user(db_session, *, username: str, password: str, role: str = "admin") -> User:
    password_hash, salt = hash_password(password)
    user = User(
        username=username,
        password_hash=password_hash,
        salt=salt,
        role=role,
        display_name=username,
        allowed_tabs='["dashboard","reference","automation","userbot","logs","admin"]' if role == "admin" else '["dashboard"]',
        allowed_folders='[]',
        forbidden_periods='[]',
        allowed_sources='[]',
        can_toggle_sources=(role == "admin"),
        permissions_version=1,
        is_active=True,
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
    monkeypatch.setenv("LAUNCH_GATE_ENABLED", "false")
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


def test_user_login_success(client, db_session):
    _seed_user(db_session, username="boss", password="secret", role="admin")

    res = client.post("/api/auth/login", json={"username": "boss", "password": "secret"})
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["ok"] is True
    assert payload.get("token")
    assert payload["user"]["role"] == "admin"
    assert "dashboard" in payload["user"]["allowed_tabs"]


def test_user_login_lockout(client, db_session):
    _seed_user(db_session, username="operator", password="good", role="operator")

    for _ in range(5):
        res = client.post("/api/auth/login", json={"username": "operator", "password": "bad"})

    assert res.status_code in (401, 423)
    body = res.json()
    assert body["error"] in ("invalid_credentials", "locked")


def test_permissions_outdated_invalidates_old_token(client, db_session):
    user = _seed_user(db_session, username="u1", password="pw", role="admin")
    token = create_app_user_token(
        user_id=int(user.id),
        username=user.username,
        role=user.role,
        permissions_version=int(user.permissions_version),
        display_name=user.display_name,
    )

    user.permissions_version = int(user.permissions_version) + 1
    db_session.commit()

    res = client.get("/api/auth/verify", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    assert "permissions_outdated" in res.text


def test_revoked_session_invalidates_verify(client, db_session):
    user = _seed_user(db_session, username="revoked-admin", password="pw", role="admin")
    token = create_app_user_token(
        user_id=int(user.id),
        username=user.username,
        role=user.role,
        permissions_version=int(user.permissions_version),
        display_name=user.display_name,
    )
    decoded = verify_jwt_token(token)
    assert decoded and decoded.get("sid")

    asyncio.run(
        register_active_session(
            token_payload=decoded,
            token_kind="app_user",
            user_id=int(user.id),
            ip_address="127.0.0.1",
            subject=user.username,
        )
    )
    ok, _ = asyncio.run(revoke_active_session(str(decoded["sid"])))
    assert ok is True

    res = client.get("/api/auth/verify", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401
    assert "session_revoked" in res.text
