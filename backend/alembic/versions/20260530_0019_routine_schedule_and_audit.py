"""Routine receipt_audit kind + one-shot schedule columns + agent_chat_commands.

Revision ID: 20260530_0019
Revises: 20260529_0018
Create Date: 2026-05-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260530_0019"
down_revision = "20260529_0018"
branch_labels = None
depends_on = None


def _has_table(inspector: Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector: Inspector, table: str, column: str) -> bool:
    try:
        return any(c["name"] == column for c in inspector.get_columns(table))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    # 1) Extend the routine `kind` CHECK constraint to allow 'receipt_audit'.
    #    Reflection of CHECK constraints is unreliable across backends, so we
    #    drop+recreate inside try/except and treat failures as idempotent.
    if _has_table(inspector, "agent_routines"):
        try:
            op.drop_constraint("check_agent_routine_kind", "agent_routines", type_="check")
        except Exception:
            pass
        try:
            op.create_check_constraint(
                "check_agent_routine_kind",
                "agent_routines",
                "kind IN ('reconcile', 'summary', 'custom', 'receipt_audit')",
            )
        except Exception:
            pass

        # 2) One-shot schedule support: schedule_kind + run_at.
        if not _has_column(inspector, "agent_routines", "schedule_kind"):
            op.add_column(
                "agent_routines",
                sa.Column(
                    "schedule_kind",
                    sa.String(length=20),
                    nullable=False,
                    server_default="recurring",
                ),
            )
        if not _has_column(inspector, "agent_routines", "run_at"):
            op.add_column(
                "agent_routines",
                sa.Column("run_at", sa.DateTime(timezone=True), nullable=True),
            )
        try:
            op.create_check_constraint(
                "check_agent_routine_schedule_kind",
                "agent_routines",
                "schedule_kind IN ('recurring', 'once')",
            )
        except Exception:
            pass

    # 3) Quick-command palette storage.
    if not _has_table(inspector, "agent_chat_commands"):
        op.create_table(
            "agent_chat_commands",
            sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
            sa.Column("title", sa.String(length=120), nullable=False),
            sa.Column("icon", sa.String(length=40), nullable=True),
            sa.Column("prompt_template", sa.Text(), nullable=False),
            sa.Column("requested_tool", sa.String(length=80), nullable=True),
            sa.Column("scope", sa.String(length=20), nullable=False, server_default="team"),
            sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("scope IN ('team', 'personal')", name="check_agent_chat_command_scope"),
        )
        op.create_index(
            "idx_agent_chat_commands_enabled_sort",
            "agent_chat_commands",
            ["enabled", "sort_order"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    if _has_table(inspector, "agent_chat_commands"):
        op.drop_table("agent_chat_commands")

    if _has_table(inspector, "agent_routines"):
        try:
            op.drop_constraint("check_agent_routine_schedule_kind", "agent_routines", type_="check")
        except Exception:
            pass
        if _has_column(inspector, "agent_routines", "run_at"):
            op.drop_column("agent_routines", "run_at")
        if _has_column(inspector, "agent_routines", "schedule_kind"):
            op.drop_column("agent_routines", "schedule_kind")
        # Restore the original kind constraint (without receipt_audit).
        try:
            op.drop_constraint("check_agent_routine_kind", "agent_routines", type_="check")
        except Exception:
            pass
        try:
            op.create_check_constraint(
                "check_agent_routine_kind",
                "agent_routines",
                "kind IN ('reconcile', 'summary', 'custom')",
            )
        except Exception:
            pass
