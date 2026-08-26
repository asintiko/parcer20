import json
from contextlib import asynccontextmanager

import pytest

pytest.importorskip("fastapi")
fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from api.main import app
from database.connection import get_db_session
from database.models import User
from services.access_control_service import hash_password
from services.root_access_config_service import hash_password_pbkdf2, reset_root_access_cache
from fake_auth_redis import install_fake_auth_redis, issue_active_app_token


def _seed_user(db_session, *, username: str, role: str) -> User:
    password_hash, salt = hash_password("secret")
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


def _make_token(user: User) -> str:
    return issue_active_app_token(user)


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


def test_admin_can_manage_users(client, db_session):
    admin = _seed_user(db_session, username="admin", role="admin")
    admin_token = _make_token(admin)

    create_res = client.post(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "username": "operator1",
            "password": "Strong!123",
            "role": "operator",
            "display_name": "Operator 1",
            "allowed_tabs": ["dashboard", "userbot"],
            "allowed_folders": [1, 2],
            "forbidden_periods": [{"from": "2025-01-01", "to": "2025-01-31"}],
            "allowed_sources": [12345],
            "can_toggle_sources": False,
            "is_active": True,
        },
    )
    assert create_res.status_code == 200, create_res.text
    user_id = create_res.json()["id"]

    patch_res = client.patch(
        f"/api/admin/users/{user_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"allowed_tabs": ["dashboard", "reference"], "can_toggle_sources": True},
    )
    assert patch_res.status_code == 200, patch_res.text
    assert set(patch_res.json()["allowed_tabs"]) >= {"dashboard", "reference"}

    list_res = client.get("/api/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert list_res.status_code == 200
    assert any(row["username"] == "operator1" for row in list_res.json())


def test_non_admin_cannot_manage_users(client, db_session):
    operator = _seed_user(db_session, username="op", role="operator")
    operator_token = _make_token(operator)

    res = client.get("/api/admin/users", headers={"Authorization": f"Bearer {operator_token}"})
    assert res.status_code == 403
    assert "admin_only" in res.text
