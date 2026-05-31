"""Add excluded_user_ids JSONB to locked_periods.

Revision ID: 20260524_0017
Revises: 20260328_0016
Create Date: 2026-05-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.reflection import Inspector


revision = "20260524_0017"
down_revision = "20260328_0016"
branch_labels = None
depends_on = None


def _has_table(inspector: Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector: Inspector, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    if not _has_table(inspector, "locked_periods"):
        return
    if _has_column(inspector, "locked_periods", "excluded_user_ids"):
        return
    op.add_column(
        "locked_periods",
        sa.Column(
            "excluded_user_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    if not _has_table(inspector, "locked_periods"):
        return
    if not _has_column(inspector, "locked_periods", "excluded_user_ids"):
        return
    op.drop_column("locked_periods", "excluded_user_ids")
