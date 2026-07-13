import asyncio

import pytest
from sqlalchemy.orm import sessionmaker

from database.models import MonitoredBotChat, ReceiptProcessingTask
from services.tg_auto_monitor_service import TgAutoMonitorService


class FakeManager:
    def __init__(self, messages=None):
        self.messages = list(messages or [])
        self.history_calls = []
        self.message_calls = []

    async def get_message(self, *, chat_id, message_id):
        self.message_calls.append((chat_id, message_id))
        for message in self.messages:
            if int(message["id"]) == int(message_id):
                return message
        return None

    async def get_messages(self, *, chat_id, limit, from_message_id):
        self.history_calls.append((chat_id, from_message_id))
        eligible = [
            message
            for message in self.messages
            if from_message_id == 0 or int(message["id"]) < int(from_message_id)
        ]
        eligible.sort(key=lambda message: int(message["id"]), reverse=True)
        return {"items": eligible[:limit]}


def _session_factory(db_session):
    return sessionmaker(bind=db_session.get_bind())


@pytest.fixture(autouse=True)
def _receipt_cutoff(monkeypatch):
    monkeypatch.setenv("RECEIPT_MIN_DATE", "2026-01-01")


def _message(message_id, *, date="2026-07-12T10:00:00Z"):
    return {
        "id": message_id,
        "date": date,
        "text": f"Оплата HUMO receipt на сумму {message_id} UZS",
    }


def _seed_monitor(db_session, *, chat_id=1001, scan_cursor=0):
    monitor = MonitoredBotChat(
        chat_id=chat_id,
        enabled=True,
        filter_mode="all",
        chat_type="private",
        scan_cursor_message_id=scan_cursor,
    )
    db_session.add(monitor)
    db_session.commit()
    return monitor


@pytest.mark.asyncio
async def test_process_single_fetches_metadata_and_only_queues_celery_task(
    db_session, monkeypatch
):
    _seed_monitor(db_session)
    manager = FakeManager([_message(42)])
    factory = _session_factory(db_session)
    service = TgAutoMonitorService(manager, factory)
    queued_payloads = []

    def fake_queue(payload, force=False):
        queued_payloads.append((payload, force))
        with factory() as db:
            db.add(
                ReceiptProcessingTask(
                    task_id="task-42",
                    chat_id=1001,
                    message_id=42,
                    status="queued",
                )
            )
            db.commit()
        return "task-42"

    monkeypatch.setattr("services.tg_auto_monitor_service.queue_receipt_task", fake_queue)

    assert await service._process_single(1001, 42) is True
    assert manager.message_calls == [(1001, 42)]
    assert queued_payloads == [
        (
            {
                "source_type": "AUTO",
                "source_chat_id": 1001,
                "source_message_id": 42,
                "source_received_at": "2026-07-12T10:00:00Z",
                "raw_text": "Оплата HUMO receipt на сумму 42 UZS",
                "added_via": "tdlib",
            },
            False,
        )
    ]


@pytest.mark.asyncio
async def test_stale_redis_lease_does_not_suppress_database_retry(db_session, monkeypatch):
    service = TgAutoMonitorService(FakeManager(), _session_factory(db_session))
    service._lease_wait_sec = 0.01
    processed = []

    async def stale_lease(*_args):
        return ""

    async def fake_process(chat_id, message_id):
        processed.append((chat_id, message_id))
        return True

    monkeypatch.setattr(service, "_reserve_recent_message", stale_lease)
    monkeypatch.setattr(service, "_process_single", fake_process)
    worker = asyncio.create_task(service._worker(0))
    try:
        assert await service._enqueue(1001, 77) is True
    finally:
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker

    assert processed == [(1001, 77)]


@pytest.mark.asyncio
async def test_concurrent_realtime_delivery_shares_one_local_enqueue(db_session, monkeypatch):
    factory = _session_factory(db_session)
    service = TgAutoMonitorService(FakeManager(), factory)
    processed = []

    async def no_redis(*_args):
        return None

    async def fake_process(chat_id, message_id):
        processed.append((chat_id, message_id))
        await asyncio.sleep(0)
        with factory() as db:
            db.add(
                ReceiptProcessingTask(
                    task_id="task-88",
                    chat_id=chat_id,
                    message_id=message_id,
                    status="queued",
                )
            )
            db.commit()
        return True

    monkeypatch.setattr(service, "_reserve_recent_message", no_redis)
    monkeypatch.setattr(service, "_process_single", fake_process)
    worker = asyncio.create_task(service._worker(0))
    try:
        results = await asyncio.gather(
            service._enqueue(1001, 88),
            service._enqueue(1001, 88),
        )
    finally:
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker

    assert results == [True, True]
    assert processed == [(1001, 88)]
    assert service.queue.maxsize > 0


@pytest.mark.asyncio
async def test_catchup_failure_keeps_cursor_before_failed_page(db_session, monkeypatch):
    _seed_monitor(db_session)
    service = TgAutoMonitorService(
        FakeManager([_message(3), _message(2), _message(1)]),
        _session_factory(db_session),
    )
    attempts = []

    async def fail_second(chat_id, message_id):
        attempts.append((chat_id, message_id))
        return message_id != 2

    monkeypatch.setattr(service, "_enqueue", fail_second)
    await service._catchup_chat(1001)

    db_session.expire_all()
    monitor = db_session.get(MonitoredBotChat, 1001)
    assert attempts == [(1001, 1), (1001, 2)]
    assert monitor.scan_cursor_message_id == 0
    assert monitor.scan_backfill_from_message_id == 0
    assert monitor.scan_backfill_target_message_id == 3
    assert monitor.last_error == "enqueue_failed:2"


@pytest.mark.asyncio
async def test_bounded_catchup_resumes_persisted_pages_and_advances_contiguously(
    db_session, monkeypatch
):
    _seed_monitor(db_session, scan_cursor=50)
    manager = FakeManager([_message(message_id) for message_id in range(1, 251)])
    service = TgAutoMonitorService(manager, _session_factory(db_session))
    service._catchup_max_batches = 1
    service._catchup_max_seconds = 60
    queued = []

    async def durable_enqueue(chat_id, message_id):
        queued.append((chat_id, message_id))
        return True

    monkeypatch.setattr(service, "_enqueue", durable_enqueue)

    await service._catchup_chat(1001)
    db_session.expire_all()
    first = db_session.get(MonitoredBotChat, 1001)
    assert first.scan_cursor_message_id == 50
    assert first.scan_backfill_from_message_id == 151
    assert first.scan_backfill_target_message_id == 250

    await service._catchup_chat(1001)
    db_session.expire_all()
    second = db_session.get(MonitoredBotChat, 1001)
    assert second.scan_cursor_message_id == 50
    assert second.scan_backfill_from_message_id == 51

    await service._catchup_chat(1001)
    db_session.expire_all()
    completed = db_session.get(MonitoredBotChat, 1001)
    assert completed.scan_cursor_message_id == 250
    assert completed.scan_backfill_from_message_id is None
    assert completed.scan_backfill_target_message_id is None
    assert {message_id for _, message_id in queued} == set(range(51, 251))
    assert manager.history_calls == [(1001, 0), (1001, 151), (1001, 51)]


@pytest.mark.asyncio
async def test_realtime_enqueue_never_jumps_scan_cursor(db_session, monkeypatch):
    _seed_monitor(db_session, scan_cursor=10)
    service = TgAutoMonitorService(FakeManager(), _session_factory(db_session))

    monkeypatch.setattr(service, "_persist_to_history", lambda *_args: None)

    async def durable_enqueue(_chat_id, _message_id):
        return True

    monkeypatch.setattr(service, "_enqueue", durable_enqueue)
    await service._handle_new_message(
        {"chat_id": 1001, **_message(99)}
    )

    db_session.expire_all()
    assert db_session.get(MonitoredBotChat, 1001).scan_cursor_message_id == 10


@pytest.mark.asyncio
async def test_catchup_stops_at_current_year_cutoff(db_session, monkeypatch):
    _seed_monitor(db_session)
    manager = FakeManager(
        [
            _message(3, date="2026-02-01T00:00:00Z"),
            _message(2, date="2026-01-01T00:00:00Z"),
            _message(1, date="2025-12-31T18:59:59Z"),
        ]
    )
    service = TgAutoMonitorService(manager, _session_factory(db_session))
    queued = []

    async def durable_enqueue(chat_id, message_id):
        queued.append((chat_id, message_id))
        return True

    monkeypatch.setattr(service, "_enqueue", durable_enqueue)
    await service._catchup_chat(1001)

    db_session.expire_all()
    monitor = db_session.get(MonitoredBotChat, 1001)
    assert queued == [(1001, 2), (1001, 3)]
    assert monitor.scan_cursor_message_id == 3
    assert monitor.scan_backfill_from_message_id is None


@pytest.mark.asyncio
async def test_realtime_old_or_undated_messages_are_rejected(db_session, monkeypatch):
    _seed_monitor(db_session)
    service = TgAutoMonitorService(FakeManager(), _session_factory(db_session))
    monkeypatch.setattr(service, "_persist_to_history", lambda *_args: None)
    queued = []

    async def capture_enqueue(*args):
        queued.append(args)
        return True

    monkeypatch.setattr(service, "_enqueue", capture_enqueue)
    await service._handle_new_message(
        {"chat_id": 1001, **_message(1, date="2025-12-31T18:00:00Z")}
    )
    await service._handle_new_message({"chat_id": 1001, **_message(2, date=None)})

    assert queued == []


@pytest.mark.asyncio
async def test_metadata_only_chat_is_never_enqueued_or_caught_up(db_session, monkeypatch):
    chat_id = -1009999999999
    monkeypatch.setenv("TG_METADATA_ONLY_CHAT_IDS", str(chat_id))
    _seed_monitor(db_session, chat_id=chat_id)
    manager = FakeManager([{"chat_id": chat_id, **_message(101)}])
    service = TgAutoMonitorService(manager, _session_factory(db_session))
    queued = []

    async def capture_enqueue(*args):
        queued.append(args)
        return True

    monkeypatch.setattr(service, "_enqueue", capture_enqueue)
    monkeypatch.setattr(service, "_persist_to_history", lambda *_args: None)
    await service._handle_new_message({"chat_id": chat_id, **_message(101)})
    await service._run_catchup_once()

    assert queued == []
    assert manager.history_calls == []


def test_ubpay_demo_cannot_be_hidden_by_metadata_only_env(monkeypatch):
    from services.message_utils import is_metadata_only_chat

    monkeypatch.setenv("TG_METADATA_ONLY_CHAT_IDS", "-1003547724919")

    assert is_metadata_only_chat(-1003547724919) is False


@pytest.mark.asyncio
async def test_catchup_pauses_when_durable_backlog_is_full(db_session):
    _seed_monitor(db_session)
    db_session.add_all(
        [
            ReceiptProcessingTask(
                task_id=f"backlog-{message_id}",
                chat_id=2000,
                message_id=message_id,
                status="queued",
            )
            for message_id in range(100)
        ]
    )
    db_session.commit()
    manager = FakeManager([_message(101)])
    service = TgAutoMonitorService(manager, _session_factory(db_session))
    service._max_durable_backlog = 100

    await service._run_catchup_once()
    await service._catchup_chat(1001)

    assert manager.history_calls == []
