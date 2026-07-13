"""Add raw_message column to receipt_processing_tasks.

Revision ID: 20260220_0012
Revises: 20260220_0011
Create Date: 2026-02-20 01:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260220_0012"
down_revision = "20260220_0011"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    cols = [c["name"] for c in inspector.get_columns(table)]
    return column in cols


def upgrade() -> None:
    if not _column_exists("receipt_processing_tasks", "raw_message"):
        op.add_column(
            "receipt_processing_tasks",
            sa.Column("raw_message", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    dialect = bind.dialect.name
    if _column_exists("receipt_processing_tasks", "raw_message"):
        if dialect == "sqlite":
            # SQLite doesn't support DROP COLUMN directly in older versions;
            # skip downgrade for SQLite environments
            pass
        else:
            op.drop_column("receipt_processing_tasks", "raw_message")
