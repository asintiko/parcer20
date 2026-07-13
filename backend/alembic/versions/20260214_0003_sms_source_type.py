"""Allow SMS source type for transactions.

Revision ID: 20260214_0003
Revises: 20260213_0002
Create Date: 2026-02-14 01:00:00
"""
from __future__ import annotations

from alembic import op


revision = "20260214_0003"
down_revision = "20260213_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE transactions DROP CONSTRAINT IF EXISTS check_source_type")
    op.execute(
        """
        ALTER TABLE transactions
        ADD CONSTRAINT check_source_type
        CHECK (source_type IN ('MANUAL', 'AUTO', 'SMS'))
        """
    )


def downgrade() -> None:
    op.execute("UPDATE transactions SET source_type = 'AUTO' WHERE upper(source_type) = 'SMS'")
    op.execute("ALTER TABLE transactions DROP CONSTRAINT IF EXISTS check_source_type")
    op.execute(
        """
        ALTER TABLE transactions
        ADD CONSTRAINT check_source_type
        CHECK (source_type IN ('MANUAL', 'AUTO'))
        """
    )
