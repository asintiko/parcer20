from datetime import datetime
from decimal import Decimal

import pytest

pytest.importorskip("fastapi")

from database.models import Transaction
from services.receipt_processor import _merge_duplicate_transaction


def _build_tx(
    *,
    transaction_date: datetime,
    operator_raw: str = "Unknown",
    application_mapped=None,
    balance_after=None,
    receiver_name=None,
    receiver_card=None,
    parsing_method="REGEX_SMS",
    parsing_confidence=0.8,
):
    return Transaction(
        raw_message="short",
        source_type="AUTO",
        source_chat_id=1,
        source_message_id=1,
        transaction_date=transaction_date,
        amount=Decimal("-100000.00"),
        currency="UZS",
        card_last_4="4483",
        operator_raw=operator_raw,
        application_mapped=application_mapped,
        transaction_type="DEBIT",
        balance_after=balance_after,
        receiver_name=receiver_name,
        receiver_card=receiver_card,
        is_p2p=False,
        parsing_method=parsing_method,
        parsing_confidence=parsing_confidence,
        is_gpt_parsed=False,
        fingerprint="fp",
    )


def test_merge_fills_missing_fields_even_if_candidate_not_globally_better():
    existing = _build_tx(
        transaction_date=datetime(2026, 1, 31, 11, 12, 0),
        operator_raw="Unknown",
        parsing_method="REGEX_HUMO",
        parsing_confidence=0.95,
    )

    merged = _merge_duplicate_transaction(
        existing,
        candidate_transaction_date=datetime(2026, 1, 31, 11, 12, 11),
        candidate_operator_raw="Uzum Bank",
        candidate_application_mapped="Uzum",
        candidate_balance_after=Decimal("5000000.00"),
        candidate_receiver_name="SVYATOSLAV LI",
        candidate_receiver_card="491699******1116",
        candidate_raw_message="very long raw message with extra receipt details",
        candidate_is_p2p=True,
        candidate_parsing_method="REGEX_TRANSFER",
        candidate_parsing_confidence=0.75,
        candidate_is_gpt=False,
    )

    assert merged is True
    assert existing.operator_raw == "Uzum Bank"
    assert existing.application_mapped == "Uzum"
    assert existing.balance_after == Decimal("5000000.00")
    assert existing.receiver_name == "SVYATOSLAV LI"
    assert existing.receiver_card == "491699******1116"
    assert existing.is_p2p is True
    assert existing.parsing_confidence == 0.95


def test_merge_upgrades_seconds_for_same_minute():
    existing = _build_tx(
        transaction_date=datetime(2026, 1, 31, 11, 12, 0),
        operator_raw="Uzum Bank",
        parsing_method="REGEX_SMS",
        parsing_confidence=0.8,
    )

    merged = _merge_duplicate_transaction(
        existing,
        candidate_transaction_date=datetime(2026, 1, 31, 11, 12, 51),
        candidate_operator_raw="Uzum Bank",
        candidate_application_mapped="Uzum",
        candidate_balance_after=None,
        candidate_receiver_name=None,
        candidate_receiver_card=None,
        candidate_raw_message="details",
        candidate_is_p2p=False,
        candidate_parsing_method="REGEX_TRANSFER",
        candidate_parsing_confidence=0.82,
        candidate_is_gpt=False,
    )

    assert merged is True
    assert existing.transaction_date.second == 51


def test_merge_prefers_higher_quality_method_on_tie_confidence():
    existing = _build_tx(
        transaction_date=datetime(2026, 1, 31, 11, 12, 0),
        operator_raw="Unknown",
        parsing_method="REGEX_SMS",
        parsing_confidence=0.8,
    )

    merged = _merge_duplicate_transaction(
        existing,
        candidate_transaction_date=datetime(2026, 1, 31, 11, 12, 0),
        candidate_operator_raw="PAK VALENTINA PETROVNA",
        candidate_application_mapped=None,
        candidate_balance_after=None,
        candidate_receiver_name="SVYATOSLAV LI",
        candidate_receiver_card="491699******1116",
        candidate_raw_message="longer message with sender receiver transaction id",
        candidate_is_p2p=True,
        candidate_parsing_method="REGEX_TRANSFER",
        candidate_parsing_confidence=0.8,
        candidate_is_gpt=False,
    )

    assert merged is True
    assert existing.parsing_method == "REGEX_TRANSFER"
    assert existing.operator_raw == "PAK VALENTINA PETROVNA"
    assert existing.receiver_name == "SVYATOSLAV LI"
    assert existing.is_p2p is True


def test_merge_upgrades_source_type_when_candidate_is_better():
    existing = _build_tx(
        transaction_date=datetime(2026, 1, 31, 11, 12, 0),
        operator_raw="Unknown",
        parsing_method="REGEX_SMS",
        parsing_confidence=0.65,
    )
    existing.source_type = "SMS"

    merged = _merge_duplicate_transaction(
        existing,
        candidate_transaction_date=datetime(2026, 1, 31, 11, 12, 31),
        candidate_operator_raw="UZUM MARKET",
        candidate_application_mapped="Uzum",
        candidate_balance_after=Decimal("1000000.00"),
        candidate_receiver_name=None,
        candidate_receiver_card=None,
        candidate_raw_message="long richer auto receipt message",
        candidate_is_p2p=False,
        candidate_parsing_method="REGEX_TRANSFER",
        candidate_parsing_confidence=0.91,
        candidate_is_gpt=False,
        candidate_source_type="AUTO",
    )

    assert merged is True
    assert existing.source_type == "AUTO"
