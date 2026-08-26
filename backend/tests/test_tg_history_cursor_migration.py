import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260710_0022_tg_history_backfill_continuation.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("tg_history_cursor_0022", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_seeds_monitor_cursor_without_changing_legacy_cursor():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    cursors = sa.Table(
        "tg_history_cursors",
        metadata,
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="idle"),
        sa.Column("cursor_message_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("loaded_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("lag_messages", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("lag_seconds", sa.BigInteger(), nullable=False, server_default="0"),
    )
    messages = sa.Table(
        "tg_chat_messages",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
    )
    metadata.create_all(engine)

    migration = _load_migration()
    with engine.begin() as connection:
        connection.execute(
            cursors.insert(),
            {
                "chat_id": 1001,
                "status": "running",
                "cursor_message_id": 7,
                "loaded_count": 11,
                "lag_messages": 0,
                "lag_seconds": 0,
            },
        )
        connection.execute(
            messages.insert(),
            [
                {"chat_id": 1001, "message_id": 19},
                {"chat_id": 1001, "message_id": 23},
                {"chat_id": 2002, "message_id": 41},
            ],
        )
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()

        rows = {
            int(row.chat_id): row
            for row in connection.execute(
                sa.text("SELECT * FROM tg_history_cursors ORDER BY chat_id")
            ).mappings()
        }
        assert rows[1001]["status"] == "running"
        assert rows[1001]["cursor_message_id"] == 7
        assert rows[1001]["loaded_count"] == 11
        assert rows[1001]["monitor_cursor_message_id"] == 23
        assert rows[1001]["monitor_status"] == "idle"
        assert rows[2002]["cursor_message_id"] == 0
        assert rows[2002]["monitor_cursor_message_id"] == 41

        with Operations.context(context):
            migration.downgrade()

        columns = {
            column["name"]
            for column in sa.inspect(connection).get_columns("tg_history_cursors")
        }
        assert "monitor_cursor_message_id" not in columns
        assert "cursor_message_id" in columns

        with Operations.context(context):
            migration.upgrade()

        reseeded = connection.execute(
            sa.text(
                "SELECT cursor_message_id, monitor_cursor_message_id "
                "FROM tg_history_cursors WHERE chat_id = 1001"
            )
        ).mappings().one()
        assert reseeded["cursor_message_id"] == 7
        assert reseeded["monitor_cursor_message_id"] == 23
