"""Add isolated monitored-chat sync progress.

Revision ID: 20260710_0022
Revises: 20260605_0021
Create Date: 2026-07-10
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260710_0022"
down_revision = "20260605_0021"
branch_labels = None
depends_on = None


def _column_names(inspector, table: str) -> set[str]:
    try:
        return {str(column["name"]) for column in inspector.get_columns(table)}
    except Exception:
        return set()


def _index_names(inspector, table: str) -> set[str]:
    try:
        return {str(index["name"]) for index in inspector.get_indexes(table)}
    except Exception:
        return set()


def _seed_monitor_cursors(bind) -> None:
    cursors = sa.table(
        "tg_history_cursors",
        sa.column("chat_id", sa.BigInteger()),
        sa.column("status", sa.String()),
        sa.column("cursor_message_id", sa.BigInteger()),
        sa.column("loaded_count", sa.BigInteger()),
        sa.column("lag_messages", sa.BigInteger()),
        sa.column("lag_seconds", sa.BigInteger()),
        sa.column("monitor_cursor_message_id", sa.BigInteger()),
        sa.column("monitor_status", sa.String()),
    )
    messages = sa.table(
        "tg_chat_messages",
        sa.column("chat_id", sa.BigInteger()),
        sa.column("message_id", sa.BigInteger()),
    )
    message_max = (
        sa.select(
            messages.c.chat_id,
            sa.func.max(messages.c.message_id).label("max_message_id"),
        )
        .group_by(messages.c.chat_id)
        .subquery()
    )

    missing_cursors = sa.insert(cursors).from_select(
        [
            "chat_id",
            "status",
            "cursor_message_id",
            "loaded_count",
            "lag_messages",
            "lag_seconds",
            "monitor_cursor_message_id",
            "monitor_status",
        ],
        sa.select(
            message_max.c.chat_id,
            sa.literal("idle"),
            sa.literal(0),
            sa.literal(0),
            sa.literal(0),
            sa.literal(0),
            message_max.c.max_message_id,
            sa.literal("idle"),
        ).where(
            ~sa.exists(
                sa.select(sa.literal(1)).where(
                    cursors.c.chat_id == message_max.c.chat_id
                )
            )
        ),
    )
    bind.execute(missing_cursors)

    max_for_chat = (
        sa.select(sa.func.max(messages.c.message_id))
        .where(messages.c.chat_id == cursors.c.chat_id)
        .scalar_subquery()
    )
    bind.execute(
        sa.update(cursors).values(
            monitor_cursor_message_id=sa.func.coalesce(max_for_chat, 0)
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = _column_names(inspector, "tg_history_cursors")

    definitions = (
        ("monitor_cursor_message_id", sa.BigInteger(), False, "0"),
        ("monitor_backfill_from_message_id", sa.BigInteger(), True, None),
        ("monitor_backfill_target_message_id", sa.BigInteger(), True, None),
        ("monitor_status", sa.String(length=20), False, "idle"),
        ("monitor_error", sa.Text(), True, None),
        ("monitor_last_batch_at", sa.DateTime(timezone=True), True, None),
    )
    for name, column_type, nullable, server_default in definitions:
        if name not in columns:
            op.add_column(
                "tg_history_cursors",
                sa.Column(
                    name,
                    column_type,
                    nullable=nullable,
                    server_default=server_default,
                ),
            )

    _seed_monitor_cursors(bind)

    inspector = sa.inspect(bind)
    if "idx_tg_history_cursors_monitor_status" not in _index_names(
        inspector, "tg_history_cursors"
    ):
        op.create_index(
            "idx_tg_history_cursors_monitor_status",
            "tg_history_cursors",
            ["monitor_status"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "idx_tg_history_cursors_monitor_status" in _index_names(
        inspector, "tg_history_cursors"
    ):
        op.drop_index(
            "idx_tg_history_cursors_monitor_status",
            table_name="tg_history_cursors",
        )

    columns = _column_names(sa.inspect(bind), "tg_history_cursors")
    for name in (
        "monitor_last_batch_at",
        "monitor_error",
        "monitor_status",
        "monitor_backfill_target_message_id",
        "monitor_backfill_from_message_id",
        "monitor_cursor_message_id",
    ):
        if name in columns:
            op.drop_column("tg_history_cursors", name)
