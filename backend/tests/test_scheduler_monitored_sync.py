"""Unit tests for AgentSchedulerService._run_monitored_chat_sync.

Covers the v1.4.10 hotfix: monitored-chat sync runs in-process in the backend
event loop, not enqueued into Celery.
"""
import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.ai_agent.scheduler_service import AgentSchedulerService


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("MONITORED_CHAT_SYNC_ENABLED", raising=False)
    monkeypatch.delenv("MONITORED_CHAT_SYNC_VIA_BACKEND", raising=False)


def _make_service():
    return AgentSchedulerService()


def test_run_monitored_chat_sync_calls_backend_path():
    """Default flags → sync runs in-process via sync_all_active_chats."""
    svc = _make_service()
    captured = {}

    async def fake_sync_all(*, fetch_callable):
        captured["called"] = True
        items = await fetch_callable(chat_id=42, from_message_id=0, limit=5)
        captured["fetch_items"] = items
        return [{"chat_id": 42, "new_rows": len(items), "pages_done": 1}]

    fake_mgr = types.SimpleNamespace()

    async def fake_get_messages(*, chat_id, from_message_id, limit):
        return {"items": [{"id": 1}, {"id": 2}], "total": 2}

    fake_mgr.get_messages = fake_get_messages

    fake_sync_module = types.ModuleType("services.monitored_chat_sync")
    fake_sync_module.sync_all_active_chats = fake_sync_all

    fake_tdlib_module = types.ModuleType("services.telegram_tdlib_manager")

    class _FakeTDLibUnavailableError(RuntimeError):
        pass

    fake_tdlib_module.TDLibUnavailableError = _FakeTDLibUnavailableError
    fake_tdlib_module.get_tdlib_manager = lambda: fake_mgr

    with patch.dict(
        sys.modules,
        {
            "services.monitored_chat_sync": fake_sync_module,
            "services.telegram_tdlib_manager": fake_tdlib_module,
        },
    ):
        asyncio.run(svc._run_monitored_chat_sync())

    assert captured["called"] is True
    assert captured["fetch_items"] == [{"id": 1}, {"id": 2}]


def test_run_monitored_chat_sync_disabled_via_env(monkeypatch):
    """`MONITORED_CHAT_SYNC_ENABLED=false` → no work done."""
    monkeypatch.setenv("MONITORED_CHAT_SYNC_ENABLED", "false")
    svc = _make_service()

    fake_sync_module = types.ModuleType("services.monitored_chat_sync")

    async def boom(**_):
        raise AssertionError("sync_all_active_chats should not run when disabled")

    fake_sync_module.sync_all_active_chats = boom

    with patch.dict(sys.modules, {"services.monitored_chat_sync": fake_sync_module}):
        asyncio.run(svc._run_monitored_chat_sync())  # must complete without error


def test_run_monitored_chat_sync_rejects_unsafe_celery_fallback(monkeypatch):
    """The unauthenticated Celery TDLib fallback is ignored even if configured."""
    monkeypatch.setenv("MONITORED_CHAT_SYNC_VIA_BACKEND", "false")
    svc = _make_service()

    sent_tasks = []

    def fake_send_task(name, *args, **kwargs):
        sent_tasks.append(name)

    svc._celery.send_task = fake_send_task  # type: ignore[assignment]

    fake_sync_module = types.ModuleType("services.monitored_chat_sync")

    called = []

    async def fake_sync_all(**_):
        called.append(True)
        return []

    fake_sync_module.sync_all_active_chats = fake_sync_all

    fake_tdlib_module = types.ModuleType("services.telegram_tdlib_manager")

    class _FakeTDLibUnavailableError(RuntimeError):
        pass

    fake_tdlib_module.TDLibUnavailableError = _FakeTDLibUnavailableError
    fake_tdlib_module.get_tdlib_manager = lambda: types.SimpleNamespace()

    with patch.dict(
        sys.modules,
        {
            "services.monitored_chat_sync": fake_sync_module,
            "services.telegram_tdlib_manager": fake_tdlib_module,
        },
    ):
        asyncio.run(svc._run_monitored_chat_sync())

    assert called == [True]
    assert sent_tasks == []


def test_run_monitored_chat_sync_swallows_per_chat_errors():
    """Exception in fetch_callable for one chat does not abort the tick."""
    svc = _make_service()

    fake_sync_module = types.ModuleType("services.monitored_chat_sync")
    captured_errors = []

    async def fake_sync_all(*, fetch_callable):
        try:
            await fetch_callable(chat_id=1, from_message_id=0, limit=5)
        except Exception as exc:  # noqa: BLE001
            captured_errors.append(str(exc))
        return [{"chat_id": 1, "new_rows": 0}]

    fake_sync_module.sync_all_active_chats = fake_sync_all

    fake_tdlib_module = types.ModuleType("services.telegram_tdlib_manager")

    class _FakeTDLibUnavailableError(RuntimeError):
        pass

    class _FakeMgr:
        async def get_messages(self, **_):
            raise RuntimeError("tdlib boom")

    fake_tdlib_module.TDLibUnavailableError = _FakeTDLibUnavailableError
    fake_tdlib_module.get_tdlib_manager = lambda: _FakeMgr()

    with patch.dict(
        sys.modules,
        {
            "services.monitored_chat_sync": fake_sync_module,
            "services.telegram_tdlib_manager": fake_tdlib_module,
        },
    ):
        asyncio.run(svc._run_monitored_chat_sync())

    assert captured_errors == ["tdlib boom"]


def test_run_monitored_chat_sync_handles_tdlib_unavailable():
    """`TDLibUnavailableError` remains distinguishable from empty history."""
    svc = _make_service()

    fake_sync_module = types.ModuleType("services.monitored_chat_sync")
    captured_errors = []

    async def fake_sync_all(*, fetch_callable):
        try:
            await fetch_callable(chat_id=7, from_message_id=0, limit=5)
        except Exception as exc:  # noqa: BLE001
            captured_errors.append(str(exc))
        return [{"chat_id": 7, "new_rows": 0}]

    fake_sync_module.sync_all_active_chats = fake_sync_all

    fake_tdlib_module = types.ModuleType("services.telegram_tdlib_manager")

    class _FakeTDLibUnavailableError(RuntimeError):
        pass

    class _FakeMgr:
        async def get_messages(self, **_):
            raise _FakeTDLibUnavailableError("not loaded")

    fake_tdlib_module.TDLibUnavailableError = _FakeTDLibUnavailableError
    fake_tdlib_module.get_tdlib_manager = lambda: _FakeMgr()

    with patch.dict(
        sys.modules,
        {
            "services.monitored_chat_sync": fake_sync_module,
            "services.telegram_tdlib_manager": fake_tdlib_module,
        },
    ):
        asyncio.run(svc._run_monitored_chat_sync())

    assert captured_errors == ["tdlib_unavailable:not loaded"]


def test_run_monitored_chat_sync_handles_fetch_timeout(monkeypatch):
    """A hung TDLib request is bounded by the per-chat timeout, not the tick."""
    monkeypatch.setenv("MONITORED_CHAT_SYNC_FETCH_TIMEOUT_SECONDS", "5")
    svc = _make_service()

    fake_sync_module = types.ModuleType("services.monitored_chat_sync")
    captured_errors = []

    async def fake_sync_all(*, fetch_callable):
        try:
            await fetch_callable(chat_id=99, from_message_id=0, limit=5)
        except Exception as exc:  # noqa: BLE001
            captured_errors.append(str(exc))
        return [{"chat_id": 99, "new_rows": 0}]

    fake_sync_module.sync_all_active_chats = fake_sync_all

    fake_tdlib_module = types.ModuleType("services.telegram_tdlib_manager")

    class _FakeTDLibUnavailableError(RuntimeError):
        pass

    class _FakeMgr:
        async def get_messages(self, **_):
            await asyncio.sleep(120)
            return {"items": [], "total": 0}

    fake_tdlib_module.TDLibUnavailableError = _FakeTDLibUnavailableError
    fake_tdlib_module.get_tdlib_manager = lambda: _FakeMgr()

    async def fast_wait_for(coro, timeout):
        # Cancel the inner sleep immediately to keep the test < 1s
        task = asyncio.ensure_future(coro)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, BaseException):
            pass
        raise asyncio.TimeoutError()

    with patch.dict(
        sys.modules,
        {
            "services.monitored_chat_sync": fake_sync_module,
            "services.telegram_tdlib_manager": fake_tdlib_module,
        },
    ), patch("services.ai_agent.scheduler_service.asyncio.wait_for", fast_wait_for):
        asyncio.run(svc._run_monitored_chat_sync())

    assert captured_errors == ["tdlib_timeout:5.0s"]


def test_scheduler_registers_async_monitored_sync_job():
    """`start()` registers `agent-monitored-chat-sync` pointing at async coroutine."""

    async def _run():
        svc = _make_service()
        svc.start()
        try:
            assert svc._scheduler is not None
            job = svc._scheduler.get_job("agent-monitored-chat-sync")
            assert job is not None
            assert asyncio.iscoroutinefunction(job.func)
            assert job.func.__name__ == "_run_monitored_chat_sync"
        finally:
            svc.stop()

    asyncio.run(_run())
