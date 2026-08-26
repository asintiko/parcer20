import asyncio

from sqlalchemy.orm import sessionmaker

from database.models import MonitoredBotChat, TgHistoryCursor
from services import monitored_chat_sync
from services.history_loader import TgHistoryLoaderService


class FakeHistory:
    def __init__(self, highest_id: int) -> None:
        self.ids = list(range(highest_id, 0, -1))
        self.calls: list[int] = []
        self.fail_once_from: int | None = None

    def extend_to(self, highest_id: int) -> None:
        self.ids = list(range(highest_id, 0, -1))

    async def fetch(self, *, chat_id: int, from_message_id: int, limit: int):
        _ = chat_id
        self.calls.append(from_message_id)
        if self.fail_once_from == from_message_id:
            self.fail_once_from = None
            raise RuntimeError("temporary fetch failure")
        eligible = [
            message_id
            for message_id in self.ids
            if from_message_id == 0 or message_id < from_message_id
        ]
        return [
            {"id": message_id, "date": message_id, "text": f"receipt {message_id}"}
            for message_id in eligible[:limit]
        ]


class RecordingPersister:
    def __init__(self) -> None:
        self.persisted: set[int] = set()
        self.fail_id_once: int | None = None
        self.rollback_on_failure = False
        self.raise_once = False

    def persist(self, db, chat_id, chat_title, messages):
        _ = chat_id, chat_title
        ids = {int(message["id"]) for message in messages}
        if self.raise_once:
            self.raise_once = False
            db.rollback()
            raise RuntimeError("temporary persist failure")
        if self.fail_id_once is not None and self.fail_id_once in ids:
            failed_id = self.fail_id_once
            self.fail_id_once = None
            self.persisted.update(ids - {failed_id})
            if self.rollback_on_failure:
                db.rollback()
            return len(ids) - 1, {failed_id}
        self.persisted.update(ids)
        return len(ids), set()


def _seed_chat(db_session, *, monitor_cursor_message_id: int = 50):
    chat = MonitoredBotChat(chat_id=1001, enabled=True, chat_title="sync test")
    cursor = TgHistoryCursor(
        chat_id=chat.chat_id,
        status="completed",
        cursor_message_id=17,
        loaded_count=23,
        error="manual marker",
        monitor_status="completed",
        monitor_cursor_message_id=monitor_cursor_message_id,
    )
    db_session.add_all([chat, cursor])
    db_session.commit()
    return chat


def _run_cycle(db_session, chat, history):
    return asyncio.run(
        monitored_chat_sync.sync_one_chat(
            db_session,
            chat,
            fetch_callable=history.fetch,
        )
    )


def _run_until_complete(db_session, chat, history, *, max_cycles: int = 5):
    results = []
    for _ in range(max_cycles):
        results.append(_run_cycle(db_session, chat, history))
        cursor = db_session.get(TgHistoryCursor, chat.chat_id)
        if cursor.monitor_backfill_target_message_id is None:
            return results
    raise AssertionError("backfill did not complete")


def test_more_than_500_messages_resume_without_gap(db_session, monkeypatch):
    chat = _seed_chat(db_session)
    history = FakeHistory(650)
    persister = RecordingPersister()
    monkeypatch.setattr(monitored_chat_sync, "_persist_messages", persister.persist)

    first = _run_cycle(db_session, chat, history)

    assert first["monitor_cursor_message_id"] == 50
    assert first["monitor_backfill_target_message_id"] == 650
    assert first["monitor_backfill_from_message_id"] == 151

    second = _run_cycle(db_session, chat, history)

    assert second["monitor_cursor_message_id"] == 650
    assert second["monitor_backfill_target_message_id"] is None
    assert persister.persisted == set(range(51, 651))
    assert history.calls == [0, 551, 451, 351, 251, 151, 51]


def test_new_messages_wait_for_next_window_during_backfill(db_session, monkeypatch):
    chat = _seed_chat(db_session)
    history = FakeHistory(650)
    persister = RecordingPersister()
    monkeypatch.setattr(monitored_chat_sync, "_persist_messages", persister.persist)

    first = _run_cycle(db_session, chat, history)
    assert first["monitor_backfill_target_message_id"] == 650

    history.extend_to(700)
    second = _run_cycle(db_session, chat, history)

    assert history.calls[5] == 151
    assert second["monitor_cursor_message_id"] == 650
    assert not set(range(651, 701)).intersection(persister.persisted)

    third = _run_cycle(db_session, chat, history)

    assert history.calls[-1] == 0
    assert third["monitor_cursor_message_id"] == 700
    assert persister.persisted == set(range(51, 701))


def test_fetch_failure_resumes_from_last_successful_page(db_session, monkeypatch):
    chat = _seed_chat(db_session)
    history = FakeHistory(650)
    history.fail_once_from = 551
    persister = RecordingPersister()
    monkeypatch.setattr(monitored_chat_sync, "_persist_messages", persister.persist)

    failed = _run_cycle(db_session, chat, history)

    assert failed["monitor_cursor_message_id"] == 50
    assert failed["monitor_backfill_target_message_id"] == 650
    assert failed["monitor_backfill_from_message_id"] == 551
    cursor = db_session.get(TgHistoryCursor, chat.chat_id)
    assert cursor.monitor_status == "failed"

    _run_until_complete(db_session, chat, history)

    cursor = db_session.get(TgHistoryCursor, chat.chat_id)
    assert cursor.monitor_cursor_message_id == 650
    assert cursor.monitor_backfill_target_message_id is None
    assert persister.persisted == set(range(51, 651))
    assert history.calls[:3] == [0, 551, 551]


def test_persist_failure_retries_whole_page_without_advancing(db_session, monkeypatch):
    chat = _seed_chat(db_session)
    history = FakeHistory(650)
    persister = RecordingPersister()
    persister.fail_id_once = 600
    persister.rollback_on_failure = True
    monkeypatch.setattr(monitored_chat_sync, "_persist_messages", persister.persist)

    failed = _run_cycle(db_session, chat, history)

    assert failed["monitor_cursor_message_id"] == 50
    assert failed["monitor_backfill_target_message_id"] == 650
    assert failed["monitor_backfill_from_message_id"] == 0
    assert 600 not in persister.persisted
    cursor = db_session.get(TgHistoryCursor, chat.chat_id)
    assert cursor.monitor_status == "partial"

    _run_until_complete(db_session, chat, history)

    cursor = db_session.get(TgHistoryCursor, chat.chat_id)
    assert cursor.monitor_cursor_message_id == 650
    assert cursor.monitor_backfill_target_message_id is None
    assert persister.persisted == set(range(51, 651))
    assert history.calls[:2] == [0, 0]


def test_persist_exception_keeps_page_continuation(db_session, monkeypatch):
    chat = _seed_chat(db_session)
    history = FakeHistory(650)
    persister = RecordingPersister()
    persister.raise_once = True
    monkeypatch.setattr(monitored_chat_sync, "_persist_messages", persister.persist)

    failed = _run_cycle(db_session, chat, history)

    assert failed["monitor_cursor_message_id"] == 50
    assert failed["monitor_backfill_target_message_id"] == 650
    assert failed["monitor_backfill_from_message_id"] == 0
    cursor = db_session.get(TgHistoryCursor, chat.chat_id)
    assert cursor.monitor_status == "failed"

    _run_until_complete(db_session, chat, history)

    cursor = db_session.get(TgHistoryCursor, chat.chat_id)
    assert cursor.monitor_cursor_message_id == 650
    assert cursor.monitor_backfill_target_message_id is None
    assert persister.persisted == set(range(51, 651))
    assert history.calls[:2] == [0, 0]


def test_monitor_sync_does_not_touch_manual_loader_fields(db_session, monkeypatch):
    chat = _seed_chat(db_session)
    history = FakeHistory(75)
    persister = RecordingPersister()
    monkeypatch.setattr(monitored_chat_sync, "_persist_messages", persister.persist)

    _run_cycle(db_session, chat, history)

    cursor = db_session.get(TgHistoryCursor, chat.chat_id)
    assert cursor.status == "completed"
    assert cursor.cursor_message_id == 17
    assert cursor.loaded_count == 23
    assert cursor.error == "manual marker"


def test_manual_loader_restart_preserves_monitor_continuation(db_session):
    chat = _seed_chat(db_session)
    cursor = db_session.get(TgHistoryCursor, chat.chat_id)
    cursor.monitor_status = "running"
    cursor.monitor_backfill_from_message_id = 151
    cursor.monitor_backfill_target_message_id = 650
    db_session.commit()

    class EmptyManager:
        async def iter_chat_history(self, **kwargs):
            _ = kwargs
            if False:
                yield []

    service = TgHistoryLoaderService(
        manager=EmptyManager(),
        session_factory=sessionmaker(bind=db_session.get_bind()),
    )
    asyncio.run(
        service._run_job(
            chat_id=chat.chat_id,
            max_messages=None,
            restart=True,
            date_filters=None,
        )
    )

    db_session.expire_all()
    cursor = db_session.get(TgHistoryCursor, chat.chat_id)
    assert cursor.monitor_status == "running"
    assert cursor.monitor_cursor_message_id == 50
    assert cursor.monitor_backfill_from_message_id == 151
    assert cursor.monitor_backfill_target_message_id == 650


def test_concurrent_same_chat_sync_does_not_double_run(db_session, monkeypatch):
    chat = _seed_chat(db_session)
    entered = asyncio.Event()
    release = asyncio.Event()
    fetch_calls = 0

    async def blocking_fetch(*, chat_id, from_message_id, limit):
        nonlocal fetch_calls
        _ = chat_id, from_message_id, limit
        fetch_calls += 1
        entered.set()
        await release.wait()
        return []

    monkeypatch.setattr(
        monitored_chat_sync,
        "_persist_messages",
        RecordingPersister().persist,
    )

    async def run_both():
        first = asyncio.create_task(
            monitored_chat_sync.sync_one_chat(
                db_session, chat, fetch_callable=blocking_fetch
            )
        )
        await entered.wait()
        second = await monitored_chat_sync.sync_one_chat(
            db_session, chat, fetch_callable=blocking_fetch
        )
        release.set()
        return await first, second

    first, second = asyncio.run(run_both())

    assert first.get("skipped") is not True
    assert second == {
        "chat_id": chat.chat_id,
        "skipped": True,
        "reason": "already_running",
    }
    assert fetch_calls == 1
