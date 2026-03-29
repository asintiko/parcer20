"""Expand agent run status column to fit awaiting_confirmation.

Revision ID: 20260328_0016
Revises: 20260327_0015
Create Date: 2026-03-28 00:45:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260328_0016"
down_revision = "20260327_0015"
branch_labels = None
depends_on = None


def _has_table(inspector: Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    if not _has_table(inspector, "agent_runs"):
        return
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=20),
            type_=sa.String(length=40),
            existing_nullable=False,
            existing_server_default="queued",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    if not _has_table(inspector, "agent_runs"):
        return
    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=40),
            type_=sa.String(length=20),
            existing_nullable=False,
            existing_server_default="queued",
        )
