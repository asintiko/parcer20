"""Add user 2FA fields.

Revision ID: 20260218_0006
Revises: 20260218_0005
Create Date: 2026-02-18 13:10:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260218_0006"
down_revision = "20260218_0005"
branch_labels = None
depends_on = None


def _has_table(inspector: Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector: Inspector, table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, "users"):
        return

    if not _has_column(inspector, "users", "force_2fa"):
        op.add_column("users", sa.Column("force_2fa", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    if not _has_column(inspector, "users", "totp_secret"):
        op.add_column("users", sa.Column("totp_secret", sa.String(length=128), nullable=True))
    if not _has_column(inspector, "users", "totp_enabled"):
        op.add_column("users", sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    if not _has_column(inspector, "users", "totp_confirmed_at"):
        op.add_column("users", sa.Column("totp_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column(inspector, "users", "backup_codes"):
        op.add_column("users", sa.Column("backup_codes", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, "users"):
        return

    if _has_column(inspector, "users", "backup_codes"):
        op.drop_column("users", "backup_codes")
    if _has_column(inspector, "users", "totp_confirmed_at"):
        op.drop_column("users", "totp_confirmed_at")
    if _has_column(inspector, "users", "totp_enabled"):
        op.drop_column("users", "totp_enabled")
    if _has_column(inspector, "users", "totp_secret"):
        op.drop_column("users", "totp_secret")
    if _has_column(inspector, "users", "force_2fa"):
        op.drop_column("users", "force_2fa")
