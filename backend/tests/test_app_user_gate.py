"""Tests for the strict app-user token-purpose gate."""
import asyncio

import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException

from api.dependencies import get_current_app_user


def _run(current_user):
    return asyncio.run(get_current_app_user(current_user=current_user))


def test_user_with_role_passes_through_unchanged():
    user = {
        "role": "admin",
        "user_id": 1,
        "allowed_tabs": ["dashboard"],
        "token_kind": "app_user",
    }
    assert _run(user) is user


def test_qr_legacy_roleless_is_rejected():
    user = {"token_kind": "qr_legacy", "user_id": 7, "phone": "+99890"}
    with pytest.raises(HTTPException) as exc:
        _run(user)
    assert exc.value.status_code == 401


def test_qr_user_roleless_is_rejected():
    user = {"token_kind": "qr_user", "user_id": 8}
    with pytest.raises(HTTPException) as exc:
        _run(user)
    assert exc.value.status_code == 401


def test_legacy_kind_raw_payload_is_rejected():
    user = {"kind": "legacy", "user_id": 9}
    with pytest.raises(HTTPException) as exc:
        _run(user)
    assert exc.value.status_code == 401


def test_roleless_app_user_is_rejected():
    user = {"token_kind": "app_user", "user_id": 3}
    with pytest.raises(HTTPException) as exc:
        _run(user)
    assert exc.value.status_code == 401


def test_roleless_refresh_token_is_rejected():
    # The exploit: a refresh_token used as a bearer is roleless and was escalated.
    user = {"kind": "refresh", "user_id": 3, "sub": 3}
    with pytest.raises(HTTPException) as exc:
        _run(user)
    assert exc.value.status_code == 401


def test_roleless_unknown_kind_is_rejected():
    user = {"user_id": 3}
    with pytest.raises(HTTPException) as exc:
        _run(user)
    assert exc.value.status_code == 401
