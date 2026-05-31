from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import AutomationTask
from services.automation import (
    start_mapping_analysis,
    start_reconciliation_analysis,
    start_verification_analysis,
)

logger = logging.getLogger(__name__)

ToolResult = Dict[str, Any]

_POLL_INTERVAL_S = 1.5
_POLL_MAX_S = 120.0
_TERMINAL = {"completed", "failed"}


async def _await_task_result(
    task_id: str,
    *,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Poll an AutomationTask until terminal or timeout.

    Opens a fresh short-lived session per check and closes it before sleeping,
    so a pooled connection is never held across an await (pool_size=10).
    Returns {status, result, progress}. status is one of:
    completed | failed | timeout | not_found.
    """
    try:
        tid = UUID(str(task_id))
    except (ValueError, TypeError):
        return {"status": "not_found", "result": {}, "progress": {}}

    deadline = time.monotonic() + _POLL_MAX_S
    last_progress: Dict[str, Any] = {}
    while True:
        status: Optional[str] = None
        result: Dict[str, Any] = {}
        found = False
        try:
            with SessionLocal() as db:
                task = db.get(AutomationTask, tid)
                if task is not None:
                    found = True
                    status = task.status
                    if task.result_json:
                        try:
                            result = json.loads(task.result_json)
                        except Exception:
                            result = {}
                    if task.progress_json:
                        try:
                            last_progress = json.loads(task.progress_json)
                        except Exception:
                            pass
        except Exception:
            logger.debug("routine poll: db read failed", exc_info=True)
        if status in _TERMINAL:
            return {"status": status, "result": result, "progress": last_progress}
        if not found:
            # Task row vanished (deleted mid-poll) — stop early.
            return {"status": "not_found", "result": result, "progress": last_progress}
        if progress_callback is not None and last_progress:
            try:
                progress_callback({
                    "step": "tool_execution",
                    "percent": int(last_progress.get("percent") or 30),
                })
            except Exception:
                pass
        if time.monotonic() >= deadline:
            return {"status": "timeout", "result": result, "progress": last_progress}
        await asyncio.sleep(_POLL_INTERVAL_S)


def _nav_to_automation(task_id: str, tab: str) -> Dict[str, Any]:
    """AgentLocateResult-compatible target → opens AutomationPage on the task's tab."""
    return {
        "exists": True,
        "route": "/automation",
        "row_id": None,
        "column_id": None,
        "focus_mode": "filter",
        "suggested_filters": {},
        "sort_hint": {},
        "page_hint": None,
        "cursor_hint": {"automation_task_id": str(task_id), "automation_tab": tab},
    }


def _result_card(title: str, body: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "result", "title": title, "body": body, "payload": payload, "details": payload}


def _empty(title: str, msg: str, run_reference: Dict[str, Any]) -> ToolResult:
    return {
        "summary": msg,
        "assistant_message": msg,
        "cards": [_result_card(title, msg, {"обработано": 0})],
        "run_reference": run_reference,
    }


def _failed(title: str, result: Dict[str, Any], run_reference: Dict[str, Any]) -> ToolResult:
    detail = str(result.get("error") or "ошибка обработки")
    msg = f"Не удалось завершить: {detail}"
    return {
        "summary": msg,
        "assistant_message": msg,
        "cards": [{"type": "warning", "title": f"{title} не удалось", "body": msg}],
        "run_reference": run_reference,
    }


def _timeout(title: str, msg: str, task_id: str, tab: str, run_reference: Dict[str, Any]) -> ToolResult:
    return {
        "summary": msg,
        "assistant_message": msg,
        "cards": [_result_card(f"{title} — выполняется", msg, {"статус": "в обработке"})],
        "navigation_targets": [_nav_to_automation(task_id, tab)],
        "run_reference": run_reference,
    }


async def app_mapping(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> ToolResult:
    progress_cb = args.get("_progress_callback")
    started = await start_mapping_analysis(
        db,
        current_user=current_user,
        scope=scope,
        only_unmapped=True,
    )
    if int(started.get("count") or 0) == 0:
        return _empty("Сопоставление приложений", "Непривязанных операций нет — сопоставлять нечего.", started)

    polled = await _await_task_result(started["task_id"], progress_callback=progress_cb)
    res = polled["result"] or {}
    if polled["status"] == "failed":
        return _failed("Сопоставление", res, started)
    if polled["status"] in ("timeout", "not_found"):
        msg = (
            f"Анализ ещё выполняется ({started['count']} операций). "
            "Готовые предложения появятся в разделе «Автоматизация»."
        )
        return _timeout("Сопоставление", msg, started["task_id"], "mapping", started)

    sc = int(res.get("suggestions_count") or 0)
    hc = int(res.get("high_confidence") or 0)
    lc = int(res.get("low_confidence") or 0)
    msg = (
        f"Готово. Подобрал приложения для {sc} операций "
        f"({hc} уверенных, {lc} требуют проверки). "
        "Откройте «Автоматизацию», чтобы подтвердить предложения."
    )
    return {
        "summary": f"Сопоставление: {sc} предложений",
        "assistant_message": msg,
        "cards": [_result_card("Сопоставление приложений", msg, {
            "Предложений": sc,
            "Уверенных": hc,
            "На проверку": lc,
        })],
        "navigation_targets": [_nav_to_automation(started["task_id"], "mapping")],
        "run_reference": started,
    }


async def data_verification(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> ToolResult:
    progress_cb = args.get("_progress_callback")
    started = await start_verification_analysis(
        db,
        current_user=current_user,
        scope=scope,
    )
    if int(started.get("count") or 0) == 0:
        return _empty("Проверка данных", "Нет распарсенных транзакций для проверки.", started)

    polled = await _await_task_result(started["task_id"], progress_callback=progress_cb)
    res = polled["result"] or {}
    if polled["status"] == "failed":
        return _failed("Проверка", res, started)
    if polled["status"] in ("timeout", "not_found"):
        msg = (
            f"Проверка ещё выполняется ({started['count']} транзакций). "
            "Готовые исправления появятся в разделе «Автоматизация»."
        )
        return _timeout("Проверка", msg, started["task_id"], "verification", started)

    tv = int(res.get("total_verified") or 0)
    err = int(res.get("transactions_with_errors") or 0)
    cor = int(res.get("total_corrections") or 0)
    msg = (
        f"Проверено {tv} транзакций. Нашёл проблемы в {err}, "
        f"подготовил {cor} исправлений на проверку. "
        "Откройте «Автоматизацию», чтобы применить."
    )
    return {
        "summary": f"Проверка: {cor} исправлений",
        "assistant_message": msg,
        "cards": [_result_card("Проверка данных", msg, {
            "Проверено": tv,
            "С ошибками": err,
            "Исправлений": cor,
        })],
        "navigation_targets": [_nav_to_automation(started["task_id"], "verification")],
        "run_reference": started,
    }


async def bot_reconciliation(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> ToolResult:
    from api.dependencies import get_allowed_sources_for_user

    progress_cb = args.get("_progress_callback")
    period_end = datetime.utcnow()
    period_start = period_end - timedelta(days=7)

    # RBAC: restrict an operator to their allowed source chats. Admin → None (all).
    allowed = get_allowed_sources_for_user(current_user)
    bot_chat_ids = sorted(allowed) if allowed is not None else None
    if allowed is not None and not allowed:
        return _empty("Сверка чеков", "Нет доступных источников для сверки.", {"task_id": None, "count": 0})

    started = await start_reconciliation_analysis(
        db,
        current_user=current_user,
        period_start=period_start,
        period_end=period_end,
        bot_chat_ids=bot_chat_ids,
        auto_parse=False,
        source="local",
    )
    if int(started.get("count") or 0) == 0:
        return _empty("Сверка чеков", "Нет активных мониторинговых чатов для сверки.", started)

    polled = await _await_task_result(started["task_id"], progress_callback=progress_cb)
    res = polled["result"] or {}
    if polled["status"] == "failed":
        return _failed("Сверка", res, started)
    if polled["status"] in ("timeout", "not_found"):
        msg = (
            f"Сверка ещё выполняется ({started['count']} источников). "
            "Результат появится в разделе «Автоматизация»."
        )
        return _timeout("Сверка", msg, started["task_id"], "reconciliation", started)

    summ = res.get("summary") or {}
    total = int(summ.get("total_receipt_candidates") or 0)
    matched = int(summ.get("matched") or 0)
    missing = int(summ.get("missing_in_db") or 0)
    failed = int(summ.get("failed_parse") or 0)
    orphan = int(summ.get("orphaned_in_db") or 0)
    msg = (
        f"Сверка завершена. Кандидатов: {total}. Совпали: {matched}, "
        f"не попали в базу: {missing}, ошибки разбора: {failed}, без сообщения: {orphan}."
    )
    return {
        "summary": f"Сверка: {matched}/{total} совпали",
        "assistant_message": msg,
        "cards": [_result_card("Сверка чеков", msg, {
            "Кандидатов": total,
            "Совпали": matched,
            "Не попали в базу": missing,
            "Ошибки разбора": failed,
            "Без сообщения": orphan,
        })],
        "navigation_targets": [_nav_to_automation(started["task_id"], "reconciliation")],
        "run_reference": started,
    }
