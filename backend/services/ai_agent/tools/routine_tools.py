"""Agent tool: create/list scheduled routines from a chat phrase.

Lets the operator say e.g. "каждый понедельник в 12 делай сверку всех транзакций"
and the agent creates a routine. Routines run SAFE preset actions only — this
tool never stores or executes generated code.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _ok(summary: str, **kw: Any) -> Dict[str, Any]:
    out = {"summary": summary, "assistant_message": summary}
    out.update(kw)
    return out


# Lightweight RU phrase → cron helper for the common cases the LLM may miss.
_WEEKDAY = {
    "понедельник": 1, "пн": 1, "вторник": 2, "вт": 2, "среда": 3, "ср": 3,
    "четверг": 4, "чт": 4, "пятница": 5, "пт": 5, "суббота": 6, "сб": 6,
    "воскресенье": 0, "вс": 0,
}


async def create_routine_tool(
    db: Session,
    current_user: Dict[str, Any],
    scope: Optional[dict],
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    from services.ai_agent.routine_service import create_routine, serialize_routine

    name = str(arguments.get("name") or "").strip() or "Сверка транзакций"
    task = str(arguments.get("task_prompt") or arguments.get("task") or "").strip()
    cron = str(arguments.get("cron") or "0 12 * * 1").strip()
    kind = str(arguments.get("kind") or "reconcile").strip().lower()
    if kind not in {"reconcile", "summary", "custom", "receipt_audit"}:
        kind = "custom"
    if not task:
        task = "Сверить все транзакции с локально сохранёнными сообщениями Telegram и сообщить об ошибках."

    user_id = None
    try:
        user_id = int(current_user.get("id") or current_user.get("user_id") or 0) or None
    except Exception:  # noqa: BLE001
        user_id = None

    try:
        row = create_routine(
            db,
            name=name,
            task_prompt=task,
            cron=cron,
            kind=kind,
            created_by_user_id=user_id,
        )
    except ValueError as exc:
        return _ok(
            f"Не удалось создать рутину: {exc}",
            cards=[{"type": "warning", "title": "Рутина не создана", "body": str(exc)}],
        )

    # Re-sync scheduler so it starts firing without a restart.
    try:
        from services.ai_agent import get_agent_scheduler_service
        get_agent_scheduler_service().sync_routines()
    except Exception:
        logger.debug("routine reschedule from tool skipped", exc_info=True)

    payload = serialize_routine(row)
    return _ok(
        f"Создана рутина «{name}» (расписание {cron}).",
        assistant_message=f"✅ Рутина «{name}» создана. Расписание: {cron}. Тип: {kind}.",
        cards=[{
            "type": "report",
            "title": f"Рутина · {name}",
            "body": {"cron": cron, "kind": kind, "task": task},
        }],
        data=payload,
    )


async def list_routines_tool(
    db: Session,
    current_user: Dict[str, Any],
    scope: Optional[dict],
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    from services.ai_agent.routine_service import list_routines

    items = list_routines(db)
    if not items:
        return _ok("Рутин пока нет.", assistant_message="Пока не настроено ни одной рутины.")
    lines = [f"• {r['name']} — {r['cron']} ({'вкл' if r['enabled'] else 'выкл'})" for r in items]
    return _ok(
        f"Рутин: {len(items)}",
        assistant_message="Текущие рутины:\n" + "\n".join(lines),
        data={"routines": items},
    )
