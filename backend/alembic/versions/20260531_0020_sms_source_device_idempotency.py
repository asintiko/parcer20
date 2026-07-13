"""Per-device SMS idempotency: source_device_id / source_device_sms_id on transactions.

Revision ID: 20260531_0020
Revises: 20260530_0019
Create Date: 2026-05-31
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260531_0020"
down_revision = "20260530_0019"
branch_labels = None
depends_on = None


def _has_column(inspector: Inspector, table: str, column: str) -> bool:
    try:
        return any(c["name"] == column for c in inspector.get_columns(table))
    except Exception:
        return False


def _has_index(inspector: Inspector, table: str, index_name: str) -> bool:
    try:
        return any(ix["name"] == index_name for ix in inspector.get_indexes(table))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    if not _has_column(inspector, "transactions", "source_device_id"):
        op.add_column(
            "transactions",
            sa.Column("source_device_id", sa.String(length=128), nullable=True),
        )
    if not _has_column(inspector, "transactions", "source_device_sms_id"):
        op.add_column(
            "transactions",
            sa.Column("source_device_sms_id", sa.String(length=128), nullable=True),
        )

    if not _has_index(inspector, "transactions", "uq_transactions_source_device_sms"):
        op.create_index(
            "uq_transactions_source_device_sms",
            "transactions",
            ["source_device_id", "source_device_sms_id"],
            unique=True,
            postgresql_where=sa.text("source_device_sms_id IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    if _has_index(inspector, "transactions", "uq_transactions_source_device_sms"):
        op.drop_index("uq_transactions_source_device_sms", table_name="transactions")
    if _has_column(inspector, "transactions", "source_device_sms_id"):
        op.drop_column("transactions", "source_device_sms_id")
    if _has_column(inspector, "transactions", "source_device_id"):
        op.drop_column("transactions", "source_device_id")
