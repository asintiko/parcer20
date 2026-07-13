"""Repair transaction signs and deduplicate active receipt incidents.

Revision ID: 20260712_0024
Revises: 20260712_0023
Create Date: 2026-07-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260712_0024"
down_revision = "20260712_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "transactions" in tables:
        # The domain stores debits as negative and every other direction as
        # positive. Historical rows predate that invariant.
        op.execute(
            """
            UPDATE transactions
               SET amount = CASE
                   WHEN transaction_type = 'DEBIT' THEN -ABS(amount)
                   ELSE ABS(amount)
               END,
                   updated_at = NOW()
             WHERE (transaction_type = 'DEBIT' AND amount > 0)
                OR (transaction_type <> 'DEBIT' AND amount < 0)
            """
        )
        check_names = {item.get("name") for item in inspector.get_check_constraints("transactions")}
        if "check_transaction_amount_sign" not in check_names:
            op.create_check_constraint(
                "check_transaction_amount_sign",
                "transactions",
                "(transaction_type = 'DEBIT' AND amount <= 0) OR "
                "(transaction_type <> 'DEBIT' AND amount >= 0)",
            )

    if "receipt_processing_incidents" in tables:
        # Resolve obsolete missing incidents that now have a concrete source
        # transaction, then collapse concurrent duplicate incident rows.
        op.execute(
            """
            UPDATE receipt_processing_incidents AS incident
               SET status = 'resolved', resolved_at = NOW(), last_seen_at = NOW()
             WHERE incident.incident_type = 'missing_in_db'
               AND incident.status IN ('open', 'acknowledged', 'ignored')
               AND incident.message_id IS NOT NULL
               AND EXISTS (
                   SELECT 1
                     FROM transactions AS tx
                    WHERE tx.source_chat_id = incident.chat_id
                      AND tx.source_message_id = incident.message_id
               )
            """
        )
        op.execute(
            """
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY chat_id, COALESCE(message_id, -1), incident_type
                           ORDER BY last_seen_at DESC, first_seen_at DESC, id DESC
                       ) AS position
                  FROM receipt_processing_incidents
                 WHERE status IN ('open', 'acknowledged', 'ignored')
            )
            UPDATE receipt_processing_incidents AS incident
               SET status = 'resolved', resolved_at = NOW()
              FROM ranked
             WHERE incident.id = ranked.id
               AND ranked.position > 1
            """
        )
        index_names = {item.get("name") for item in inspector.get_indexes("receipt_processing_incidents")}
        if "uq_receipt_incidents_active" not in index_names:
            op.execute(
                """
                CREATE UNIQUE INDEX uq_receipt_incidents_active
                    ON receipt_processing_incidents (
                        chat_id, COALESCE(message_id, -1), incident_type
                    )
                 WHERE status IN ('open', 'acknowledged', 'ignored')
                """
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "receipt_processing_incidents" in tables:
        index_names = {item.get("name") for item in inspector.get_indexes("receipt_processing_incidents")}
        if "uq_receipt_incidents_active" in index_names:
            op.drop_index("uq_receipt_incidents_active", table_name="receipt_processing_incidents")
    if "transactions" in tables:
        check_names = {item.get("name") for item in inspector.get_check_constraints("transactions")}
        if "check_transaction_amount_sign" in check_names:
            op.drop_constraint("check_transaction_amount_sign", "transactions", type_="check")
    # Corrected signs and incident resolutions are intentionally not reversed.
