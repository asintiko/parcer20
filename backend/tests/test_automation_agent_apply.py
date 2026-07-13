from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")

from database.models import (
    AutomationSuggestion,
    Transaction,
    VerificationSuggestion,
)
from services.automation.agent_apply_service import (
    apply_mapping_suggestions,
    apply_verification_suggestions,
    rollback_automation,
)


def _seed_tx(db_session, *, idx: int, application=None) -> Transaction:
    row = Transaction(
        raw_message=f"raw-{idx}",
        source_type="AUTO",
        source_chat_id=900 + idx,
        source_message_id=idx,
        transaction_date=datetime(2026, 2, 10 + idx, 10, 0, 0),
        amount=Decimal("-100.00"),
        currency="UZS",
        card_last_4="2222",
        operator_raw=f"Korzinka {idx}",
        application_mapped=application,
        transaction_type="DEBIT",
        parsing_method="REGEX_SMS",
        fingerprint=f"apply-fp-{idx}",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_apply_mapping_respects_threshold_and_is_revertible(db_session):
    task_id = uuid4()
    confident_tx = _seed_tx(db_session, idx=1, application=None)
    weak_tx = _seed_tx(db_session, idx=2, application=None)

    db_session.add(AutomationSuggestion(
        id=uuid4(), task_id=task_id, transaction_id=confident_tx.id,
        suggested_application="Korzinka", confidence=0.95, is_p2p=False, status="pending",
    ))
    db_session.add(AutomationSuggestion(
        id=uuid4(), task_id=task_id, transaction_id=weak_tx.id,
        suggested_application="Maybe", confidence=0.50, is_p2p=False, status="pending",
    ))
    db_session.commit()

    out = apply_mapping_suggestions(
        db_session, task_id=str(task_id), scope=None, current_user={"user_id": 1}, min_confidence=0.85,
    )
    assert out["applied"] == 1
    assert out["low_confidence"] == 1

    db_session.refresh(confident_tx)
    db_session.refresh(weak_tx)
    assert confident_tx.application_mapped == "Korzinka"
    assert weak_tx.application_mapped is None  # below threshold, untouched

    rolled = rollback_automation(db_session, task_id=str(task_id), scope_kind="mapping")
    assert rolled["reverted"] == 1
    db_session.refresh(confident_tx)
    assert confident_tx.application_mapped is None  # reverted to prior null


def test_apply_verification_revert_uses_old_value(db_session):
    task_id = uuid4()
    tx = _seed_tx(db_session, idx=3, application="App")
    original_operator = tx.operator_raw

    db_session.add(VerificationSuggestion(
        id=uuid4(), task_id=task_id, transaction_id=tx.id,
        field_name="operator_raw",
        current_value=original_operator,
        suggested_value="Corrected Operator",
        confidence=0.97, status="pending",
    ))
    db_session.commit()

    out = apply_verification_suggestions(
        db_session, task_id=str(task_id), scope=None, current_user={"user_id": 1}, min_confidence=0.85,
    )
    assert out["applied"] == 1
    db_session.refresh(tx)
    assert tx.operator_raw == "Corrected Operator"

    rolled = rollback_automation(db_session, task_id=str(task_id), scope_kind="verification")
    assert rolled["reverted"] == 1
    assert rolled["unrevertable"] == 0
    db_session.refresh(tx)
    assert tx.operator_raw == original_operator


def test_verification_without_old_value_is_unrevertable(db_session):
    task_id = uuid4()
    tx = _seed_tx(db_session, idx=4, application="App")

    db_session.add(VerificationSuggestion(
        id=uuid4(), task_id=task_id, transaction_id=tx.id,
        field_name="card_last_4",
        current_value=None,  # no prior value captured
        suggested_value="9999",
        confidence=0.99, status="pending",
    ))
    db_session.commit()

    out = apply_verification_suggestions(
        db_session, task_id=str(task_id), scope=None, current_user={"user_id": 1}, min_confidence=0.85,
    )
    assert out["applied"] == 1
    db_session.refresh(tx)
    assert tx.card_last_4 == "9999"

    rolled = rollback_automation(db_session, task_id=str(task_id), scope_kind="verification")
    assert rolled["reverted"] == 0
    assert rolled["unrevertable"] == 1
    assert any("прежнее значение" in note for note in rolled["notes"])
