"""Add agent_routines + agent_routine_runs tables.

Revision ID: 20260529_0018
Revises: 20260524_0017
Create Date: 2026-05-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260529_0018"
down_revision = "20260524_0017"
branch_labels = None
depends_on = None


def _has_table(inspector: Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    if not _has_table(inspector, "agent_routines"):
        op.create_table(
            "agent_routines",
            sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("task_prompt", sa.Text(), nullable=False),
            sa.Column("cron", sa.String(length=120), nullable=False, server_default="0 12 * * 1"),
            sa.Column("kind", sa.String(length=40), nullable=False, server_default="reconcile"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("deliver_to_channel", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("deliver_to_chat", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_status", sa.String(length=20), nullable=True),
            sa.Column("last_summary", sa.Text(), nullable=True),
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("kind IN ('reconcile', 'summary', 'custom')", name="check_agent_routine_kind"),
            sa.CheckConstraint(
                "last_status IS NULL OR last_status IN ('ok', 'error', 'running')",
                name="check_agent_routine_status",
            ),
        )
        op.create_index("idx_agent_routines_enabled", "agent_routines", ["enabled"])

    if not _has_table(inspector, "agent_routine_runs"):
        op.create_table(
            "agent_routine_runs",
            sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
            sa.Column("routine_id", sa.Uuid(as_uuid=True), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
            sa.Column("trigger", sa.String(length=20), nullable=False, server_default="schedule"),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("result_json", sa.Text(), nullable=True),
            sa.Column("error_text", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("status IN ('running', 'ok', 'error')", name="check_agent_routine_run_status"),
        )
        op.create_index(
            "idx_agent_routine_runs_routine_started",
            "agent_routine_runs",
            ["routine_id", "started_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    if _has_table(inspector, "agent_routine_runs"):
        op.drop_table("agent_routine_runs")
    if _has_table(inspector, "agent_routines"):
        op.drop_table("agent_routines")
