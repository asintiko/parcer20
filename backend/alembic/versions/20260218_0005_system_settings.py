"""Add system_settings table.

Revision ID: 20260218_0005
Revises: 20260216_0004
Create Date: 2026-02-18 13:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260218_0005"
down_revision = "20260216_0004"
branch_labels = None
depends_on = None


def _has_table(inspector: Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "system_settings"):
        op.create_table(
            "system_settings",
            sa.Column("id", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("otp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("bot_control_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("totp_2fa_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("launch_gate_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_by", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    op.execute(
        """
        INSERT INTO system_settings (id, otp_enabled, bot_control_enabled, totp_2fa_enabled, launch_gate_enabled)
        SELECT 1, TRUE, TRUE, FALSE, FALSE
        WHERE NOT EXISTS (SELECT 1 FROM system_settings WHERE id = 1)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "system_settings"):
        op.drop_table("system_settings")
