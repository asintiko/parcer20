"""Agent routines: scheduled NL tasks executed through SAFE tool primitives.

A routine is a saved task the AI agent runs on a cron schedule (e.g. weekly
reconciliation). Execution NEVER runs generated code — it dispatches to vetted,
parameterized tools (weekly_health_check / chat_vs_db_reconcile / analytics).
Results are delivered to the receipt-log Telegram channel and as an in-app
agent notification.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import httpx
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from database.models import AgentRoutine, AgentRoutineRun

logger = logging.getLogger(__name__)

VALID_KINDS = {"reconcile", "summary", "custom", "receipt_audit"}

# Reserved name marking the auto-seeded built-in receipt-audit routine.
_BUILTIN_RECEIPT_AUDIT_NAME = "Аудит чеков (встроенная)"
_BUILTIN_RECEIPT_AUDIT_MARKER = "receipt_audit_daily"


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #
def serialize_routine(r: AgentRoutine) -> Dict[str, Any]:
    return {
        "id": str(r.id),
        "name": r.name,
        "description": r.description,
        "task_prompt": r.task_prompt,
        "cron": r.cron,
        "kind": r.kind,
        "schedule_kind": getattr(r, "schedule_kind", None) or "recurring",
        "run_at": r.run_at.isoformat() if getattr(r, "run_at", None) else None,
        "enabled": bool(r.enabled),
        "deliver_to_channel": bool(r.deliver_to_channel),
        "deliver_to_chat": bool(r.deliver_to_chat),
        "created_by_user_id": r.created_by_user_id,
        "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
        "last_status": r.last_status,
        "last_summary": r.last_summary,
        "next_run_at": r.next_run_at.isoformat() if r.next_run_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def serialize_run(r: AgentRoutineRun) -> Dict[str, Any]:
    return {
        "id": str(r.id),
        "routine_id": str(r.routine_id),
        "status": r.status,
        "trigger": r.trigger,
        "summary": r.summary,
        "error_text": r.error_text,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def _validate_cron(cron: str) -> str:
    parts = (cron or "").strip().split()
    if len(parts) != 5:
        raise ValueError("cron must have 5 fields: 'min hour day month weekday'")
    return " ".join(parts)


def _normalize_kind(kind: Optional[str]) -> str:
    k = (kind or "reconcile").strip().lower()
    return k if k in VALID_KINDS else "custom"


def _normalize_schedule_kind(value: Optional[str]) -> str:
    s = (value or "recurring").strip().lower()
    return s if s in {"recurring", "once"} else "recurring"


def _parse_run_at(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("run_at must be an ISO 8601 datetime")


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
def list_routines(
    db: Session,
    *,
    actor_user_id: Optional[int] = None,
    is_admin: bool = False,
) -> List[Dict[str, Any]]:
    query = db.query(AgentRoutine)
    if actor_user_id is not None and not is_admin:
        query = query.filter(AgentRoutine.created_by_user_id == int(actor_user_id))
    rows = query.order_by(AgentRoutine.created_at.desc()).all()
    return [serialize_routine(r) for r in rows]


def get_routine(db: Session, routine_id: UUID) -> Optional[AgentRoutine]:
    return db.get(AgentRoutine, routine_id)


def create_routine(
    db: Session,
    *,
    name: str,
    task_prompt: str,
    cron: str = "0 12 * * 1",
    kind: str = "reconcile",
    description: Optional[str] = None,
    enabled: bool = True,
    deliver_to_channel: bool = True,
    deliver_to_chat: bool = True,
    created_by_user_id: Optional[int] = None,
    schedule_kind: str = "recurring",
    run_at: Any = None,
    config: Optional[Dict[str, Any]] = None,
) -> AgentRoutine:
    if not (name or "").strip():
        raise ValueError("name is required")
    if not (task_prompt or "").strip():
        raise ValueError("task_prompt is required")
    sched = _normalize_schedule_kind(schedule_kind)
    parsed_run_at = _parse_run_at(run_at)
    if sched == "once":
        # Cron is a placeholder for one-shot routines; keep whatever fits the
        # column without enforcing a valid 5-field expression.
        normalized_cron = (cron or "0 12 * * 1").strip()[:120]
        if parsed_run_at is None:
            raise ValueError("run_at is required when schedule_kind='once'")
    else:
        normalized_cron = _validate_cron(cron)
    row = AgentRoutine(
        id=uuid4(),
        name=name.strip()[:200],
        description=(description or None),
        task_prompt=task_prompt.strip(),
        cron=normalized_cron,
        kind=_normalize_kind(kind),
        enabled=bool(enabled),
        deliver_to_channel=bool(deliver_to_channel),
        deliver_to_chat=bool(deliver_to_chat),
        created_by_user_id=created_by_user_id,
        schedule_kind=sched,
        run_at=parsed_run_at,
        config_json=json.dumps(config or {}, ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_routine(db: Session, routine: AgentRoutine, **fields: Any) -> AgentRoutine:
    if "name" in fields and fields["name"] is not None:
        routine.name = str(fields["name"]).strip()[:200]
    if "description" in fields:
        routine.description = fields["description"] or None
    if "task_prompt" in fields and fields["task_prompt"] is not None:
        routine.task_prompt = str(fields["task_prompt"]).strip()
    if "kind" in fields and fields["kind"] is not None:
        routine.kind = _normalize_kind(str(fields["kind"]))
    if "schedule_kind" in fields and fields["schedule_kind"] is not None:
        routine.schedule_kind = _normalize_schedule_kind(str(fields["schedule_kind"]))
    if "run_at" in fields:
        routine.run_at = _parse_run_at(fields["run_at"])
    if "cron" in fields and fields["cron"] is not None:
        # Only enforce a valid 5-field cron for recurring routines.
        if (routine.schedule_kind or "recurring") == "once":
            routine.cron = str(fields["cron"]).strip()[:120]
        else:
            routine.cron = _validate_cron(str(fields["cron"]))
    if "enabled" in fields and fields["enabled"] is not None:
        routine.enabled = bool(fields["enabled"])
    if "deliver_to_channel" in fields and fields["deliver_to_channel"] is not None:
        routine.deliver_to_channel = bool(fields["deliver_to_channel"])
    if "deliver_to_chat" in fields and fields["deliver_to_chat"] is not None:
        routine.deliver_to_chat = bool(fields["deliver_to_chat"])
    db.commit()
    db.refresh(routine)
    return routine


def delete_routine(db: Session, routine: AgentRoutine) -> None:
    db.delete(routine)
    db.commit()


def list_runs(db: Session, routine_id: UUID, limit: int = 50) -> List[Dict[str, Any]]:
    rows = (
        db.query(AgentRoutineRun)
        .filter(AgentRoutineRun.routine_id == routine_id)
        .order_by(AgentRoutineRun.started_at.desc())
        .limit(max(1, min(int(limit), 200)))
        .all()
    )
    return [serialize_run(r) for r in rows]


# --------------------------------------------------------------------------- #
# Execution (SAFE primitives only)
# --------------------------------------------------------------------------- #
_BUILTIN_SERVICE_CTX = {
    "role": "admin",
    "user_id": 0,
    "id": 0,
    "service_principal": _BUILTIN_RECEIPT_AUDIT_MARKER,
}


async def _run_kind(
    db: Session,
    kind: str,
    config: Dict[str, Any],
    current_user: Dict[str, Any],
    scope: Optional[Dict[str, Any]],
    task_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Dispatch a routine to a vetted tool / headless agent run. Returns result dict."""
    from services.ai_agent.tools.audit_tools import weekly_health_check
    from services.ai_agent.tools.calc_tools import period_summary

    args = dict(config or {})
    if kind == "reconcile":
        # Full health + chat↔DB reconciliation across all chats.
        return await weekly_health_check(db, current_user, scope, args)
    if kind == "summary":
        return await period_summary(db, current_user, scope, args)
    if kind == "receipt_audit":
        # Compare locally-synced TG receipts vs DB over a configurable lookback.
        days = int(args.get("days") or 7)
        end = datetime.utcnow()
        start = end - timedelta(days=max(1, days))
        audit_args = {
            **args,
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
        }
        return await weekly_health_check(db, current_user, scope, audit_args)
    # custom → run the saved NL task through the agent's native tool-calling loop
    # (safe read tools; mutations stay behind confirmation and never auto-apply).
    from services.ai_agent.orchestrator import get_orchestrator

    prompt = (task_prompt or "").strip()
    if not prompt:
        # No prompt to execute — fall back to the safe reconcile primitive.
        return await weekly_health_check(db, current_user, scope, args)
    return await get_orchestrator().run_task(
        db=db,
        task_prompt=prompt,
        scope=scope,
        current_user=current_user,
    )


def _format_report(routine: AgentRoutine, result: Dict[str, Any]) -> str:
    summary = result.get("summary") or "Готово"
    data = result.get("data") or {}
    has_issues = bool(data.get("has_issues"))
    icon = "⚠️" if has_issues else "✅"
    lines = [f"{icon} <b>Рутина: {_esc(routine.name)}</b>", "", _esc(summary)]
    if has_issues:
        lines.append("")
        lines.append("Обнаружены расхождения — проверьте детали в приложении.")
    else:
        lines.append("")
        lines.append("Расхождений не найдено, всё в порядке.")
    return "\n".join(lines)


def _esc(value: Any) -> str:
    text = str(value or "")
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_receipt_audit_report(routine: AgentRoutine, result: Dict[str, Any]) -> str:
    """Rich Telegram-HTML report comparing synced TG receipts vs DB + parsing accuracy."""
    data = result.get("data") or {}
    totals = data.get("totals") or {}
    chats = data.get("chats") or []
    period = data.get("period") or []
    has_issues = bool(data.get("has_issues"))

    total_tx = int(totals.get("transactions") or 0)
    total_failed = int(totals.get("failed") or 0)
    total_stuck = int(totals.get("stuck") or 0)
    dup_groups = int(totals.get("duplicate_groups") or 0)

    def _accuracy(tx: int, failed: int) -> Optional[float]:
        denom = tx + failed
        if denom <= 0:
            return None
        return round(tx / denom * 100.0, 1)

    overall_acc = _accuracy(total_tx, total_failed)
    icon = "⚠️" if has_issues else "✅"

    def _fmt_period() -> str:
        if len(period) == 2:
            try:
                a = datetime.fromisoformat(str(period[0]).replace("Z", "+00:00"))
                b = datetime.fromisoformat(str(period[1]).replace("Z", "+00:00"))
                return f"{a.strftime('%d.%m')} — {b.strftime('%d.%m')}"
            except Exception:
                return ""
        return ""

    lines: List[str] = [f"{icon} <b>Аудит чеков: {_esc(routine.name)}</b>"]
    period_label = _fmt_period()
    if period_label:
        lines.append(f"🗓 Период: {period_label}")
    lines.append("")
    acc_label = f"{overall_acc}%" if overall_acc is not None else "—"
    lines.append(f"📊 <b>Точность парсинга:</b> {acc_label}")
    lines.append(
        f"💰 Транзакций: {total_tx}  ·  ❌ Ошибок: {total_failed}  ·  ⏳ Застряло: {total_stuck}"
    )
    lines.append(f"♻️ Дубликат-групп: {dup_groups}")

    # Per-chat breakdown (cap to keep message compact).
    rendered = 0
    chat_lines: List[str] = []
    for ch in chats:
        cdata = ch.get("data") or {}
        cached = cdata.get("cached_messages")
        tasks = cdata.get("tasks") or {}
        ctx = int(cdata.get("transactions") or 0)
        cfailed = int(tasks.get("failed") or 0)
        cstuck = int(tasks.get("processing") or 0)
        ctotal_tasks = int(tasks.get("total") or 0)
        cacc = _accuracy(ctx, cfailed)
        cicon = "⚠️" if (cfailed or cstuck) else "✅"
        title = _esc(ch.get("chat_title") or ch.get("chat_id") or "—")
        cached_label = cached if cached is not None else "—"
        cacc_label = f"{cacc}%" if cacc is not None else "—"
        chat_lines.append(
            f"{cicon} <b>{title}</b>\n"
            f"   кэш {cached_label} → задач {ctotal_tasks} → тр. {ctx}  ·  "
            f"ошибок {cfailed}, застряло {cstuck}, точность {cacc_label}"
        )
        rendered += 1
        if rendered >= 12:
            break

    if chat_lines:
        lines.append("")
        lines.append("<b>По чатам:</b>")
        lines.extend(chat_lines)

    if len(chats) > rendered:
        lines.append(f"… и ещё {len(chats) - rendered} чат(ов)")

    lines.append("")
    if has_issues:
        lines.append("Есть расхождения — детали в приложении.")
    else:
        lines.append("Расхождений не найдено, парсинг в норме.")

    text = "\n".join(lines)
    if len(text) > 3500:
        text = text[:3490].rstrip() + "\n…"
    return text


async def execute_routine(routine_id: UUID, *, trigger: str = "schedule") -> Dict[str, Any]:
    """Execute one routine end-to-end: run tool → record run → deliver report."""
    with SessionLocal() as db:
        routine = db.get(AgentRoutine, routine_id)
        if routine is None:
            return {"ok": False, "error": "routine_not_found"}
        if trigger == "schedule" and not routine.enabled:
            return {"ok": False, "error": "disabled"}

        run = AgentRoutineRun(id=uuid4(), routine_id=routine.id, status="running", trigger=trigger)
        db.add(run)
        routine.last_status = "running"
        routine.last_run_at = datetime.utcnow()
        db.commit()

        try:
            config = json.loads(routine.config_json or "{}")
        except Exception:
            config = {}

        try:
            is_builtin = (
                routine.created_by_user_id is None
                and routine.kind == "receipt_audit"
                and routine.name == _BUILTIN_RECEIPT_AUDIT_NAME
                and config.get("builtin") == _BUILTIN_RECEIPT_AUDIT_MARKER
            )
            owner_auth = None
            if is_builtin:
                execution_user = _BUILTIN_SERVICE_CTX
                execution_scope = None
            else:
                from services.ai_agent.authorization import current_agent_authorization

                owner_auth = current_agent_authorization(db, routine.created_by_user_id)
                owner_auth.require_dashboard()
                execution_user = owner_auth.user
                execution_scope = owner_auth.tool_scope()

            result = await _run_kind(
                db,
                routine.kind,
                config,
                current_user=execution_user,
                scope=execution_scope,
                task_prompt=routine.task_prompt,
            )
            summary = result.get("summary") or "Готово"
            run.status = "ok"
            run.summary = summary
            run.result_json = json.dumps(result, ensure_ascii=False, default=str)[:20000]
            run.finished_at = datetime.utcnow()
            routine.last_status = "ok"
            routine.last_summary = summary
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            run = db.get(AgentRoutineRun, run.id)
            if run is not None:
                run.status = "error"
                run.error_text = str(exc)[:2000]
                run.finished_at = datetime.utcnow()
            routine.last_status = "error"
            routine.last_summary = None
            if "inactive_or_missing_actor" in str(exc) or "invalid_actor" in str(exc):
                routine.enabled = False
            db.commit()
            logger.exception("Routine %s execution failed", routine_id)
            return {"ok": False, "error": str(exc)}

        # One-shot routines disable themselves after a successful run so the
        # scheduler won't re-register them on the next sync.
        if (routine.schedule_kind or "recurring") == "once":
            routine.enabled = False
            db.commit()

        # Deliver (best-effort, never fails the run)
        if routine.kind == "receipt_audit":
            report_text = _format_receipt_audit_report(routine, result)
        else:
            report_text = _format_report(routine, result)
        can_deliver_to_channel = is_builtin or bool(owner_auth and owner_auth.is_admin)
        if routine.deliver_to_channel and can_deliver_to_channel:
            try:
                await _deliver_to_channel(report_text)
            except Exception:
                logger.debug("routine channel delivery failed", exc_info=True)
        if routine.deliver_to_chat and routine.created_by_user_id:
            try:
                _deliver_to_chat(db, routine, report_text, result)
            except Exception:
                logger.debug("routine chat delivery failed", exc_info=True)

        return {"ok": True, "summary": run.summary, "run_id": str(run.id)}


async def _deliver_to_channel(text: str) -> None:
    token = os.getenv("AUTH_BOT_TOKEN", "").strip()
    chat_id = int(os.getenv("RECEIPT_LOG_CHAT_ID", "0") or 0)
    if not token or not chat_id:
        return
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
        await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        )


def _deliver_to_chat(db: Session, routine: AgentRoutine, text: str, result: Dict[str, Any]) -> None:
    from services.ai_agent.notification_service import create_notification

    create_notification(
        db,
        scope="personal",
        user_id=int(routine.created_by_user_id),
        notification_type="routine_report",
        payload={"routine_id": str(routine.id), "name": routine.name, "text": text,
                 "has_issues": bool((result.get("data") or {}).get("has_issues"))},
    )


def ensure_builtin_routines(db: Session) -> int:
    """Seed the built-in daily receipt-audit routine if it doesn't exist yet.

    Idempotent: keyed off the reserved name + a config marker. Returns the
    number of routines created (0 or 1).
    """
    existing = (
        db.query(AgentRoutine)
        .filter(AgentRoutine.name == _BUILTIN_RECEIPT_AUDIT_NAME)
        .first()
    )
    if existing is not None:
        return 0
    create_routine(
        db,
        name=_BUILTIN_RECEIPT_AUDIT_NAME,
        task_prompt=(
            "Сверить локально скачанные чеки из Telegram с базой данных, "
            "проверить точность парсинга и отчитаться в канал логирования."
        ),
        cron="7 13 * * *",
        kind="receipt_audit",
        description="Ежедневный аудит точности парсинга чеков. Создаётся автоматически.",
        enabled=True,
        deliver_to_channel=True,
        deliver_to_chat=False,
        created_by_user_id=None,
        schedule_kind="recurring",
        config={"builtin": _BUILTIN_RECEIPT_AUDIT_MARKER, "days": 7},
    )
    logger.info("Seeded builtin receipt_audit routine")
    return 1
