"""Add AI agent core tables.

Revision ID: 20260327_0014
Revises: 20260220_0013
Create Date: 2026-03-27 18:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260327_0014"
down_revision = "20260220_0013"
branch_labels = None
depends_on = None


def _has_table(inspector: Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_index(inspector: Inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    if not _has_table(inspector, "agent_threads"):
        op.create_table(
            "agent_threads",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False, server_default="Новый диалог"),
            sa.Column("context_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_agent_threads_user_updated", "agent_threads", ["created_by_user_id", "updated_at"], unique=False)
    elif not _has_index(inspector, "agent_threads", "idx_agent_threads_user_updated"):
        op.create_index("idx_agent_threads_user_updated", "agent_threads", ["created_by_user_id", "updated_at"], unique=False)

    if not _has_table(inspector, "agent_messages"):
        op.create_table(
            "agent_messages",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("thread_id", sa.Uuid(), nullable=False),
            sa.Column("run_id", sa.Uuid(), nullable=True),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("message_type", sa.String(length=30), nullable=False, server_default="text"),
            sa.Column("content_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.CheckConstraint("role IN ('user', 'assistant', 'system', 'tool')", name="check_agent_message_role"),
            sa.CheckConstraint(
                "message_type IN ('text', 'tool_run', 'report', 'confirmation', 'warning', 'navigation')",
                name="check_agent_message_type",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_agent_messages_thread_created", "agent_messages", ["thread_id", "created_at"], unique=False)
        op.create_index("ix_agent_messages_run_id", "agent_messages", ["run_id"], unique=False)
    else:
        if not _has_index(inspector, "agent_messages", "idx_agent_messages_thread_created"):
            op.create_index("idx_agent_messages_thread_created", "agent_messages", ["thread_id", "created_at"], unique=False)
        if not _has_index(inspector, "agent_messages", "ix_agent_messages_run_id"):
            op.create_index("ix_agent_messages_run_id", "agent_messages", ["run_id"], unique=False)

    if not _has_table(inspector, "agent_runs"):
        op.create_table(
            "agent_runs",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("thread_id", sa.Uuid(), nullable=False),
            sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
            sa.Column("tool_name", sa.String(length=80), nullable=True),
            sa.Column("progress_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("result_json", sa.Text(), nullable=True),
            sa.Column("error_text", sa.Text(), nullable=True),
            sa.Column("requires_confirmation", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.CheckConstraint(
                "status IN ('queued', 'processing', 'awaiting_confirmation', 'completed', 'failed', 'cancelled')",
                name="check_agent_run_status",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_agent_runs_thread_updated", "agent_runs", ["thread_id", "updated_at"], unique=False)
        op.create_index("idx_agent_runs_user_created", "agent_runs", ["created_by_user_id", "created_at"], unique=False)
    else:
        if not _has_index(inspector, "agent_runs", "idx_agent_runs_thread_updated"):
            op.create_index("idx_agent_runs_thread_updated", "agent_runs", ["thread_id", "updated_at"], unique=False)
        if not _has_index(inspector, "agent_runs", "idx_agent_runs_user_created"):
            op.create_index("idx_agent_runs_user_created", "agent_runs", ["created_by_user_id", "created_at"], unique=False)

    if not _has_table(inspector, "agent_reports"):
        op.create_table(
            "agent_reports",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
            sa.Column("thread_id", sa.Uuid(), nullable=True),
            sa.Column("scope", sa.String(length=20), nullable=False, server_default="personal"),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="ready"),
            sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.CheckConstraint("scope IN ('personal', 'team')", name="check_agent_report_scope"),
            sa.CheckConstraint("status IN ('draft', 'ready', 'published', 'archived')", name="check_agent_report_status"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_agent_reports_scope_created", "agent_reports", ["scope", "created_at"], unique=False)
        op.create_index("ix_agent_reports_thread_id", "agent_reports", ["thread_id"], unique=False)
    else:
        if not _has_index(inspector, "agent_reports", "idx_agent_reports_scope_created"):
            op.create_index("idx_agent_reports_scope_created", "agent_reports", ["scope", "created_at"], unique=False)
        if not _has_index(inspector, "agent_reports", "ix_agent_reports_thread_id"):
            op.create_index("ix_agent_reports_thread_id", "agent_reports", ["thread_id"], unique=False)

    if not _has_table(inspector, "agent_report_items"):
        op.create_table(
            "agent_report_items",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("report_id", sa.Uuid(), nullable=False),
            sa.Column("issue_type", sa.String(length=80), nullable=False),
            sa.Column("severity", sa.String(length=20), nullable=False, server_default="medium"),
            sa.Column("entity_type", sa.String(length=80), nullable=False),
            sa.Column("entity_id", sa.String(length=255), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("suggested_action_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("assignee_user_id", sa.BigInteger(), nullable=True),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="check_agent_report_item_severity"),
            sa.CheckConstraint("status IN ('open', 'claimed', 'released', 'resolved')", name="check_agent_report_item_status"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_agent_report_items_report_status", "agent_report_items", ["report_id", "status"], unique=False)
        op.create_index("idx_agent_report_items_assignee_status", "agent_report_items", ["assignee_user_id", "status"], unique=False)
    else:
        if not _has_index(inspector, "agent_report_items", "idx_agent_report_items_report_status"):
            op.create_index("idx_agent_report_items_report_status", "agent_report_items", ["report_id", "status"], unique=False)
        if not _has_index(inspector, "agent_report_items", "idx_agent_report_items_assignee_status"):
            op.create_index("idx_agent_report_items_assignee_status", "agent_report_items", ["assignee_user_id", "status"], unique=False)

    if not _has_table(inspector, "agent_notifications"):
        op.create_table(
            "agent_notifications",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("scope", sa.String(length=20), nullable=False, server_default="personal"),
            sa.Column("user_id", sa.BigInteger(), nullable=True),
            sa.Column("report_id", sa.Uuid(), nullable=True),
            sa.Column("report_item_id", sa.Uuid(), nullable=True),
            sa.Column("type", sa.String(length=80), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("scope IN ('personal', 'team')", name="check_agent_notification_scope"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_agent_notifications_scope_created", "agent_notifications", ["scope", "created_at"], unique=False)
        op.create_index("idx_agent_notifications_user_unread", "agent_notifications", ["user_id", "is_read"], unique=False)
        op.create_index("ix_agent_notifications_report_id", "agent_notifications", ["report_id"], unique=False)
        op.create_index("ix_agent_notifications_report_item_id", "agent_notifications", ["report_item_id"], unique=False)
    else:
        if not _has_index(inspector, "agent_notifications", "idx_agent_notifications_scope_created"):
            op.create_index("idx_agent_notifications_scope_created", "agent_notifications", ["scope", "created_at"], unique=False)
        if not _has_index(inspector, "agent_notifications", "idx_agent_notifications_user_unread"):
            op.create_index("idx_agent_notifications_user_unread", "agent_notifications", ["user_id", "is_read"], unique=False)
        if not _has_index(inspector, "agent_notifications", "ix_agent_notifications_report_id"):
            op.create_index("ix_agent_notifications_report_id", "agent_notifications", ["report_id"], unique=False)
        if not _has_index(inspector, "agent_notifications", "ix_agent_notifications_report_item_id"):
            op.create_index("ix_agent_notifications_report_item_id", "agent_notifications", ["report_item_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    if _has_table(inspector, "agent_notifications"):
        for idx in (
            "ix_agent_notifications_report_item_id",
            "ix_agent_notifications_report_id",
            "idx_agent_notifications_user_unread",
            "idx_agent_notifications_scope_created",
        ):
            if _has_index(inspector, "agent_notifications", idx):
                op.drop_index(idx, table_name="agent_notifications")
        op.drop_table("agent_notifications")

    if _has_table(inspector, "agent_report_items"):
        for idx in ("idx_agent_report_items_assignee_status", "idx_agent_report_items_report_status"):
            if _has_index(inspector, "agent_report_items", idx):
                op.drop_index(idx, table_name="agent_report_items")
        op.drop_table("agent_report_items")

    if _has_table(inspector, "agent_reports"):
        for idx in ("ix_agent_reports_thread_id", "idx_agent_reports_scope_created"):
            if _has_index(inspector, "agent_reports", idx):
                op.drop_index(idx, table_name="agent_reports")
        op.drop_table("agent_reports")

    if _has_table(inspector, "agent_runs"):
        for idx in ("idx_agent_runs_user_created", "idx_agent_runs_thread_updated"):
            if _has_index(inspector, "agent_runs", idx):
                op.drop_index(idx, table_name="agent_runs")
        op.drop_table("agent_runs")

    if _has_table(inspector, "agent_messages"):
        for idx in ("ix_agent_messages_run_id", "idx_agent_messages_thread_created"):
            if _has_index(inspector, "agent_messages", idx):
                op.drop_index(idx, table_name="agent_messages")
        op.drop_table("agent_messages")

    if _has_table(inspector, "agent_threads"):
        if _has_index(inspector, "agent_threads", "idx_agent_threads_user_updated"):
            op.drop_index("idx_agent_threads_user_updated", table_name="agent_threads")
        op.drop_table("agent_threads")
