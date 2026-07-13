import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260712_0023_receipt_outbox.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("receipt_outbox_0023", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_upgrades_legacy_tracking_dlq_and_fingerprint_index():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    transactions = sa.Table(
        "transactions",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=True),
    )
    sa.Index(
        "uq_transactions_fingerprint",
        transactions.c.fingerprint,
        unique=True,
    )
    sa.Table(
        "receipt_processing_tasks",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.String(255), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    sa.Table(
        "monitored_bot_chats",
        metadata,
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
    )
    sa.Table(
        "receipt_task_dlq",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("chat_id", sa.BigInteger()),
        sa.Column("message_id", sa.BigInteger()),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("error_text", sa.Text()),
        sa.Column("traceback", sa.Text()),
        sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("replayed_at", sa.DateTime(timezone=True)),
    )
    metadata.create_all(engine)

    migration = _load_migration()
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()

        inspector = sa.inspect(connection)
        task_columns = {
            column["name"]
            for column in inspector.get_columns("receipt_processing_tasks")
        }
        assert {
            "payload_json",
            "publish_state",
            "publish_attempts",
            "processing_attempts",
            "next_retry_at",
            "heartbeat_at",
        }.issubset(task_columns)
        monitor_columns = {
            column["name"] for column in inspector.get_columns("monitored_bot_chats")
        }
        assert {
            "scan_cursor_message_id",
            "scan_backfill_from_message_id",
            "scan_backfill_target_message_id",
        }.issubset(monitor_columns)
        dlq_columns = {
            column["name"] for column in inspector.get_columns("receipt_task_dlq")
        }
        assert {"tracking_task_id", "reason"}.issubset(dlq_columns)
        transaction_indexes = {
            index["name"]: index for index in inspector.get_indexes("transactions")
        }
        assert "uq_transactions_fingerprint" not in transaction_indexes
        assert not transaction_indexes["idx_transactions_fingerprint_candidate"]["unique"]

        connection.execute(transactions.insert(), {"fingerprint": "same"})
        connection.execute(transactions.insert(), {"fingerprint": "same"})
