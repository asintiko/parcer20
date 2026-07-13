"""Operator descriptions: descriptions + operator_description_links tables.

Revision ID: 20260605_0021
Revises: 20260531_0020
Create Date: 2026-06-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260605_0021"
down_revision = "20260531_0020"
branch_labels = None
depends_on = None


def _has_table(inspector: Inspector, table: str) -> bool:
    try:
        return inspector.has_table(table)
    except Exception:
        return False


def _has_index(inspector: Inspector, table: str, index_name: str) -> bool:
    try:
        return any(ix["name"] == index_name for ix in inspector.get_indexes(table))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    if not _has_table(inspector, "descriptions"):
        op.create_table(
            "descriptions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
        )

    if not _has_table(inspector, "operator_description_links"):
        op.create_table(
            "operator_description_links",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("operator_key", sa.String(length=500), nullable=False),
            sa.Column("description_id", sa.Integer(), nullable=False),
            sa.Column(
                "source",
                sa.String(length=20),
                server_default="manual",
                nullable=False,
            ),
            sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["description_id"],
                ["descriptions.id"],
                ondelete="CASCADE",
            ),
        )

    inspector = Inspector.from_engine(bind)

    if not _has_index(inspector, "operator_description_links", "idx_operator_desc_link_key"):
        op.create_index(
            "idx_operator_desc_link_key",
            "operator_description_links",
            ["operator_key"],
            unique=True,
        )
    if not _has_index(inspector, "operator_description_links", "idx_operator_desc_link_desc"):
        op.create_index(
            "idx_operator_desc_link_desc",
            "operator_description_links",
            ["description_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    if _has_index(inspector, "operator_description_links", "idx_operator_desc_link_desc"):
        op.drop_index("idx_operator_desc_link_desc", table_name="operator_description_links")
    if _has_index(inspector, "operator_description_links", "idx_operator_desc_link_key"):
        op.drop_index("idx_operator_desc_link_key", table_name="operator_description_links")
    if _has_table(inspector, "operator_description_links"):
        op.drop_table("operator_description_links")
    if _has_table(inspector, "descriptions"):
        op.drop_table("descriptions")
