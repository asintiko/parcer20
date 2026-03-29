import pytest

pytest.importorskip("fastapi")

from api.routes.transactions import detect_source_channel, normalize_source_type


def test_normalize_source_type_supports_sms():
    assert normalize_source_type("sms") == "SMS"
    assert normalize_source_type("AUTO") == "AUTO"
    assert normalize_source_type("manual") == "MANUAL"


def test_detect_source_channel_prefers_explicit_sms_over_emoji():
    assert detect_source_channel("SMS", "➖ Оплата 10 000 UZS") == "SMS"


def test_detect_source_channel_prefers_auto_to_telegram():
    assert detect_source_channel("AUTO", "Обычный текст без эмодзи") == "TELEGRAM"


def test_detect_source_channel_prefers_manual():
    assert detect_source_channel("MANUAL", "➕ Текст с эмодзи") == "MANUAL"


def test_detect_source_channel_uses_legacy_emoji_heuristic_only_without_source_type():
    assert detect_source_channel(None, "➕ Оплата 10 000 UZS") == "TELEGRAM"
    assert detect_source_channel(None, "Plain legacy text") == "SMS"
