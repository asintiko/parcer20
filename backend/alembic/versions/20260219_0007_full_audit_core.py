"""Full audit core schema updates (history loader, automation version, sync/search indexes).

Revision ID: 20260219_0007
Revises: 20260218_0006
Create Date: 2026-02-19 01:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision = "20260219_0007"
down_revision = "20260218_0006"
branch_labels = None
depends_on = None


def _has_table(inspector: Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector: Inspector, table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _has_index(inspector: Inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "tg_chat_messages"):
        op.create_table(
            "tg_chat_messages",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("message_id", sa.BigInteger(), nullable=False),
            sa.Column("message_date", sa.DateTime(timezone=False), nullable=True),
            sa.Column("is_outgoing", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("sender_id", sa.BigInteger(), nullable=True),
            sa.Column("text", sa.Text(), nullable=True),
            sa.Column("raw_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("chat_id", "message_id", name="uq_tg_chat_messages_chat_message"),
        )

    if not _has_table(inspector, "tg_history_cursors"):
        op.create_table(
            "tg_history_cursors",
            sa.Column("chat_id", sa.BigInteger(), primary_key=True, nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="idle"),
            sa.Column("cursor_message_id", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("loaded_count", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )

    inspector = sa.inspect(bind)

    if _has_table(inspector, "automation_tasks") and not _has_column(inspector, "automation_tasks", "version"):
        op.add_column(
            "automation_tasks",
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        )

    if _has_table(inspector, "tg_chat_messages"):
        if not _has_index(inspector, "tg_chat_messages", "idx_tg_chat_messages_chat_msg"):
            op.create_index("idx_tg_chat_messages_chat_msg", "tg_chat_messages", ["chat_id", "message_id"])
        if not _has_index(inspector, "tg_chat_messages", "idx_tg_chat_messages_chat_date"):
            op.create_index("idx_tg_chat_messages_chat_date", "tg_chat_messages", ["chat_id", "message_date"])
        if not _has_index(inspector, "tg_chat_messages", "idx_tg_chat_messages_updated"):
            op.create_index("idx_tg_chat_messages_updated", "tg_chat_messages", ["updated_at"])

    if _has_table(inspector, "tg_history_cursors"):
        if not _has_index(inspector, "tg_history_cursors", "idx_tg_history_cursors_status"):
            op.create_index("idx_tg_history_cursors_status", "tg_history_cursors", ["status"])
        if not _has_index(inspector, "tg_history_cursors", "idx_tg_history_cursors_updated"):
            op.create_index("idx_tg_history_cursors_updated", "tg_history_cursors", ["updated_at"])

    if _has_table(inspector, "transactions"):
        if not _has_index(inspector, "transactions", "idx_transactions_source_msg"):
            op.create_index("idx_transactions_source_msg", "transactions", ["source_chat_id", "source_message_id"])
        if not _has_index(inspector, "transactions", "idx_transactions_updated_id"):
            op.create_index("idx_transactions_updated_id", "transactions", ["updated_at", "id"])

    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_transactions_raw_message_trgm "
            "ON transactions USING gin (raw_message gin_trgm_ops)"
        )

    if _has_table(inspector, "sync_deletions"):
        if not _has_index(inspector, "sync_deletions", "idx_sync_deletions_table_deleted_id"):
            op.create_index(
                "idx_sync_deletions_table_deleted_id",
                "sync_deletions",
                ["table_name", "deleted_at", "id"],
            )
        if not _has_index(inspector, "sync_deletions", "idx_sync_deletions_cleanup"):
            op.create_index("idx_sync_deletions_cleanup", "sync_deletions", ["deleted_at", "id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "sync_deletions"):
        if _has_index(inspector, "sync_deletions", "idx_sync_deletions_cleanup"):
            op.drop_index("idx_sync_deletions_cleanup", table_name="sync_deletions")
        if _has_index(inspector, "sync_deletions", "idx_sync_deletions_table_deleted_id"):
            op.drop_index("idx_sync_deletions_table_deleted_id", table_name="sync_deletions")

    if _has_table(inspector, "transactions"):
        if _has_index(inspector, "transactions", "idx_transactions_updated_id"):
            op.drop_index("idx_transactions_updated_id", table_name="transactions")
        if _has_index(inspector, "transactions", "idx_transactions_source_msg"):
            op.drop_index("idx_transactions_source_msg", table_name="transactions")
        if bind.dialect.name == "postgresql":
            op.execute("DROP INDEX IF EXISTS idx_transactions_raw_message_trgm")

    if _has_table(inspector, "automation_tasks") and _has_column(inspector, "automation_tasks", "version"):
        op.drop_column("automation_tasks", "version")

    if _has_table(inspector, "tg_history_cursors"):
        if _has_index(inspector, "tg_history_cursors", "idx_tg_history_cursors_updated"):
            op.drop_index("idx_tg_history_cursors_updated", table_name="tg_history_cursors")
        if _has_index(inspector, "tg_history_cursors", "idx_tg_history_cursors_status"):
            op.drop_index("idx_tg_history_cursors_status", table_name="tg_history_cursors")
        op.drop_table("tg_history_cursors")

    if _has_table(inspector, "tg_chat_messages"):
        if _has_index(inspector, "tg_chat_messages", "idx_tg_chat_messages_updated"):
            op.drop_index("idx_tg_chat_messages_updated", table_name="tg_chat_messages")
        if _has_index(inspector, "tg_chat_messages", "idx_tg_chat_messages_chat_date"):
            op.drop_index("idx_tg_chat_messages_chat_date", table_name="tg_chat_messages")
        if _has_index(inspector, "tg_chat_messages", "idx_tg_chat_messages_chat_msg"):
            op.drop_index("idx_tg_chat_messages_chat_msg", table_name="tg_chat_messages")
        op.drop_table("tg_chat_messages")
