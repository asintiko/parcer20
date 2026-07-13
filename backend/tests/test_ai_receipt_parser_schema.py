from datetime import datetime
from decimal import Decimal

import pytest
import pytz
from pydantic import ValidationError

from parsers.ai_receipt_parser import ReceiptAiParser, TransactionSchema


def _payload(**overrides):
    payload = {
        "amount": "500,000",
        "currency": "UZS",
        "transaction_date_iso": "2026-07-12T10:30:00+05:00",
        "card_last_4": "***1234",
        "operator_raw": "TEST",
        "transaction_type": "DEBIT",
        "balance_after": "0.00",
        "receiver_name": None,
        "receiver_card": None,
        "confidence": 0.9,
    }
    payload.update(overrides)
    return payload


def test_ai_schema_uses_decimal_and_preserves_zero_balance():
    parsed = TransactionSchema.model_validate(_payload())
    assert parsed.amount == Decimal("500000")
    assert parsed.balance_after == Decimal("0.00")
    assert parsed.card_last_4 == "1234"

    parser = ReceiptAiParser.__new__(ReceiptAiParser)
    parser.tz = pytz.timezone("Asia/Tashkent")
    converted = parser._convert_schema(parsed)
    assert converted["balance_after"] == Decimal("0.00")
    assert converted["date_source"] == "receipt"


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": "not-an-amount"},
        {"amount": "-500.00"},
        {"transaction_date_iso": None},
        {"transaction_date_iso": "12 July sometime"},
        {"transaction_date_iso": "2026-07-12"},
        {"card_last_4": "12ab"},
        {"confidence": 2.5},
        {"currency": "INVALID"},
    ],
)
def test_ai_schema_rejects_invalid_financial_fields(overrides):
    with pytest.raises(ValidationError):
        TransactionSchema.model_validate(_payload(**overrides))


def test_source_datetime_is_explicit_and_marked():
    received_at = datetime(2026, 7, 12, 10, 30, tzinfo=pytz.timezone("Asia/Tashkent"))
    payload = _payload(transaction_date_iso=None)

    enriched, date_source = ReceiptAiParser._with_source_datetime(payload, received_at)
    parsed = TransactionSchema.model_validate(enriched)

    assert parsed.transaction_date_iso == received_at.isoformat()
    assert date_source == "source_received_at"


def test_missing_date_is_not_filled_without_source_datetime():
    payload, date_source = ReceiptAiParser._with_source_datetime(
        _payload(transaction_date_iso=None),
        None,
    )
    assert date_source == "receipt"
    with pytest.raises(ValidationError):
        TransactionSchema.model_validate(payload)
