from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import AutomationTask
from services.automation import (
    start_mapping_analysis,
    start_reconciliation_analysis,
    start_verification_analysis,
)
from services.automation.agent_apply_service import (
    apply_mapping_suggestions,
    apply_verification_suggestions,
    rollback_automation,
)

logger = logging.getLogger(__name__)

ToolResult = Dict[str, Any]

_POLL_INTERVAL_S = 1.5
# Hard ceiling so a wedged background task can't pin the run forever. This is a
# safety net, not a UX deadline: progress is emitted on every poll so the run's
# updated_at keeps bumping and run_watchdog never reaps a live analysis.
_MAX_WAIT_S = float(os.getenv("AI_AGENT_TOOL_MAX_WAIT_S", "600"))
_TERMINAL = {"completed", "failed"}


async def _apply_in_thread(fn: Callable[..., Dict[str, Any]], **kwargs: Any) -> Dict[str, Any]:
    """Run a sync apply/rollback in a worker thread on its own DB session.

    Never share the request Session across threads; open a short-lived one so
    the apply commits independently of the orchestrator's async session.
    """
    def _runner() -> Dict[str, Any]:
        with SessionLocal() as db:
            return fn(db, **kwargs)

    return await asyncio.to_thread(_runner)


def _emit(progress_callback: Optional[Callable[[Dict[str, Any]], None]], payload: Dict[str, Any]) -> None:
    if progress_callback is None:
        return
    try:
        progress_callback(payload)
    except Exception:  # noqa: BLE001
        logger.debug("progress callback raised", exc_info=True)


async def _await_task_result(
    task_id: str,
    *,
    stage_label: str,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Poll an AutomationTask until terminal (or the safety ceiling).

    Opens a fresh short-lived session per check and closes it before sleeping so
    a pooled connection is never held across an await. Emits a progress event on
    EVERY poll — including a starting tick before any task progress exists — so
    the chat shows live steps and the run's updated_at keeps bumping (keeping
    run_watchdog from reaping a genuinely long analysis).
    Returns {status, result, progress}; status one of
    completed | failed | timeout | not_found.
    """
    try:
        tid = UUID(str(task_id))
    except (ValueError, TypeError):
        return {"status": "not_found", "result": {}, "progress": {}}

    deadline = time.monotonic() + _MAX_WAIT_S
    last_progress: Dict[str, Any] = {}
    _emit(progress_callback, {"step": stage_label, "percent": 5, "stage": stage_label})

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
            logger.debug("automation poll: db read failed", exc_info=True)

        if status in _TERMINAL:
            return {"status": status, "result": result, "progress": last_progress}
        if not found:
            return {"status": "not_found", "result": result, "progress": last_progress}

        total = int(last_progress.get("total") or 0)
        done = int(last_progress.get("processed") or 0)
        percent = int(last_progress.get("percent") or 0)
        if total:
            human = f"{stage_label}: {done}/{total}"
        else:
            human = f"{stage_label}…"
        _emit(progress_callback, {
            "step": stage_label,
            "stage": stage_label,
            "percent": max(5, min(95, percent)),
            "current": done,
            "total": total,
            "description": human,
        })

        if time.monotonic() >= deadline:
            return {"status": "timeout", "result": result, "progress": last_progress}
        await asyncio.sleep(_POLL_INTERVAL_S)


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


def _still_running(title: str, count: int, run_reference: Dict[str, Any]) -> ToolResult:
    msg = (
        f"{title}: фоновый анализ ещё идёт ({count} элементов) и не уложился в лимит ожидания. "
        "Слежу за ним — повторите запрос чуть позже, результат подтянется автоматически."
    )
    return {
        "summary": msg,
        "assistant_message": msg,
        "cards": [_result_card(f"{title} — выполняется", msg, {"статус": "в обработке", "элементов": count})],
        "run_reference": run_reference,
    }


async def app_mapping(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> ToolResult:
    progress_cb = args.get("_progress_callback")
    started = await start_mapping_analysis(
        db,
        current_user=current_user,
        scope=scope,
        limit=int(args.get("limit") or 100),
        only_unmapped=bool(args.get("only_unmapped", True)),
        currency_filter=args.get("currency") or None,
    )
    if int(started.get("count") or 0) == 0:
        return _empty("Сопоставление приложений", "Непривязанных операций нет — сопоставлять нечего.", started)

    polled = await _await_task_result(
        started["task_id"], stage_label="Сопоставляю операторов", progress_callback=progress_cb
    )
    res = polled["result"] or {}
    if polled["status"] == "failed":
        return _failed("Сопоставление", res, started)
    if polled["status"] in ("timeout", "not_found"):
        return _still_running("Сопоставление", int(started["count"]), started)

    sc = int(res.get("suggestions_count") or 0)
    hc = int(res.get("high_confidence") or 0)
    lc = int(res.get("low_confidence") or 0)

    # Auto-apply confident suggestions for this task; weak ones stay for review.
    min_conf = float(args.get("min_confidence") or 0.85)
    _emit(progress_cb, {"step": "Применяю предложения", "stage": "Применяю предложения", "percent": 92})
    applied = await _apply_in_thread(
        apply_mapping_suggestions,
        task_id=started["task_id"],
        scope=scope,
        current_user=current_user,
        min_confidence=min_conf,
    )

    msg = (
        f"Подобрал приложения для {sc} операций ({hc} уверенных, {lc} на проверку). "
        f"Автоматически применил {applied['applied']} уверенных."
    )
    if applied["low_confidence"]:
        msg += f" {applied['low_confidence']} слабых оставил без изменений."
    cards = [_result_card("Сопоставление приложений", msg, {
        "Предложений": sc,
        "Применено": applied["applied"],
        "На проверку": applied["low_confidence"],
        "Пропущено": applied["skipped"],
    })]
    if applied["items"]:
        cards.append(_result_card("Применённые сопоставления", "Топ применённых:", {"список": applied["items"]}))
    if applied["low_items"]:
        cards.append(_result_card("Требуют проверки", "Слабые предложения:", {"список": applied["low_items"]}))
    return {
        "summary": f"Сопоставление: применил {applied['applied']}",
        "assistant_message": msg,
        "cards": cards,
        "run_reference": started,
        "data": {"task_id": started["task_id"], "applied": applied["applied"], "low": applied["low_confidence"]},
    }


async def data_verification(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> ToolResult:
    progress_cb = args.get("_progress_callback")
    date_from = _parse_dt(args.get("date_from"))
    date_to = _parse_dt(args.get("date_to"))
    started = await start_verification_analysis(
        db,
        current_user=current_user,
        scope=scope,
        limit=int(args.get("limit") or 50),
        date_from=date_from,
        date_to=date_to,
    )
    if int(started.get("count") or 0) == 0:
        return _empty("Проверка данных", "Нет распарсенных транзакций для проверки.", started)

    polled = await _await_task_result(
        started["task_id"], stage_label="Проверяю транзакции", progress_callback=progress_cb
    )
    res = polled["result"] or {}
    if polled["status"] == "failed":
        return _failed("Проверка", res, started)
    if polled["status"] in ("timeout", "not_found"):
        return _still_running("Проверка", int(started["count"]), started)

    tv = int(res.get("total_verified") or 0)
    err = int(res.get("transactions_with_errors") or 0)
    cor = int(res.get("total_corrections") or 0)

    min_conf = float(args.get("min_confidence") or 0.85)
    _emit(progress_cb, {"step": "Применяю предложения", "stage": "Применяю предложения", "percent": 92})
    applied = await _apply_in_thread(
        apply_verification_suggestions,
        task_id=started["task_id"],
        scope=scope,
        current_user=current_user,
        min_confidence=min_conf,
    )

    msg = (
        f"Проверено {tv} транзакций, нашёл проблемы в {err}, подготовил {cor} исправлений. "
        f"Автоматически применил {applied['applied']} уверенных."
    )
    if applied["low_confidence"]:
        msg += f" {applied['low_confidence']} слабых оставил на проверку."
    cards = [_result_card("Проверка данных", msg, {
        "Проверено": tv,
        "С ошибками": err,
        "Применено": applied["applied"],
        "На проверку": applied["low_confidence"],
    })]
    if applied["items"]:
        cards.append(_result_card("Применённые исправления", "Топ применённых:", {"список": applied["items"]}))
    if applied["low_items"]:
        cards.append(_result_card("Требуют проверки", "Слабые исправления:", {"список": applied["low_items"]}))
    return {
        "summary": f"Проверка: применил {applied['applied']}",
        "assistant_message": msg,
        "cards": cards,
        "run_reference": started,
        "data": {"task_id": started["task_id"], "applied": applied["applied"], "low": applied["low_confidence"]},
    }


async def bot_reconciliation(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> ToolResult:
    from api.dependencies import get_allowed_sources_for_user

    progress_cb = args.get("_progress_callback")
    period_end = _parse_dt(args.get("date_to")) or datetime.utcnow()
    explicit_start = _parse_dt(args.get("date_from"))
    if explicit_start is not None:
        period_start = explicit_start
    else:
        days = int(args.get("period_days") or 7)
        period_start = period_end - timedelta(days=max(1, days))

    # RBAC: restrict an operator to their allowed source chats. Admin → None (all).
    allowed = get_allowed_sources_for_user(current_user)
    requested = args.get("chat_ids")
    if isinstance(requested, list) and requested:
        requested_ids = {int(c) for c in requested}
        if allowed is not None:
            requested_ids &= set(allowed)
        bot_chat_ids: Optional[List[int]] = sorted(requested_ids)
    else:
        bot_chat_ids = sorted(allowed) if allowed is not None else None
    if allowed is not None and not bot_chat_ids:
        return _empty("Сверка чеков", "Нет доступных источников для сверки.", {"task_id": None, "count": 0})

    started = await start_reconciliation_analysis(
        db,
        current_user=current_user,
        period_start=period_start,
        period_end=period_end,
        bot_chat_ids=bot_chat_ids,
        auto_parse=bool(args.get("auto_parse", False)),
        source=str(args.get("source") or "local"),
    )
    if int(started.get("count") or 0) == 0:
        return _empty("Сверка чеков", "Нет активных мониторинговых чатов для сверки.", started)

    polled = await _await_task_result(
        started["task_id"], stage_label="Сверяю с Telegram", progress_callback=progress_cb
    )
    res = polled["result"] or {}
    if polled["status"] == "failed":
        return _failed("Сверка", res, started)
    if polled["status"] in ("timeout", "not_found"):
        return _still_running("Сверка", int(started["count"]), started)

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
    if bool(args.get("auto_parse", False)):
        ap = res.get("auto_parse") or {}
        msg += f" Поставил на разбор: {int(ap.get('queued') or 0)}."
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
        "run_reference": started,
        "data": {"task_id": started["task_id"], "matched": matched, "missing": missing},
    }


async def apply_mapping_suggestions_tool(
    db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]
) -> ToolResult:
    progress_cb = args.get("_progress_callback")
    _emit(progress_cb, {"step": "Применяю предложения", "stage": "Применяю предложения", "percent": 50})
    out = await _apply_in_thread(
        apply_mapping_suggestions,
        task_id=args.get("task_id"),
        scope=scope,
        current_user=current_user,
        min_confidence=float(args.get("min_confidence") or 0.85),
        suggestion_ids=args.get("ids"),
    )
    msg = (
        f"Применил {out['applied']} сопоставлений. "
        f"Слабых (ниже порога): {out['low_confidence']}, пропущено: {out['skipped']}."
    )
    cards = [_result_card("Применение сопоставлений", msg, {
        "Применено": out["applied"],
        "Ниже порога": out["low_confidence"],
        "Пропущено": out["skipped"],
    })]
    if out["low_items"]:
        cards.append(_result_card("Требуют проверки", "Слабые предложения:", {"список": out["low_items"]}))
    return {"summary": msg, "assistant_message": msg, "cards": cards, "data": out}


async def apply_verification_suggestions_tool(
    db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]
) -> ToolResult:
    progress_cb = args.get("_progress_callback")
    _emit(progress_cb, {"step": "Применяю предложения", "stage": "Применяю предложения", "percent": 50})
    out = await _apply_in_thread(
        apply_verification_suggestions,
        task_id=args.get("task_id"),
        scope=scope,
        current_user=current_user,
        min_confidence=float(args.get("min_confidence") or 0.85),
        suggestion_ids=args.get("ids"),
    )
    msg = (
        f"Применил {out['applied']} исправлений полей. "
        f"Слабых (ниже порога): {out['low_confidence']}, пропущено: {out['skipped']}."
    )
    cards = [_result_card("Применение исправлений", msg, {
        "Применено": out["applied"],
        "Ниже порога": out["low_confidence"],
        "Пропущено": out["skipped"],
    })]
    if out["low_items"]:
        cards.append(_result_card("Требуют проверки", "Слабые исправления:", {"список": out["low_items"]}))
    return {"summary": msg, "assistant_message": msg, "cards": cards, "data": out}


async def auto_parse_reconciliation_tool(
    db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]
) -> ToolResult:
    from api.routes.reconciliation import _queue_message_for_parsing

    progress_cb = args.get("_progress_callback")
    _emit(progress_cb, {"step": "Сверяю с Telegram", "stage": "Сверяю с Telegram", "percent": 40})
    try:
        tid = UUID(str(args.get("task_id")))
    except (ValueError, TypeError):
        msg = "Не указан корректный task_id завершённой сверки."
        return {"summary": msg, "assistant_message": msg, "cards": [{"type": "warning", "title": "Авто-разбор", "body": msg}]}

    task = db.get(AutomationTask, tid)
    if not task or task.status != "completed" or not task.result_json:
        msg = "Завершённая задача сверки не найдена — сначала выполните сверку."
        return {"summary": msg, "assistant_message": msg, "cards": [{"type": "warning", "title": "Авто-разбор", "body": msg}]}

    try:
        result = json.loads(task.result_json)
    except Exception:
        msg = "Повреждённые результаты сверки."
        return {"summary": msg, "assistant_message": msg, "cards": [{"type": "warning", "title": "Авто-разбор", "body": msg}]}

    parseable = {"MISSING_IN_DB", "FAILED_PARSE"}
    category = args.get("category")
    if category:
        cat = str(category).upper()
        if cat in parseable:
            parseable = {cat}

    stats = {"queued": 0, "skipped": 0, "errors": 0}
    for item in result.get("items", []):
        if item.get("category") not in parseable or not item.get("can_auto_parse"):
            continue
        try:
            if _queue_message_for_parsing(db, chat_id=item["chat_id"], message_id=item["message_id"]):
                stats["queued"] += 1
            else:
                stats["skipped"] += 1
        except Exception:  # noqa: BLE001
            logger.warning("auto-parse queue failed chat=%s msg=%s", item.get("chat_id"), item.get("message_id"), exc_info=True)
            stats["errors"] += 1

    msg = f"Поставил на повторный разбор {stats['queued']} сообщений (пропущено {stats['skipped']}, ошибок {stats['errors']})."
    return {
        "summary": msg,
        "assistant_message": msg,
        "cards": [_result_card("Авто-разбор пропусков", msg, {
            "В очередь": stats["queued"],
            "Пропущено": stats["skipped"],
            "Ошибки": stats["errors"],
        })],
        "data": stats,
    }


async def rollback_automation_tool(
    db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]
) -> ToolResult:
    progress_cb = args.get("_progress_callback")
    _emit(progress_cb, {"step": "Откатываю изменения", "stage": "Откатываю изменения", "percent": 50})
    out = await _apply_in_thread(
        rollback_automation,
        task_id=args.get("task_id"),
        scope_kind=str(args.get("scope") or "all"),
        current_user=current_user,
    )
    msg = f"Откатил {out['reverted']} изменений."
    if out["unrevertable"]:
        msg += f" {out['unrevertable']} откатить нельзя (нет прежнего значения)."
    if out["skipped"]:
        msg += f" Пропущено: {out['skipped']}."
    cards = [_result_card("Откат изменений", msg, {
        "Откачено": out["reverted"],
        "Без отката": out["unrevertable"],
        "Пропущено": out["skipped"],
    })]
    for note in out.get("notes") or []:
        cards.append({"type": "warning", "title": "Внимание", "body": note})
    return {"summary": msg, "assistant_message": msg, "cards": cards, "data": out}


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
