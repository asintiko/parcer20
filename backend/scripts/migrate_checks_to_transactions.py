"""
One-time migration script to move data from checks table to transactions table.
Run manually (e.g. `python -m backend.scripts.migrate_checks_to_transactions`).
"""
import json
from decimal import Decimal

from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import Check, Transaction


def migrate():
    with get_db() as db:  # type: Session
        checks = db.query(Check).all()
        migrated = 0
        for chk in checks:
            # Skip if already migrated (by source ids)
            existing = (
                db.query(Transaction)
                .filter(
                    Transaction.source_chat_id == chk.source_chat_id,
                    Transaction.source_message_id == chk.source_message_id,
                )
                .first()
            )
            if existing:
                continue

            amount = Decimal(str(chk.amount))
            txn_type = (chk.transaction_type or "DEBIT").upper()
            store_amount = -abs(amount) if txn_type == "DEBIT" else abs(amount)

            parsing_method = None
            parsing_confidence = None
            is_gpt_parsed = False
            try:
                if chk.metadata_json:
                    meta = json.loads(chk.metadata_json)
                    parsing_method = meta.get("parsing_method")
                    parsing_confidence = meta.get("parsing_confidence")
                    if parsing_method and str(parsing_method).upper().startswith("GPT"):
                        is_gpt_parsed = True
            except Exception:
                pass

            txn = Transaction(
                transaction_date=chk.datetime,
                amount=store_amount,
                currency=chk.currency or "UZS",
                card_last_4=chk.card_last4,
                operator_raw=chk.operator,
                application_mapped=chk.app,
                transaction_type=txn_type,
                balance_after=chk.balance,
                raw_message=chk.raw_text,
                source_type="AUTO",
                source_chat_id=chk.source_chat_id,
                source_message_id=chk.source_message_id,
                parsing_method=parsing_method,
                parsing_confidence=parsing_confidence,
                is_gpt_parsed=is_gpt_parsed,
                is_p2p=chk.is_p2p,
            )
            db.add(txn)
            migrated += 1

        db.commit()
        print(f"Migrated {migrated} rows from checks to transactions")


if __name__ == "__main__":
    migrate()
