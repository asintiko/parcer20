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
from services.auth_service import create_app_user_token
from services.root_access_config_service import hash_password_pbkdf2, reset_root_access_cache


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

    app.dependency_overrides[get_db_session] = override_db
    try:
        with TestClient(app) as test_client:
            test_client.headers.update({"X-System-Access": system_token})
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.router.lifespan_context = original_lifespan
        reset_root_access_cache()


def test_periods_crud(client, db_session):
    admin = _seed_admin(db_session)
    token = create_app_user_token(
        user_id=int(admin.id),
        username=admin.username,
        role=admin.role,
        permissions_version=int(admin.permissions_version or 1),
        display_name=admin.display_name,
    )
    headers = {"Authorization": f"Bearer {token}"}

    create_res = client.post(
        "/api/periods",
        headers=headers,
        json={"date_from": "2026-01-01", "date_to": "2026-01-31", "reason": "audit"},
    )
    assert create_res.status_code == 201, create_res.text
    period_id = int(create_res.json()["id"])

    list_res = client.get("/api/periods?active_only=false", headers=headers)
    assert list_res.status_code == 200
    assert any(int(item["id"]) == period_id for item in list_res.json())

    patch_res = client.patch(
        f"/api/periods/{period_id}",
        headers=headers,
        json={"reason": "updated"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["reason"] == "updated"

    delete_res = client.delete(f"/api/periods/{period_id}", headers=headers)
    assert delete_res.status_code == 200
    assert delete_res.json()["is_active"] is False
