import json
from contextlib import asynccontextmanager

import pytest

pytest.importorskip("fastapi")
fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from api.main import app
from database.connection import get_db_session
from database.models import AccessScope
from services.access_control_service import hash_password, years_to_json
from services.auth_bot_service import create_launch_session_token
from services.root_access_config_service import hash_password_pbkdf2, reset_root_access_cache


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

    otp_store = {}

    class FakeOTPManager:
        async def check_rate_limit(self, actor_key):  # noqa: ARG002
            return True, 0

        async def generate_code(self, purpose, subject, context):  # noqa: ARG002
            otp_store[(purpose, subject)] = "123456"
            return {"code": "123456", "expires_in": 120, "code_length": 6}

        async def verify_code(self, purpose, subject, input_code):
            expected = otp_store.get((purpose, subject))
            if not expected:
                return False, {"error": "code_expired"}
            if input_code != expected:
                return False, {"error": "invalid_code", "attempts_left": 2}
            return True, {"ok": True}

    async def fake_notify_admins(message_text):  # noqa: ARG001
        return None

    monkeypatch.setattr("api.routes.security.OTPManager", FakeOTPManager)
    monkeypatch.setattr("api.routes.security._notify_admins", fake_notify_admins)

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = noop_lifespan

    def override_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_db
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
        app.router.lifespan_context = original_lifespan
        reset_root_access_cache()


def _add_scope(db_session) -> AccessScope:
    pwd_hash, salt = hash_password("unused-password")
    scope = AccessScope(
        name="OTP Scope",
        password_hash=pwd_hash,
        salt=salt,
        years_json=years_to_json([2026]),
        allow_transactions=True,
        allow_sources=False,
        auth_method="otp",
        is_active=True,
    )
    db_session.add(scope)
    db_session.commit()
    db_session.refresh(scope)
    return scope


def test_scope_otp_request_and_verify_flow(client, db_session):
    scope = _add_scope(db_session)

    req = client.post(f"/api/security/scope/{scope.id}/request-code")
    assert req.status_code == 200, req.text
    req_body = req.json()
    assert req_body["status"] == "code_sent"
    assert req_body["expires_in"] == 120

    bad_verify = client.post(f"/api/security/scope/{scope.id}/verify-code", json={"code": "000000"})
    assert bad_verify.status_code == 401
    assert bad_verify.json()["detail"]["error"] == "invalid_code"

    ok_verify = client.post(f"/api/security/scope/{scope.id}/verify-code", json={"code": "123456"})
    assert ok_verify.status_code == 200, ok_verify.text
    payload = ok_verify.json()
    assert payload["token"]
    assert payload["scope"]["id"] == scope.id
