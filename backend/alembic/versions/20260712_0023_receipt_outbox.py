"""Add durable receipt outbox state and Alembic-managed DLQ.

Revision ID: 20260712_0023
Revises: 20260710_0022
Create Date: 2026-07-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260712_0023"
down_revision = "20260710_0022"
branch_labels = None
depends_on = None


def _tables(inspector) -> set[str]:
    return {str(name) for name in inspector.get_table_names()}


def _columns(inspector, table: str) -> set[str]:
    if table not in _tables(inspector):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table)}


def _indexes(inspector, table: str) -> set[str]:
    if table not in _tables(inspector):
        return set()
    return {str(index["name"]) for index in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = _columns(inspector, "receipt_processing_tasks")
    definitions = (
        ("payload_json", sa.Text(), True, None),
        ("force_reprocess", sa.Boolean(), False, sa.text("false")),
        ("publish_state", sa.String(length=20), False, "published"),
        ("publish_attempts", sa.Integer(), False, "0"),
        ("processing_attempts", sa.Integer(), False, "0"),
        ("next_retry_at", sa.DateTime(timezone=False), True, None),
        ("heartbeat_at", sa.DateTime(timezone=False), True, None),
        ("published_at", sa.DateTime(timezone=False), True, None),
        ("started_at", sa.DateTime(timezone=False), True, None),
        ("finished_at", sa.DateTime(timezone=False), True, None),
        ("last_error_kind", sa.String(length=40), True, None),
    )
    for name, column_type, nullable, server_default in definitions:
        if name in columns:
            continue
        op.add_column(
            "receipt_processing_tasks",
            sa.Column(
                name,
                column_type,
                nullable=nullable,
                server_default=server_default,
            ),
        )

    inspector = sa.inspect(bind)
    indexes = _indexes(inspector, "receipt_processing_tasks")
    if "idx_receipt_tasks_outbox" not in indexes:
        op.create_index(
            "idx_receipt_tasks_outbox",
            "receipt_processing_tasks",
            ["publish_state", "next_retry_at"],
            unique=False,
        )
    if "idx_receipt_tasks_heartbeat" not in indexes:
        op.create_index(
            "idx_receipt_tasks_heartbeat",
            "receipt_processing_tasks",
            ["status", "heartbeat_at"],
            unique=False,
        )

    inspector = sa.inspect(bind)
    if "receipt_task_dlq" not in _tables(inspector):
        op.create_table(
            "receipt_task_dlq",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("task_id", sa.String(length=255), nullable=False),
            sa.Column("tracking_task_id", sa.BigInteger(), nullable=True),
            sa.Column("chat_id", sa.BigInteger(), nullable=True),
            sa.Column("message_id", sa.BigInteger(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("error_text", sa.Text(), nullable=True),
            sa.Column("traceback", sa.Text(), nullable=True),
            sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reason", sa.String(length=40), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("replayed_at", sa.DateTime(timezone=True), nullable=True),
        )
    else:
        dlq_columns = _columns(inspector, "receipt_task_dlq")
        if "tracking_task_id" not in dlq_columns:
            op.add_column(
                "receipt_task_dlq",
                sa.Column("tracking_task_id", sa.BigInteger(), nullable=True),
            )
        if "reason" not in dlq_columns:
            op.add_column(
                "receipt_task_dlq",
                sa.Column("reason", sa.String(length=40), nullable=True),
            )

    inspector = sa.inspect(bind)
    dlq_indexes = _indexes(inspector, "receipt_task_dlq")
    for name, columns in (
        ("idx_receipt_task_dlq_task_id", ["task_id"]),
        ("idx_receipt_task_dlq_created", ["created_at"]),
        ("idx_receipt_task_dlq_chat_msg", ["chat_id", "message_id"]),
    ):
        if name not in dlq_indexes:
            op.create_index(name, "receipt_task_dlq", columns, unique=False)

    if bind.dialect.name == "postgresql":
        # Preserve legacy terminal failures as explicit DLQ evidence. These
        # rows predate payload_json, so they are not automatically replayable.
        op.execute(
            """
            INSERT INTO receipt_task_dlq (
                task_id, tracking_task_id, chat_id, message_id, payload_json,
                error_text, retries, reason
            )
            SELECT task.task_id,
                   task.id,
                   task.chat_id,
                   task.message_id,
                   json_build_object(
                       'source_chat_id', task.chat_id,
                       'source_message_id', task.message_id,
                       'raw_text', COALESCE(task.raw_message, '')
                   )::text,
                   task.error,
                   0,
                   'legacy_failed'
              FROM receipt_processing_tasks AS task
             WHERE task.status = 'failed'
               AND NOT EXISTS (
                   SELECT 1 FROM receipt_task_dlq AS dlq
                    WHERE dlq.tracking_task_id = task.id
                      AND dlq.reason = 'legacy_failed'
               )
            """
        )
        op.execute(
            """
            UPDATE receipt_processing_tasks
               SET status = 'dead',
                   publish_state = 'dead',
                   last_error_kind = 'legacy_failed',
                   finished_at = COALESCE(finished_at, updated_at, NOW())
             WHERE status = 'failed'
            """
        )

    inspector = sa.inspect(bind)
    transaction_indexes = _indexes(inspector, "transactions")
    if "uq_transactions_fingerprint" in transaction_indexes:
        op.drop_index("uq_transactions_fingerprint", table_name="transactions")
    transaction_indexes = _indexes(sa.inspect(bind), "transactions")
    if "idx_transactions_fingerprint_candidate" not in transaction_indexes:
        op.create_index(
            "idx_transactions_fingerprint_candidate",
            "transactions",
            ["fingerprint"],
            unique=False,
            postgresql_where=sa.text("fingerprint IS NOT NULL"),
        )

    monitor_columns = _columns(sa.inspect(bind), "monitored_bot_chats")
    for name, column_type, nullable, server_default in (
        ("scan_cursor_message_id", sa.BigInteger(), False, "0"),
        ("scan_backfill_from_message_id", sa.BigInteger(), True, None),
        ("scan_backfill_target_message_id", sa.BigInteger(), True, None),
    ):
        if name not in monitor_columns:
            op.add_column(
                "monitored_bot_chats",
                sa.Column(
                    name,
                    column_type,
                    nullable=nullable,
                    server_default=server_default,
                ),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = _indexes(inspector, "receipt_processing_tasks")
    for name in ("idx_receipt_tasks_heartbeat", "idx_receipt_tasks_outbox"):
        if name in indexes:
            op.drop_index(name, table_name="receipt_processing_tasks")

    columns = _columns(sa.inspect(bind), "receipt_processing_tasks")
    for name in (
        "last_error_kind",
        "finished_at",
        "started_at",
        "published_at",
        "heartbeat_at",
        "next_retry_at",
        "processing_attempts",
        "publish_attempts",
        "publish_state",
        "force_reprocess",
        "payload_json",
    ):
        if name in columns:
            op.drop_column("receipt_processing_tasks", name)

    monitor_columns = _columns(sa.inspect(bind), "monitored_bot_chats")
    for name in (
        "scan_backfill_target_message_id",
        "scan_backfill_from_message_id",
        "scan_cursor_message_id",
    ):
        if name in monitor_columns:
            op.drop_column("monitored_bot_chats", name)

    transaction_indexes = _indexes(sa.inspect(bind), "transactions")
    if "idx_transactions_fingerprint_candidate" in transaction_indexes:
        op.drop_index(
            "idx_transactions_fingerprint_candidate",
            table_name="transactions",
        )

    # receipt_task_dlq may predate Alembic (legacy migration 010). Keep terminal
    # failure evidence on downgrade instead of destructively dropping that table.
