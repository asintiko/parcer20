"""Add session_ttl_days to users.

Revision ID: 20260220_0013
Revises: 20260220_0012
Create Date: 2026-02-20 05:20:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260220_0013"
down_revision = "20260220_0012"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    cols = [c["name"] for c in inspector.get_columns(table)]
    return column in cols


def _constraint_exists(table: str, constraint_name: str) -> bool:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    constraints = inspector.get_check_constraints(table)
    names = {str(item.get("name") or "") for item in constraints}
    return constraint_name in names


def upgrade() -> None:
    if not _column_exists("users", "session_ttl_days"):
        op.add_column(
            "users",
            sa.Column("session_ttl_days", sa.Integer(), nullable=False, server_default="7"),
        )
    op.execute("UPDATE users SET session_ttl_days = 7 WHERE session_ttl_days IS NULL")
    op.execute("UPDATE users SET session_ttl_days = 1 WHERE session_ttl_days < 1")
    op.execute("UPDATE users SET session_ttl_days = 90 WHERE session_ttl_days > 90")

    if not _constraint_exists("users", "check_user_session_ttl_days"):
        op.create_check_constraint(
            "check_user_session_ttl_days",
            "users",
            "session_ttl_days >= 1 AND session_ttl_days <= 90",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    dialect = bind.dialect.name

    if _constraint_exists("users", "check_user_session_ttl_days"):
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_constraint("check_user_session_ttl_days", type_="check")

    if _column_exists("users", "session_ttl_days"):
        if dialect == "sqlite":
            # Skip unsupported DROP COLUMN on old sqlite.
            return
        op.drop_column("users", "session_ttl_days")
