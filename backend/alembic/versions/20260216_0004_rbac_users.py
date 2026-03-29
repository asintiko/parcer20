"""Add users table for RBAC login.

Revision ID: 20260216_0004
Revises: 20260214_0003
Create Date: 2026-02-16 03:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260216_0004"
down_revision = "20260214_0003"
branch_labels = None
depends_on = None


def _has_table(inspector: Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "users"):
        return

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("salt", sa.String(length=128), nullable=False),
        sa.Column("hash_method", sa.String(length=50), nullable=False, server_default="pbkdf2_sha256"),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="operator"),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("allowed_tabs", sa.Text(), nullable=False, server_default='["dashboard"]'),
        sa.Column("allowed_folders", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("forbidden_periods", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("allowed_sources", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("can_toggle_sources", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("permissions_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'operator')", name="check_user_role"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("idx_users_username", "users", ["username"], unique=False)
    op.create_index("idx_users_role_active", "users", ["role", "is_active"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, "users"):
        return
    op.drop_index("idx_users_role_active", table_name="users")
    op.drop_index("idx_users_username", table_name="users")
    op.drop_table("users")
