"""Expand AI agent runtime for V4 thread lifecycle, run events, telegram cache audit, and incidents.

Revision ID: 20260327_0015
Revises: 20260327_0014
Create Date: 2026-03-27 23:10:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260327_0015"
down_revision = "20260327_0014"
branch_labels = None
depends_on = None


def _has_table(inspector: Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector: Inspector, table_name: str, column_name: str) -> bool:
    return any(col.get("name") == column_name for col in inspector.get_columns(table_name))


def _has_index(inspector: Inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def _add_column_if_missing(inspector: Inspector, table_name: str, column: sa.Column) -> None:
    if _has_table(inspector, table_name) and not _has_column(inspector, table_name, column.name):
        op.add_column(table_name, column)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    if _has_table(inspector, "agent_threads"):
        _add_column_if_missing(inspector, "agent_threads", sa.Column("last_message_preview", sa.String(length=500), nullable=True))
        _add_column_if_missing(inspector, "agent_threads", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        _add_column_if_missing(inspector, "agent_threads", sa.Column("archived_by_user_id", sa.BigInteger(), nullable=True))
        _add_column_if_missing(inspector, "agent_threads", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        _add_column_if_missing(inspector, "agent_threads", sa.Column("deleted_by_user_id", sa.BigInteger(), nullable=True))
        _add_column_if_missing(inspector, "agent_threads", sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True))
        if not _has_index(inspector, "agent_threads", "idx_agent_threads_archived"):
            op.create_index("idx_agent_threads_archived", "agent_threads", ["created_by_user_id", "archived_at"], unique=False)
        if not _has_index(inspector, "agent_threads", "idx_agent_threads_deleted"):
            op.create_index("idx_agent_threads_deleted", "agent_threads", ["created_by_user_id", "deleted_at", "purge_after"], unique=False)

    if not _has_table(inspector, "agent_run_events"):
        op.create_table(
            "agent_run_events",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("run_id", sa.Uuid(), nullable=False),
            sa.Column("event_type", sa.String(length=40), nullable=False),
            sa.Column("label", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.CheckConstraint(
                "event_type IN ('planning_started', 'tool_selected', 'tool_started', 'tool_progress', 'tool_finished', 'awaiting_confirmation', 'completed', 'failed')",
                name="check_agent_run_event_type",
            ),
            sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="check_agent_run_event_status"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_agent_run_events_run_created", "agent_run_events", ["run_id", "created_at"], unique=False)

    if _has_table(inspector, "tg_chat_messages"):
        for column in (
            sa.Column("content_type", sa.String(length=40), nullable=True),
            sa.Column("media_kind", sa.String(length=40), nullable=True),
            sa.Column("looks_like_receipt", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("processing_status", sa.String(length=30), nullable=True),
            sa.Column("processing_error_code", sa.String(length=80), nullable=True),
            sa.Column("processing_error_text", sa.Text(), nullable=True),
            sa.Column("duplicate_status", sa.String(length=30), nullable=True),
            sa.Column("message_hash", sa.String(length=128), nullable=True),
            sa.Column("source_chat_title_snapshot", sa.String(length=255), nullable=True),
        ):
            _add_column_if_missing(inspector, "tg_chat_messages", column)
        for idx_name, columns in (
            ("idx_tg_chat_messages_receipt_like", ["looks_like_receipt"]),
            ("idx_tg_chat_messages_processing_status", ["processing_status"]),
            ("idx_tg_chat_messages_duplicate_status", ["duplicate_status"]),
            ("idx_tg_chat_messages_message_hash", ["message_hash"]),
        ):
            if not _has_index(inspector, "tg_chat_messages", idx_name):
                op.create_index(idx_name, "tg_chat_messages", columns, unique=False)
        if bind.dialect.name == "postgresql":
            op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            op.execute(
                "CREATE INDEX IF NOT EXISTS idx_tg_chat_messages_text_trgm "
                "ON tg_chat_messages USING gin (text gin_trgm_ops)"
            )

    if _has_table(inspector, "monitored_bot_chats"):
        for column in (
            sa.Column("last_history_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_realtime_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_receipt_candidate_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_sync_issue_at", sa.DateTime(timezone=True), nullable=True),
        ):
            _add_column_if_missing(inspector, "monitored_bot_chats", column)
        if not _has_index(inspector, "monitored_bot_chats", "idx_monitored_bot_chats_enabled"):
            op.create_index("idx_monitored_bot_chats_enabled", "monitored_bot_chats", ["enabled"], unique=False)
        if not _has_index(inspector, "monitored_bot_chats", "idx_monitored_bot_chats_sync_health"):
            op.create_index(
                "idx_monitored_bot_chats_sync_health",
                "monitored_bot_chats",
                ["last_history_sync_at", "last_realtime_seen_at"],
                unique=False,
            )

    if _has_table(inspector, "tg_history_cursors"):
        for column in (
            sa.Column("last_batch_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("lag_messages", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("lag_seconds", sa.BigInteger(), nullable=False, server_default="0"),
        ):
            _add_column_if_missing(inspector, "tg_history_cursors", column)
        if not _has_index(inspector, "tg_history_cursors", "idx_tg_history_cursors_lag"):
            op.create_index("idx_tg_history_cursors_lag", "tg_history_cursors", ["lag_messages", "lag_seconds"], unique=False)

    if not _has_table(inspector, "receipt_processing_incidents"):
        op.create_table(
            "receipt_processing_incidents",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("message_id", sa.BigInteger(), nullable=True),
            sa.Column("transaction_id", sa.BigInteger(), nullable=True),
            sa.Column("task_id", sa.BigInteger(), nullable=True),
            sa.Column("incident_type", sa.String(length=50), nullable=False),
            sa.Column("severity", sa.String(length=20), nullable=False, server_default="medium"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
            sa.Column("reason_code", sa.String(length=80), nullable=True),
            sa.Column("reason_text", sa.Text(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="check_receipt_incident_severity"),
            sa.CheckConstraint("status IN ('open', 'acknowledged', 'resolved', 'ignored')", name="check_receipt_incident_status"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_receipt_incidents_chat_message", "receipt_processing_incidents", ["chat_id", "message_id"], unique=False)
        op.create_index("idx_receipt_incidents_status_seen", "receipt_processing_incidents", ["status", "last_seen_at"], unique=False)
        op.create_index("idx_receipt_incidents_type_status", "receipt_processing_incidents", ["incident_type", "status"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)

    if _has_table(inspector, "receipt_processing_incidents"):
        for idx_name in ("idx_receipt_incidents_type_status", "idx_receipt_incidents_status_seen", "idx_receipt_incidents_chat_message"):
            if _has_index(inspector, "receipt_processing_incidents", idx_name):
                op.drop_index(idx_name, table_name="receipt_processing_incidents")
        op.drop_table("receipt_processing_incidents")

    if _has_table(inspector, "tg_history_cursors"):
        if _has_index(inspector, "tg_history_cursors", "idx_tg_history_cursors_lag"):
            op.drop_index("idx_tg_history_cursors_lag", table_name="tg_history_cursors")
        for column_name in ("lag_seconds", "lag_messages", "last_batch_at"):
            if _has_column(inspector, "tg_history_cursors", column_name):
                op.drop_column("tg_history_cursors", column_name)

    if _has_table(inspector, "monitored_bot_chats"):
        for idx_name in ("idx_monitored_bot_chats_sync_health", "idx_monitored_bot_chats_enabled"):
            if _has_index(inspector, "monitored_bot_chats", idx_name):
                op.drop_index(idx_name, table_name="monitored_bot_chats")
        for column_name in ("last_sync_issue_at", "last_receipt_candidate_at", "last_realtime_seen_at", "last_history_sync_at"):
            if _has_column(inspector, "monitored_bot_chats", column_name):
                op.drop_column("monitored_bot_chats", column_name)

    if _has_table(inspector, "tg_chat_messages"):
        if bind.dialect.name == "postgresql":
            op.execute("DROP INDEX IF EXISTS idx_tg_chat_messages_text_trgm")
        for idx_name in (
            "idx_tg_chat_messages_message_hash",
            "idx_tg_chat_messages_duplicate_status",
            "idx_tg_chat_messages_processing_status",
            "idx_tg_chat_messages_receipt_like",
        ):
            if _has_index(inspector, "tg_chat_messages", idx_name):
                op.drop_index(idx_name, table_name="tg_chat_messages")
        for column_name in (
            "source_chat_title_snapshot",
            "message_hash",
            "duplicate_status",
            "processing_error_text",
            "processing_error_code",
            "processing_status",
            "looks_like_receipt",
            "media_kind",
            "content_type",
        ):
            if _has_column(inspector, "tg_chat_messages", column_name):
                op.drop_column("tg_chat_messages", column_name)

    if _has_table(inspector, "agent_run_events"):
        if _has_index(inspector, "agent_run_events", "idx_agent_run_events_run_created"):
            op.drop_index("idx_agent_run_events_run_created", table_name="agent_run_events")
        op.drop_table("agent_run_events")

    if _has_table(inspector, "agent_threads"):
        for idx_name in ("idx_agent_threads_deleted", "idx_agent_threads_archived"):
            if _has_index(inspector, "agent_threads", idx_name):
                op.drop_index(idx_name, table_name="agent_threads")
        for column_name in (
            "purge_after",
            "deleted_by_user_id",
            "deleted_at",
            "archived_by_user_id",
            "archived_at",
            "last_message_preview",
        ):
            if _has_column(inspector, "agent_threads", column_name):
                op.drop_column("agent_threads", column_name)
