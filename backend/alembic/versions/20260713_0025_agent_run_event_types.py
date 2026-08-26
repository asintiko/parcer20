"""Keep agent run event CHECK values in parity with the runtime model.

Revision ID: 20260713_0025
Revises: 20260712_0024
Create Date: 2026-07-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260713_0025"
down_revision = "20260712_0024"
branch_labels = None
depends_on = None


_EVENT_TYPES = (
    "planning_started",
    "tool_selected",
    "tool_started",
    "tool_progress",
    "tool_finished",
    "tool_failed",
    "awaiting_confirmation",
    "completed",
    "failed",
)


def _expression(values: tuple[str, ...]) -> str:
    return "event_type IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "agent_run_events" not in set(inspector.get_table_names()):
        return
    check_names = {item.get("name") for item in inspector.get_check_constraints("agent_run_events")}
    if "check_agent_run_event_type" in check_names:
        op.drop_constraint("check_agent_run_event_type", "agent_run_events", type_="check")
    op.create_check_constraint(
        "check_agent_run_event_type",
        "agent_run_events",
        _expression(_EVENT_TYPES),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "agent_run_events" not in set(inspector.get_table_names()):
        return
    op.execute("UPDATE agent_run_events SET event_type = 'failed' WHERE event_type = 'tool_failed'")
    check_names = {item.get("name") for item in inspector.get_check_constraints("agent_run_events")}
    if "check_agent_run_event_type" in check_names:
        op.drop_constraint("check_agent_run_event_type", "agent_run_events", type_="check")
    op.create_check_constraint(
        "check_agent_run_event_type",
        "agent_run_events",
        _expression(tuple(value for value in _EVENT_TYPES if value != "tool_failed")),
    )
