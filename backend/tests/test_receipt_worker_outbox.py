from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base, MonitoredBotChat, ReceiptProcessingTask, ReceiptTaskDLQ
from services import receipt_watchdog
from workers import celery_worker


@pytest.fixture
def outbox_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    @contextmanager
    def get_db():
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr("database.connection.get_db", get_db)
    monkeypatch.setattr(receipt_watchdog, "get_db", get_db)
    return session_factory


def _payload(message_id: int = 20) -> dict:
    return {
        "raw_text": "HUMO receipt amount 10000 UZS card *1234",
        "source_type": "AUTO",
        "source_chat_id": 10,
        "source_message_id": message_id,
    }


def test_tracking_commit_precedes_broker_publish(outbox_db, monkeypatch):
    observed = {}

    def fake_apply_async(*, args, task_id, queue):
        with outbox_db() as db:
            row = db.query(ReceiptProcessingTask).filter_by(task_id=task_id).one()
            observed.update(
                status=row.status,
                publish_state=row.publish_state,
                payload_json=row.payload_json,
                queue=queue,
                args=args,
            )

    monkeypatch.setattr(celery_worker.process_receipt_task, "apply_async", fake_apply_async)

    task_id = celery_worker.queue_receipt_task(_payload())

    assert observed["publish_state"] == "publishing"
    assert observed["payload_json"] == observed["args"][0]
    assert observed["queue"] == "receipts.fast"
    with outbox_db() as db:
        row = db.query(ReceiptProcessingTask).filter_by(task_id=task_id).one()
        assert row.status == "queued"
        assert row.publish_state == "published"
        assert row.publish_attempts == 1
        assert row.published_at is not None


def test_broker_failure_remains_durable_and_dispatcher_retries(outbox_db, monkeypatch):
    def fail_publish(**_kwargs):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(celery_worker.process_receipt_task, "apply_async", fail_publish)
    task_id = celery_worker.queue_receipt_task(_payload(21))

    with outbox_db() as db:
        row = db.query(ReceiptProcessingTask).filter_by(task_id=task_id).one()
        assert row.status == "retry"
        assert row.publish_state == "retry"
        assert row.payload_json
        row.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()

    published = []

    def succeed_publish(**kwargs):
        published.append(kwargs)

    monkeypatch.setattr(celery_worker.process_receipt_task, "apply_async", succeed_publish)
    result = celery_worker.dispatch_pending_receipt_tasks()

    assert result == {"checked": 1, "published": 1}
    assert published[0]["task_id"] == task_id
    with outbox_db() as db:
        row = db.query(ReceiptProcessingTask).filter_by(task_id=task_id).one()
        assert row.publish_state == "published"
        assert row.publish_attempts == 2


def test_source_identity_reuses_active_task(outbox_db, monkeypatch):
    published = []
    monkeypatch.setattr(
        celery_worker.process_receipt_task,
        "apply_async",
        lambda **kwargs: published.append(kwargs),
    )

    first = celery_worker.queue_receipt_task(_payload(22))
    second = celery_worker.queue_receipt_task(_payload(22))

    assert second == first
    assert len(published) == 1
    with outbox_db() as db:
        assert db.query(ReceiptProcessingTask).count() == 1


def test_watchdog_bounds_poison_retries_and_writes_dlq(outbox_db, monkeypatch):
    old = datetime.utcnow() - timedelta(minutes=30)
    with outbox_db() as db:
        db.add(
            ReceiptProcessingTask(
                task_id="00000000-0000-0000-0000-000000000023",
                chat_id=10,
                message_id=23,
                status="processing",
                payload_json='{"source_chat_id": 10, "source_message_id": 23}',
                publish_state="published",
                processing_attempts=celery_worker.RECEIPT_MAX_PROCESSING_ATTEMPTS,
                heartbeat_at=old,
            )
        )
        db.commit()

    monkeypatch.setattr(
        celery_worker,
        "dispatch_pending_receipt_tasks",
        lambda limit=100: {"checked": 0, "published": 0},
    )
    result = receipt_watchdog.sweep_stuck_receipt_tasks(timeout_seconds=120)

    assert result["dead"] == 1
    assert result["retried"] == 0
    with outbox_db() as db:
        row = db.query(ReceiptProcessingTask).one()
        assert row.status == "dead"
        assert row.publish_state == "dead"
        dlq = db.query(ReceiptTaskDLQ).one()
        assert dlq.task_id == row.task_id
        assert dlq.reason == "watchdog_exhausted"


def test_watchdog_requeues_non_exhausted_lost_worker(outbox_db, monkeypatch):
    old = datetime.utcnow() - timedelta(minutes=30)
    with outbox_db() as db:
        db.add(
            ReceiptProcessingTask(
                task_id="00000000-0000-0000-0000-000000000024",
                chat_id=10,
                message_id=24,
                status="processing",
                payload_json='{"source_chat_id": 10, "source_message_id": 24}',
                publish_state="published",
                processing_attempts=1,
                heartbeat_at=old,
            )
        )
        db.commit()

    dispatched = []
    monkeypatch.setattr(
        celery_worker,
        "dispatch_pending_receipt_tasks",
        lambda limit=100: dispatched.append(True) or {"checked": 1, "published": 1},
    )
    result = receipt_watchdog.sweep_stuck_receipt_tasks(timeout_seconds=120)

    assert result["retried"] == 1
    assert result["dead"] == 0
    assert dispatched == [True]
    with outbox_db() as db:
        row = db.query(ReceiptProcessingTask).one()
        assert row.status == "retry"
        assert row.publish_state == "retry"
        assert row.next_retry_at is not None


def test_download_rejects_declared_file_above_hard_cap(monkeypatch):
    class Response:
        headers = {"Content-Length": str(celery_worker.RECEIPT_MAX_DOWNLOAD_BYTES + 1)}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self, chunk_size):
            yield b"ignored"

    class Client:
        def stream(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(celery_worker, "_get_http_client", lambda: Client())

    with pytest.raises(ValueError, match="receipt_file_too_large"):
        celery_worker.download_file_bytes(100)


def test_source_datetime_is_used_as_tashkent_fallback():
    parsed = celery_worker._task_fallback_datetime(
        {"source_received_at": "2026-07-12T10:00:00Z"}
    )

    assert parsed == datetime(2026, 7, 12, 15, 0, 0)


@pytest.mark.parametrize(
    ("monitor_enabled", "source_received_at", "expected_reason"),
    [
        (True, "2025-12-31T18:00:00Z", "source_before_date_cutoff"),
        (False, "2026-07-12T10:00:00Z", "unmonitored_source"),
    ],
)
def test_auto_worker_rejects_old_or_unmonitored_sources_before_logging(
    outbox_db,
    monkeypatch,
    monitor_enabled,
    source_received_at,
    expected_reason,
):
    monkeypatch.setenv("RECEIPT_MIN_DATE", "2026-01-01")
    task_id = "00000000-0000-0000-0000-000000000099"
    payload = {
        **_payload(99),
        "added_via": "tdlib",
        "source_received_at": source_received_at,
    }
    with outbox_db() as db:
        db.add(
            MonitoredBotChat(
                chat_id=10,
                enabled=monitor_enabled,
                filter_mode="all",
                chat_type="private",
            )
        )
        db.add(
            ReceiptProcessingTask(
                task_id=task_id,
                chat_id=10,
                message_id=99,
                status="queued",
                publish_state="published",
                payload_json=json.dumps(payload),
            )
        )
        db.commit()

    logged = []
    monkeypatch.setattr(
        celery_worker.receipt_logger,
        "log_received",
        lambda **kwargs: logged.append(kwargs),
    )

    result = celery_worker.process_receipt_task.apply(
        args=[json.dumps(payload)],
        task_id=task_id,
    ).get(propagate=True)

    assert result == {"success": True, "skipped": True, "reason": expected_reason}
    assert logged == []
    with outbox_db() as db:
        row = db.query(ReceiptProcessingTask).filter_by(task_id=task_id).one()
        assert row.status == "done"
        assert row.error == f"skipped:{expected_reason}"
