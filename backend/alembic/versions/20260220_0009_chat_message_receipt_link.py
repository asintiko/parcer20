"""Add receipt_transaction_id column to tg_chat_messages table.

Revision ID: 20260220_0009
Revises: 20260220_0008
Create Date: 2026-02-20 00:09:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260220_0009"
down_revision = "20260220_0008"
branch_labels = None
depends_on = None


def _has_column(inspector: Inspector, table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _has_index(inspector: Inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    if not _has_column(inspector, "tg_chat_messages", "receipt_transaction_id"):
        op.add_column(
            "tg_chat_messages",
            sa.Column("receipt_transaction_id", sa.BigInteger(), nullable=True),
        )

    if not _has_index(inspector, "tg_chat_messages", "idx_tg_chat_messages_receipt_tx"):
        op.create_index(
            "idx_tg_chat_messages_receipt_tx",
            "tg_chat_messages",
            ["receipt_transaction_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    if _has_index(inspector, "tg_chat_messages", "idx_tg_chat_messages_receipt_tx"):
        op.drop_index("idx_tg_chat_messages_receipt_tx", table_name="tg_chat_messages")

    if _has_column(inspector, "tg_chat_messages", "receipt_transaction_id"):
        op.drop_column("tg_chat_messages", "receipt_transaction_id")
