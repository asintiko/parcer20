"""Add telegram_id and telegram_username columns to users table.

Revision ID: 20260220_0008
Revises: 20260219_0007
Create Date: 2026-02-20 00:08:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260220_0008"
down_revision = "20260219_0007"
branch_labels = None
depends_on = None


def _has_column(inspector: Inspector, table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _has_index(inspector: Inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    if not _has_column(inspector, "users", "telegram_id"):
        op.add_column("users", sa.Column("telegram_id", sa.BigInteger(), nullable=True))

    if not _has_column(inspector, "users", "telegram_username"):
        op.add_column("users", sa.Column("telegram_username", sa.String(255), nullable=True))

    # Unique index on telegram_id (only non-null values)
    if not _has_index(inspector, "users", "ix_users_telegram_id"):
        op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    if _has_index(inspector, "users", "ix_users_telegram_id"):
        op.drop_index("ix_users_telegram_id", table_name="users")

    if _has_column(inspector, "users", "telegram_id"):
        op.drop_column("users", "telegram_id")

    if _has_column(inspector, "users", "telegram_username"):
        op.drop_column("users", "telegram_username")
