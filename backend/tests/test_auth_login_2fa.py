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


def _seed_2fa_user(db_session, username: str = "boss") -> User:
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
        force_2fa=True,
        totp_secret="JBSWY3DPEHPK3PXP",
        totp_enabled=True,
        backup_codes=json.dumps(["A1B2C3D4"], ensure_ascii=False),
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


def test_login_requires_2fa_and_accepts_backup_code(client, db_session):
    _seed_2fa_user(db_session, username="boss")

    login_res = client.post("/api/auth/login", json={"username": "boss", "password": "Strong!123"})
    assert login_res.status_code == 200, login_res.text
    challenge = login_res.json()
    assert challenge["ok"] is False
    assert challenge["requires_2fa"] is True
    temp_token = challenge.get("temp_token")
    assert temp_token

    verify_res = client.post(
        "/api/auth/login/2fa",
        json={"temp_token": temp_token, "code": "A1B2C3D4"},
    )
    assert verify_res.status_code == 200, verify_res.text
    final_payload = verify_res.json()
    assert final_payload["ok"] is True
    assert final_payload.get("token")
