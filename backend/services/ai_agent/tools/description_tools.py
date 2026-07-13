"""AI-agent tools for merchant operator descriptions.

Auto-write (no confirmation): the agent reads operators off transactions,
looks each one up on the web, asks DeepSeek for a 5-8 word label and stores it
via :mod:`services.description_service` with ``source="agent"``. A rollback tool
removes agent-authored descriptions.

Descriptions are resolved at read time on transactions, so a stored description
applies retroactively to every transaction with the same normalized operator.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import Description, OperatorDescriptionLink, Transaction
from services import description_service
from services.ai_provider import get_text_ai_provider
from services.web_search import search_operator_snippets

logger = logging.getLogger(__name__)

_DEFAULT_AUTO_LIMIT = 8
_MAX_AUTO_LIMIT = 12
_MAX_LIST_LIMIT = 200
_DESCRIPTION_MAX_LEN = 120
# Per-operator hard cap (web search + summary) so one hung lookup can't stall.
_PER_OPERATOR_TIMEOUT = 15.0
# Yield + throttle between operators: keeps the event loop responsive and avoids
# DuckDuckGo rate-limiting on rapid sequential requests.
_INTER_OPERATOR_DELAY = 0.25
# Only one bulk run at a time across the worker — concurrent invocations would
# multiply outbound calls and starve the single uvicorn worker.
_auto_running = False


def _user_id(current_user: Dict[str, Any]) -> Optional[int]:
    raw = current_user.get("user_id") or current_user.get("id")
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _emit(progress_cb: Optional[Callable[[Dict[str, Any]], None]], payload: Dict[str, Any]) -> None:
    if progress_cb is None:
        return
    try:
        progress_cb(payload)
    except Exception:  # noqa: BLE001
        pass


async def _summarize_operator(operator_raw: str, snippets: List[str]) -> Optional[str]:
    """Return a short Russian label (5-8 words) for an operator from web snippets."""
    joined = "\n".join(snippets).strip()
    if not joined:
        return None

    provider = get_text_ai_provider()
    if getattr(provider, "enabled", False):
        try:
            text = await provider.complete_text(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты определяешь, что за продавец или сервис, по сниппетам из интернета. "
                            "Ответь по-русски одним коротким описанием в 5-8 слов. "
                            "Только описание, без кавычек, без префиксов."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Оператор: {operator_raw}\n\nСниппеты:\n{joined}",
                    },
                ],
                temperature=0.2,
                max_tokens=60,
            )
            text = (text or "").strip().strip('"').strip()
            if text:
                return text[:_DESCRIPTION_MAX_LEN]
        except Exception as exc:  # noqa: BLE001
            logger.warning("DeepSeek summarize failed for %r: %s", operator_raw, exc)

    # Fallback: first snippet, trimmed.
    return snippets[0][:_DESCRIPTION_MAX_LEN]


def _missing_operators(db: Session, limit: int, only_missing: bool) -> List[str]:
    rows = (
        db.query(Transaction.operator_raw)
        .filter(Transaction.operator_raw.isnot(None), func.length(Transaction.operator_raw) > 0)
        .distinct()
        .all()
    )
    seen: set[str] = set()
    operators: List[str] = []
    for (op,) in rows:
        op = (op or "").strip()
        if not op:
            continue
        key = description_service.normalize_key(op)
        if not key or key in seen:
            continue
        if only_missing and description_service.resolve(db, op) is not None:
            continue
        seen.add(key)
        operators.append(op)
        if len(operators) >= limit:
            break
    return operators


async def auto_describe_operators(
    db: Session,
    current_user: Dict[str, Any],
    scope: Optional[dict],
    args: Dict[str, Any],
) -> Dict[str, Any]:
    """Look up operators on the web and auto-write short descriptions (source=agent)."""
    progress_cb = args.get("_progress_callback")
    try:
        limit = int(args.get("limit") or _DEFAULT_AUTO_LIMIT)
    except (TypeError, ValueError):
        limit = _DEFAULT_AUTO_LIMIT
    limit = max(1, min(_MAX_AUTO_LIMIT, limit))
    only_missing = args.get("only_missing", True)
    if isinstance(only_missing, str):
        only_missing = only_missing.strip().lower() not in {"false", "0", "no", "нет"}

    global _auto_running
    if _auto_running:
        msg = "Описание операторов уже выполняется — дождитесь завершения."
        return {
            "summary": "Уже выполняется",
            "assistant_message": msg,
            "cards": [{"type": "info", "title": "Описания операторов", "body": msg}],
            "data": {"described": 0, "skipped": 0, "total": 0, "busy": True},
        }

    operators = _missing_operators(db, limit, bool(only_missing))
    total = len(operators)
    if total == 0:
        msg = "Все операторы уже описаны — добавлять нечего." if only_missing else "Операторов не найдено."
        _emit(progress_cb, {"step": "done", "percent": 100, "completed": True})
        return {
            "summary": "Описывать нечего",
            "assistant_message": msg,
            "cards": [{"type": "info", "title": "Описания операторов", "body": msg}],
            "data": {"described": 0, "skipped": 0, "total": 0},
        }

    described: List[Dict[str, str]] = []
    skipped: List[str] = []
    user_id = _user_id(current_user)

    _auto_running = True
    try:
        for i, op in enumerate(operators):
            _emit(
                progress_cb,
                {
                    "step": "web_search",
                    "operator": op,
                    "current": i,
                    "total": total,
                    "percent": int(i / total * 90),
                },
            )
            try:
                async def _lookup(operator: str = op) -> Optional[str]:
                    snippets = await search_operator_snippets(operator)
                    return await _summarize_operator(operator, snippets)

                text = await asyncio.wait_for(_lookup(), timeout=_PER_OPERATOR_TIMEOUT)
                if not text:
                    skipped.append(op)
                else:
                    description_service.set_for_operator(db, op, text, source="agent", user_id=user_id)
                    described.append({"operator": op, "description": text})
            except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
                logger.warning("auto_describe_operators failed for %r: %s", op, exc)
                skipped.append(op)
            # Yield to the event loop + throttle external requests.
            await asyncio.sleep(_INTER_OPERATOR_DELAY)
    finally:
        _auto_running = False

    _emit(progress_cb, {"step": "done", "percent": 100, "completed": True})

    summary = f"Описано {len(described)} операторов"
    if skipped:
        summary += f", пропущено {len(skipped)}"
    cards = [
        {
            "type": "table",
            "title": "Добавленные описания",
            "body": {
                "rows": described,
                "skipped": skipped[:20],
            },
        }
    ]
    msg_lines = [f"<b>Описано операторов:</b> {len(described)} из {total}"]
    for d in described[:15]:
        msg_lines.append(f"  · {d['operator']} → {d['description']}")
    if skipped:
        msg_lines.append(f"  · не нашёл в интернете: {len(skipped)}")

    return {
        "summary": summary,
        "assistant_message": "\n".join(msg_lines),
        "cards": cards,
        "data": {
            "described": len(described),
            "skipped": len(skipped),
            "total": total,
            "rows": described,
            "skipped_operators": skipped,
        },
    }


async def set_operator_description(
    db: Session,
    current_user: Dict[str, Any],
    scope: Optional[dict],
    args: Dict[str, Any],
) -> Dict[str, Any]:
    """Write a description for a single operator directly (source=agent)."""
    operator_raw = (args.get("operator_raw") or "").strip()
    text = (args.get("text") or "").strip()
    if not operator_raw or not text:
        return {
            "summary": "Нет данных для записи описания",
            "assistant_message": "Нужны operator_raw и text.",
            "cards": [{"type": "warning", "title": "Описание оператора", "body": "Не указан оператор или текст."}],
        }

    description_service.set_for_operator(
        db, operator_raw, text, source="agent", user_id=_user_id(current_user)
    )
    msg = f"Записал описание для «{operator_raw}»: {text}"
    return {
        "summary": f"Описание для {operator_raw}",
        "assistant_message": msg,
        "cards": [
            {
                "type": "info",
                "title": "Описание оператора",
                "body": {"operator": operator_raw, "description": text},
            }
        ],
        "data": {"operator": operator_raw, "description": text},
    }


async def list_operator_descriptions(
    db: Session,
    current_user: Dict[str, Any],
    scope: Optional[dict],
    args: Dict[str, Any],
) -> Dict[str, Any]:
    """List stored operator descriptions (operator -> text + source)."""
    try:
        limit = int(args.get("limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(_MAX_LIST_LIMIT, limit))

    rows = (
        db.query(
            OperatorDescriptionLink.operator_key,
            OperatorDescriptionLink.source,
            Description.text,
        )
        .join(Description, Description.id == OperatorDescriptionLink.description_id)
        .order_by(OperatorDescriptionLink.id.desc())
        .limit(limit)
        .all()
    )
    items = [
        {"operator": key, "description": text, "source": source}
        for key, source, text in rows
    ]
    msg_lines = [f"<b>Сохранённых описаний:</b> {len(items)}"]
    for it in items[:20]:
        msg_lines.append(f"  · {it['operator']} → {it['description']} ({it['source']})")

    return {
        "summary": f"Описаний: {len(items)}",
        "assistant_message": "\n".join(msg_lines),
        "cards": [
            {
                "type": "table",
                "title": "Описания операторов",
                "body": {"rows": items},
            }
        ],
        "data": {"items": items, "count": len(items)},
    }


async def rollback_operator_descriptions(
    db: Session,
    current_user: Dict[str, Any],
    scope: Optional[dict],
    args: Dict[str, Any],
) -> Dict[str, Any]:
    """Remove agent-authored descriptions (all of them, or a given operator list)."""
    raw_operators = args.get("operators")
    operators: List[str] = []
    if isinstance(raw_operators, list):
        operators = [str(o).strip() for o in raw_operators if str(o).strip()]
    all_agent = bool(args.get("all_agent"))

    if not operators or all_agent:
        agent_keys = [
            key
            for (key,) in db.query(OperatorDescriptionLink.operator_key)
            .filter(OperatorDescriptionLink.source == "agent")
            .all()
        ]
        removed = description_service.remove_for_operators(db, agent_keys, only_source="agent")
        scope_label = "все агентские описания"
    else:
        removed = description_service.remove_for_operators(db, operators, only_source="agent")
        scope_label = f"{len(operators)} операторов"

    msg = f"Удалено {removed} агентских описаний ({scope_label})."
    return {
        "summary": f"Откат: удалено {removed}",
        "assistant_message": msg,
        "cards": [{"type": "info", "title": "Откат описаний", "body": msg}],
        "data": {"removed": removed},
    }
