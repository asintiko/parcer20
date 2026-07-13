import asyncio
from datetime import datetime

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.routes import sms


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/sms/ingest", "headers": []})


def test_device_key_config_supports_current_and_previous_keys(monkeypatch):
    sms._parse_mobile_device_keys.cache_clear()
    monkeypatch.setenv(
        "MOBILE_DEVICE_KEYS_JSON",
        '{"android-a":{"current":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        '"previous":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}}',
    )

    assert asyncio.run(
        sms._require_mobile_device("android-a", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    ) == "android-a"
    assert asyncio.run(
        sms._require_mobile_device("android-a", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    ) == "android-a"


def test_fleet_wide_key_is_not_standalone_authority(monkeypatch):
    sms._parse_mobile_device_keys.cache_clear()
    monkeypatch.setenv("MOBILE_SMS_INGEST_KEY", "legacy-fleet-key-that-must-not-authorize")
    monkeypatch.setenv(
        "MOBILE_DEVICE_KEYS_JSON",
        '{"android-a":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}',
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(sms._require_mobile_device("android-a", "legacy-fleet-key-that-must-not-authorize"))
    assert exc.value.status_code == 403


def test_missing_or_invalid_device_config_fails_closed(monkeypatch):
    sms._parse_mobile_device_keys.cache_clear()
    monkeypatch.delenv("MOBILE_DEVICE_KEYS_JSON", raising=False)
    with pytest.raises(HTTPException) as missing:
        asyncio.run(sms._require_mobile_device("android-a", "a" * 32))
    assert missing.value.status_code == 503

    sms._parse_mobile_device_keys.cache_clear()
    monkeypatch.setenv("MOBILE_DEVICE_KEYS_JSON", "not-json")
    with pytest.raises(HTTPException) as invalid:
        asyncio.run(sms._require_mobile_device("android-a", "a" * 32))
    assert invalid.value.status_code == 503


def test_ingest_rejects_body_header_device_mismatch():
    payload = sms.SmsIngestRequest(
        device_id="android-body",
        messages=[
            sms.SmsMessage(
                device_sms_id="1",
                sender="BANK",
                text="payment 1000 UZS",
                received_at=datetime(2026, 1, 1),
            )
        ],
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            sms.ingest_sms(
                payload=payload,
                request=_request(),
                authenticated_device_id="android-header",
                db=None,
            )
        )
    assert exc.value.status_code == 403


def test_mobile_sources_never_disclose_telegram_metadata():
    response = asyncio.run(sms.sms_sources(_authenticated_device_id="android-a"))
    assert response.items == []
