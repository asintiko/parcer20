"""v1.2.0 schema hotfix for nullable/default mismatches

Revision ID: 20260213_0002
Revises: 20260213_0001
Create Date: 2026-02-13 05:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260213_0002"
down_revision = "20260213_0001"
branch_labels = None
depends_on = None


def _has_table(inspector: Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _column_info(inspector: Inspector, table_name: str, column_name: str):
    columns = inspector.get_columns(table_name)
    for column in columns:
        if column.get("name") == column_name:
            return column
    return None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "chat_passwords"):
        column = _column_info(inspector, "chat_passwords", "updated_at")
        if column is not None:
            op.execute("UPDATE chat_passwords SET updated_at = now() WHERE updated_at IS NULL")
            if bool(column.get("nullable", True)):
                op.alter_column(
                    "chat_passwords",
                    "updated_at",
                    existing_type=sa.DateTime(timezone=True),
                    existing_server_default=sa.text("now()"),
                    nullable=False,
                )

    if _has_table(inspector, "app_launch_config"):
        column = _column_info(inspector, "app_launch_config", "id")
        if column is not None:
            op.execute("UPDATE app_launch_config SET id = 1 WHERE id IS NULL")
            op.alter_column(
                "app_launch_config",
                "id",
                existing_type=sa.Integer(),
                existing_nullable=False,
                server_default=sa.text("1"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "app_launch_config"):
        op.alter_column(
            "app_launch_config",
            "id",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default=None,
        )

    if _has_table(inspector, "chat_passwords"):
        op.alter_column(
            "chat_passwords",
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            existing_server_default=sa.text("now()"),
            nullable=True,
        )
