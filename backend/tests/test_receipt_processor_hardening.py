import asyncio
from datetime import datetime
from decimal import Decimal

from database.models import AccessAuditLog, Transaction
from services import receipt_processor


class _Manager:
    def __init__(self, text="receipt"):
        self.text = text

    async def get_message(self, chat_id, message_id):  # noqa: ARG002
        return {"text": self.text, "date": 1_768_214_400}


def _parsed(amount="100000.00", operator="PAYME"):
    return {
        "transaction_date": datetime(2026, 1, 12, 10, 0),
        "amount": Decimal(amount),
        "currency": "UZS",
        "card_last_4": "1234",
        "operator_raw": operator,
        "transaction_type": "DEBIT",
        "parsing_method": "REGEX_SMS",
        "parsing_confidence": 0.95,
    }


def _existing(chat_id, message_id, *, operator="PAYME"):
    return Transaction(
        raw_message="old",
        source_type="AUTO",
        source_chat_id=chat_id,
        source_message_id=message_id,
        transaction_date=datetime(2026, 1, 12, 10, 0),
        amount=Decimal("-100000.00"),
        currency="UZS",
        card_last_4="1234",
        operator_raw=operator,
        transaction_type="DEBIT",
        parsing_method="REGEX_SMS",
        parsing_confidence=0.8,
        fingerprint="same-fuzzy-candidate",
    )


def test_fingerprint_match_does_not_merge_distinct_telegram_source(db_session, monkeypatch):
    db_session.add(_existing(1, 10))
    db_session.commit()
    monkeypatch.setattr(receipt_processor, "_parse_text_in_worker", lambda *_: _parsed())

    result = asyncio.run(
        receipt_processor.process_tdlib_message(2, 20, False, db_session, _Manager())
    )

    assert result.created is True
    assert result.duplicate is False
    assert db_session.query(Transaction).count() == 2


def test_force_reparse_updates_source_row_and_writes_before_after_audit(db_session, monkeypatch):
    row = _existing(5, 50, operator="OLD")
    db_session.add(row)
    db_session.commit()
    row_id = int(row.id)
    monkeypatch.setattr(
        receipt_processor,
        "_parse_text_in_worker",
        lambda *_: _parsed(amount="250000.00", operator="NEW"),
    )

    result = asyncio.run(
        receipt_processor.process_tdlib_message(5, 50, True, db_session, _Manager("new receipt"))
    )

    assert result.created is False
    assert result.duplicate is False
    db_session.expire_all()
    updated = db_session.get(Transaction, row_id)
    assert updated.operator_raw == "NEW"
    assert updated.amount == Decimal("-250000.00")
    audit = db_session.query(AccessAuditLog).filter_by(action="receipt_force_reparse").one()
    assert '"before"' in audit.details_json
    assert '"after"' in audit.details_json
