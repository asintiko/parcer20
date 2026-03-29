"""v1.2.0 security/sync schema

Revision ID: 20260213_0001
Revises:
Create Date: 2026-02-13 03:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260213_0001"
down_revision = None
branch_labels = None
depends_on = None


def _has_table(inspector: Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(inspector: Inspector, table_name: str, column_name: str) -> bool:
    columns = inspector.get_columns(table_name)
    return any(column.get("name") == column_name for column in columns)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "access_scopes") and not _has_column(inspector, "access_scopes", "auth_method"):
        op.add_column(
            "access_scopes",
            sa.Column("auth_method", sa.String(length=20), nullable=False, server_default="otp"),
        )
        op.create_index("idx_access_scopes_auth_method", "access_scopes", ["auth_method"], unique=False)

    if not _has_table(inspector, "sync_deletions"):
        op.create_table(
            "sync_deletions",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("table_name", sa.String(length=100), nullable=False),
            sa.Column("record_id", sa.BigInteger(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_sync_deletions_table", "sync_deletions", ["table_name"], unique=False)
        op.create_index("idx_sync_deletions_deleted", "sync_deletions", ["deleted_at"], unique=False)
        op.create_index("idx_sync_deletions_table_record", "sync_deletions", ["table_name", "record_id"], unique=False)

    if not _has_table(inspector, "chat_passwords"):
        op.create_table(
            "chat_passwords",
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("password_hash", sa.String(length=512), nullable=False),
            sa.Column("salt", sa.String(length=128), nullable=False),
            sa.Column("hash_method", sa.String(length=50), nullable=False, server_default="pbkdf2_sha256"),
            sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("chat_id"),
        )
        op.create_index("idx_chat_passwords_locked", "chat_passwords", ["locked_until"], unique=False)

    if not _has_table(inspector, "app_launch_config"):
        op.create_table(
            "app_launch_config",
            sa.Column("id", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column("password_hash", sa.String(length=512), nullable=False),
            sa.Column("salt", sa.String(length=128), nullable=False),
            sa.Column("hash_method", sa.String(length=50), nullable=False, server_default="pbkdf2_sha256"),
            sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_by_tg_id", sa.BigInteger(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table(inspector, "locked_periods"):
        op.create_table(
            "locked_periods",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("date_from", sa.Date(), nullable=False),
            sa.Column("date_to", sa.Date(), nullable=False),
            sa.Column("reason", sa.String(length=500), nullable=True),
            sa.Column("locked_by_tg_id", sa.BigInteger(), nullable=False),
            sa.Column("locked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.CheckConstraint("date_from <= date_to", name="check_period_valid"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_locked_periods_active", "locked_periods", ["is_active"], unique=False)
        op.create_index("idx_locked_periods_range", "locked_periods", ["date_from", "date_to"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "locked_periods"):
        op.drop_index("idx_locked_periods_range", table_name="locked_periods")
        op.drop_index("idx_locked_periods_active", table_name="locked_periods")
        op.drop_table("locked_periods")

    if _has_table(inspector, "app_launch_config"):
        op.drop_table("app_launch_config")

    if _has_table(inspector, "chat_passwords"):
        op.drop_index("idx_chat_passwords_locked", table_name="chat_passwords")
        op.drop_table("chat_passwords")

    if _has_table(inspector, "sync_deletions"):
        op.drop_index("idx_sync_deletions_table_record", table_name="sync_deletions")
        op.drop_index("idx_sync_deletions_deleted", table_name="sync_deletions")
        op.drop_index("idx_sync_deletions_table", table_name="sync_deletions")
        op.drop_table("sync_deletions")

    if _has_table(inspector, "access_scopes") and _has_column(inspector, "access_scopes", "auth_method"):
        op.drop_index("idx_access_scopes_auth_method", table_name="access_scopes")
        op.drop_column("access_scopes", "auth_method")
