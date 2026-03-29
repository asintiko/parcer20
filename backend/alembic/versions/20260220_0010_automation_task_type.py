"""Add task_type column to automation_tasks table.

Revision ID: 20260220_0010
Revises: 20260220_0009
Create Date: 2026-02-20 00:10:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260220_0010"
down_revision = "20260220_0009"
branch_labels = None
depends_on = None


def _has_column(inspector: Inspector, table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    if not _has_column(inspector, "automation_tasks", "task_type"):
        op.add_column(
            "automation_tasks",
            sa.Column(
                "task_type",
                sa.String(30),
                nullable=True,
                server_default="mapping",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    if _has_column(inspector, "automation_tasks", "task_type"):
        op.drop_column("automation_tasks", "task_type")
