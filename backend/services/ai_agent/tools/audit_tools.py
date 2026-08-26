"""Deep audit / reconciliation tools for the AI agent.

These tools answer questions like:
- "сверь monitored chats с базой за прошлую неделю"
- "найди все дубликаты"
- "найди транзакции без mapping"
- "проверь, что все чеки из чата X распарсились"
- "что упало при обработке"

They never mutate DB state directly — for fixes the agent emits a
`confirmation_payload` or schedules a Celery job.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, List, Optional

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from database.models import (
    MonitoredBotChat,
    ReceiptProcessingTask,
    Transaction,
)

logger = logging.getLogger(__name__)


def _ok(summary: str, **kw: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"summary": summary}
    out.update(kw)
    return out


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _scope_chat_ids(scope: Optional[dict]) -> Optional[List[int]]:
    if not scope or not isinstance(scope, dict):
        return None
    if "allowed_chat_ids" not in scope:
        return None
    chats = scope.get("allowed_chat_ids") or []
    try:
        return [int(c) for c in chats]
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
async def find_duplicate_transactions(db: Session, current_user: Dict[str, Any], scope: Optional[dict], arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Find groups of suspected duplicates by (amount, transaction_date, card_last_4)."""
    date_from = _parse_dt(arguments.get("date_from")) or (datetime.utcnow() - timedelta(days=90))
    date_to = _parse_dt(arguments.get("date_to")) or datetime.utcnow()
    threshold = max(1, int(arguments.get("min_group_size") or 2))

    q = db.query(
        Transaction.amount,
        Transaction.transaction_date,
        Transaction.card_last_4,
        Transaction.operator_raw,
        func.array_agg(Transaction.id).label("ids"),
        func.count(Transaction.id).label("cnt"),
    ).filter(
        Transaction.transaction_date >= date_from,
        Transaction.transaction_date <= date_to,
        Transaction.amount.isnot(None),
    )
    chat_ids = _scope_chat_ids(scope)
    if chat_ids is not None:
        q = q.filter(
            Transaction.source_chat_id.in_(chat_ids)
        )
    q = (
        q.group_by(
            Transaction.amount,
            Transaction.transaction_date,
            Transaction.card_last_4,
            Transaction.operator_raw,
        )
        .having(func.count(Transaction.id) >= threshold)
        .order_by(func.count(Transaction.id).desc())
        .limit(int(arguments.get("limit") or 20))
    )

    groups = []
    for amount, dt, card, operator, ids, cnt in q.all():
        groups.append(
            {
                "amount": str(amount),
                "transaction_date": dt.isoformat() if dt else None,
                "card_last_4": card,
                "operator_raw": operator,
                "transaction_ids": list(ids or []),
                "count": int(cnt),
            }
        )

    msg_lines = [f"<b>Найдено групп дубликатов:</b> {len(groups)}"]
    for g in groups[:10]:
        msg_lines.append(
            f"  · {g['count']}× по {g['amount']} от {g['transaction_date']} "
            f"карта ***{g['card_last_4'] or '—'} ({g['operator_raw'] or '—'})"
        )

    return _ok(
        f"Найдено {len(groups)} групп возможных дубликатов",
        assistant_message="\n".join(msg_lines),
        data={"groups": groups, "period": [date_from.isoformat(), date_to.isoformat()]},
        cards=[
            {
                "type": "audit",
                "title": "Дубликаты",
                "body": {
                    "total_groups": len(groups),
                    "preview": groups[:5],
                    "period": [date_from.isoformat(), date_to.isoformat()],
                },
            }
        ],
    )


async def find_orphan_transactions(db: Session, current_user: Dict[str, Any], scope: Optional[dict], arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Find transactions with empty / Unknown operator or missing application mapping."""
    date_from = _parse_dt(arguments.get("date_from")) or (datetime.utcnow() - timedelta(days=30))
    date_to = _parse_dt(arguments.get("date_to")) or datetime.utcnow()

    q = db.query(Transaction).filter(
        Transaction.transaction_date >= date_from,
        Transaction.transaction_date <= date_to,
        or_(
            Transaction.operator_raw.is_(None),
            func.lower(Transaction.operator_raw) == "unknown",
            Transaction.application_mapped.is_(None),
        ),
    )
    chat_ids = _scope_chat_ids(scope)
    if chat_ids is not None:
        q = q.filter(
            Transaction.source_chat_id.in_(chat_ids)
        )
    q = q.order_by(Transaction.transaction_date.desc()).limit(int(arguments.get("limit") or 100))

    rows = []
    for tx in q.all():
        rows.append(
            {
                "id": tx.id,
                "amount": str(tx.amount) if tx.amount is not None else None,
                "currency": tx.currency,
                "operator_raw": tx.operator_raw,
                "application_mapped": tx.application_mapped,
                "transaction_date": tx.transaction_date.isoformat() if tx.transaction_date else None,
                "source_chat_id": tx.source_chat_id,
            }
        )

    return _ok(
        f"Транзакций без оператора/маппинга: {len(rows)}",
        assistant_message=(
            f"Нашёл <b>{len(rows)}</b> транзакций без чёткого оператора или application mapping "
            f"за {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}."
        ),
        data={"rows": rows, "period": [date_from.isoformat(), date_to.isoformat()]},
        cards=[
            {
                "type": "audit",
                "title": "Без маппинга",
                "body": {"count": len(rows), "preview": rows[:8]},
            }
        ],
    )


def _norm_amount(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return str(Decimal(str(value)).quantize(Decimal("0.01")))
    except Exception:  # noqa: BLE001
        return None


def _resolve_source_text(db: Session, tx: Transaction) -> Optional[str]:
    """Prefer transactions.raw_message; fall back to cached tg_chat_messages."""
    raw = (getattr(tx, "raw_message", None) or "").strip()
    if raw:
        return raw
    chat_id = getattr(tx, "source_chat_id", None)
    message_id = getattr(tx, "source_message_id", None)
    if chat_id is None or message_id is None:
        return None
    try:
        from database.models import TgChatMessage  # type: ignore

        row = (
            db.query(TgChatMessage)
            .filter(
                TgChatMessage.chat_id == int(chat_id),
                TgChatMessage.message_id == int(message_id),
            )
            .first()
        )
    except Exception:  # noqa: BLE001
        return None
    if row is None:
        return None
    text = (getattr(row, "text", None) or "").strip()
    return text or None


async def verify_receipt_parse(db: Session, current_user: Dict[str, Any], scope: Optional[dict], arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Re-parse the source receipt text of a transaction and flag mismatches.

    Deterministic verification only: re-runs the regex cascade (no DeepSeek/OCR)
    on the stored source text and diffs the result against the saved fields.
    Read-only — never mutates DB state.
    """
    tx_id_arg = arguments.get("transaction_id")
    if tx_id_arg is None:
        return _ok(
            "Не указан transaction_id",
            assistant_message="Чтобы сверить распознавание, укажите transaction_id.",
        )
    try:
        tx_id = int(tx_id_arg)
    except (TypeError, ValueError):
        return _ok(
            "Некорректный transaction_id",
            assistant_message=f"transaction_id должен быть числом, получено: {tx_id_arg!r}.",
        )

    tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
    if tx is None:
        return _ok(
            f"Транзакция #{tx_id} не найдена",
            assistant_message=f"Транзакции с id {tx_id} нет в базе.",
        )

    chat_ids = _scope_chat_ids(scope)
    if chat_ids is not None and (
        tx.source_chat_id is None or tx.source_chat_id not in chat_ids
    ):
        return _ok(
            "Доступ к транзакции ограничен",
            assistant_message=f"Транзакция #{tx_id} не входит в ваш scope.",
        )

    source_text = _resolve_source_text(db, tx)
    if not source_text:
        return _ok(
            f"Нет исходного текста для сверки #{tx_id}",
            assistant_message=(
                f"У транзакции #{tx_id} нет сохранённого исходного текста "
                "(ни raw_message, ни сообщение в кэше) — сверка невозможна."
            ),
            data={"transaction_id": tx_id, "has_source": False, "verdict": "no_source"},
        )

    from parsers.regex_parser import RegexParser

    try:
        parsed = RegexParser().parse(source_text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("verify_receipt_parse regex failed for tx %s: %s", tx_id, exc)
        parsed = None

    if not parsed:
        return _ok(
            f"Не удалось переразобрать чек #{tx_id} regex-ом",
            assistant_message=(
                f"Regex-каскад не распознал исходный текст транзакции #{tx_id}. "
                "Возможно, чек разобран через AI/Vision — детерминированная сверка не применима."
            ),
            data={
                "transaction_id": tx_id,
                "has_source": True,
                "verdict": "suspicious",
                "discrepancies": [{"field": "parse", "stored": "ok", "parsed": None}],
            },
        )

    parsed_application: Optional[str] = None
    parsed_operator = parsed.get("operator_raw")
    if parsed_operator:
        try:
            from parsers.operator_mapper import OperatorMapper

            parsed_application = OperatorMapper(db).map_operator(str(parsed_operator))
        except Exception:  # noqa: BLE001
            parsed_application = None

    parsed_dt = parsed.get("transaction_date")
    parsed_date_iso = parsed_dt.isoformat() if hasattr(parsed_dt, "isoformat") else None
    stored_date_iso = tx.transaction_date.isoformat() if tx.transaction_date else None

    comparisons = [
        ("amount", _norm_amount(tx.amount), _norm_amount(parsed.get("amount"))),
        (
            "transaction_date",
            stored_date_iso[:16] if stored_date_iso else None,
            parsed_date_iso[:16] if parsed_date_iso else None,
        ),
        (
            "operator",
            (tx.operator_raw or "").strip() or None,
            (str(parsed_operator).strip() if parsed_operator else None),
        ),
        ("application", tx.application_mapped, parsed_application),
        ("card_last_4", tx.card_last_4, parsed.get("card_last_4")),
        ("transaction_type", tx.transaction_type, parsed.get("transaction_type")),
    ]

    discrepancies: List[Dict[str, Any]] = []
    for field, stored, parsed_val in comparisons:
        # Skip fields the regex layer cannot determine (None parsed) to avoid
        # false positives — application mapping in particular is best-effort.
        if parsed_val is None and field in {"application", "card_last_4"}:
            continue
        if str(stored or "") != str(parsed_val or ""):
            discrepancies.append({"field": field, "stored": stored, "parsed": parsed_val})

    verdict = "ok" if not discrepancies else "suspicious"
    if discrepancies:
        diff_lines = "\n".join(
            f"  · <b>{d['field']}</b>: сохранено {d['stored'] or '—'} ≠ разобрано {d['parsed'] or '—'}"
            for d in discrepancies
        )
        assistant_message = (
            f"⚠️ Транзакция #{tx_id}: найдено {len(discrepancies)} расхождений при сверке "
            f"с исходным текстом:\n{diff_lines}"
        )
    else:
        assistant_message = f"✅ Транзакция #{tx_id}: распознанные поля совпадают с исходным текстом."

    return _ok(
        f"Сверка #{tx_id}: {verdict} ({len(discrepancies)} расхождений)",
        assistant_message=assistant_message,
        data={
            "transaction_id": tx_id,
            "has_source": True,
            "verdict": verdict,
            "discrepancies": discrepancies,
        },
        cards=[
            {
                "type": "audit",
                "title": f"Сверка чека #{tx_id}",
                "body": {
                    "verdict": verdict,
                    "discrepancies": discrepancies,
                    "parsing_method": parsed.get("parsing_method"),
                },
            }
        ],
    )


async def chat_vs_db_reconcile(db: Session, current_user: Dict[str, Any], scope: Optional[dict], arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Reconcile a monitored chat: how many messages cached vs how many turned into transactions.

    Args: chat_id (int, required), date_from, date_to (optional)
    """
    chat_id_arg = arguments.get("chat_id")
    if not chat_id_arg:
        return _ok(
            "Не указан chat_id",
            assistant_message="Чтобы сверить чат с базой, скажите chat_id (например, -1003547724919).",
        )
    chat_id = int(chat_id_arg)
    chat_ids = _scope_chat_ids(scope)
    if chat_ids is not None and chat_id not in chat_ids:
        return _ok(
            "Доступ к чату ограничен",
            assistant_message=f"Чат {chat_id} не входит в ваш scope.",
        )

    date_from = _parse_dt(arguments.get("date_from")) or (datetime.utcnow() - timedelta(days=7))
    date_to = _parse_dt(arguments.get("date_to")) or datetime.utcnow()

    # Cached chat messages (text + media references)
    cached_count = _safe_count_cached_messages(db, chat_id, date_from, date_to)
    # Receipt processing tasks issued for this chat
    tasks_q = db.query(ReceiptProcessingTask).filter(
        ReceiptProcessingTask.chat_id == chat_id,
        ReceiptProcessingTask.created_at >= date_from,
        ReceiptProcessingTask.created_at <= date_to,
    )
    tasks_total = tasks_q.count()
    tasks_done = tasks_q.filter(ReceiptProcessingTask.status == "done").count()
    tasks_failed = tasks_q.filter(ReceiptProcessingTask.status == "failed").count()
    tasks_processing = tasks_q.filter(
        ReceiptProcessingTask.status.in_(["queued", "processing"])
    ).count()

    # Transactions saved
    tx_q = db.query(Transaction).filter(
        Transaction.source_chat_id == chat_id,
        Transaction.created_at >= date_from,
        Transaction.created_at <= date_to,
    )
    tx_count = tx_q.count()

    # Failed reasons (top 5)
    failed_reasons = (
        db.query(
            ReceiptProcessingTask.error,
            func.count(ReceiptProcessingTask.id),
        )
        .filter(
            ReceiptProcessingTask.chat_id == chat_id,
            ReceiptProcessingTask.status == "failed",
            ReceiptProcessingTask.created_at >= date_from,
            ReceiptProcessingTask.created_at <= date_to,
        )
        .group_by(ReceiptProcessingTask.error)
        .order_by(func.count(ReceiptProcessingTask.id).desc())
        .limit(5)
        .all()
    )

    issues: List[Dict[str, Any]] = []
    if tasks_failed:
        issues.append(
            {
                "kind": "failed_tasks",
                "count": tasks_failed,
                "reasons": [
                    {"reason": (r or "—")[:120], "count": int(c)}
                    for r, c in failed_reasons
                ],
            }
        )
    if tasks_processing:
        issues.append({"kind": "stuck_tasks", "count": tasks_processing})
    if cached_count is not None and cached_count > tasks_total:
        issues.append(
            {
                "kind": "uncovered_messages",
                "count": cached_count - tasks_total,
                "hint": "часть сообщений в кэше не дошла до парсера",
            }
        )

    msg = (
        f"<b>Чат {chat_id}</b> · {date_from.strftime('%d.%m.%Y')}–{date_to.strftime('%d.%m.%Y')}\n"
        f"  · сообщений в кэше: {cached_count if cached_count is not None else '—'}\n"
        f"  · задач обработки: {tasks_total} (done={tasks_done}, failed={tasks_failed}, "
        f"в работе={tasks_processing})\n"
        f"  · транзакций сохранено: {tx_count}\n"
    )
    if issues:
        msg += "  · <b>проблемы:</b> " + ", ".join(
            f"{i['kind']}={i['count']}" for i in issues
        )
    else:
        msg += "  · <b>проблем нет</b>"

    return _ok(
        f"Сверка чата {chat_id}: {tx_count} транзакций, {len(issues)} проблем",
        assistant_message=msg,
        data={
            "chat_id": chat_id,
            "period": [date_from.isoformat(), date_to.isoformat()],
            "cached_messages": cached_count,
            "tasks": {
                "total": tasks_total,
                "done": tasks_done,
                "failed": tasks_failed,
                "processing": tasks_processing,
            },
            "transactions": tx_count,
            "issues": issues,
        },
        cards=[
            {
                "type": "audit",
                "title": f"Сверка чата {chat_id}",
                "body": {
                    "tasks_total": tasks_total,
                    "tasks_failed": tasks_failed,
                    "transactions": tx_count,
                    "issues": issues[:5],
                },
            }
        ],
    )


def _safe_count_cached_messages(
    db: Session, chat_id: int, date_from: datetime, date_to: datetime
) -> Optional[int]:
    """Count rows in `monitored_chat_messages` if the table exists, else None."""
    try:
        from database.models import MonitoredChatMessage  # type: ignore
        return (
            db.query(MonitoredChatMessage)
            .filter(
                MonitoredChatMessage.chat_id == chat_id,
                MonitoredChatMessage.message_date >= date_from,
                MonitoredChatMessage.message_date <= date_to,
            )
            .count()
        )
    except Exception:  # noqa: BLE001
        # Fallback: legacy `tg_chat_messages`
        try:
            from database.models import TgChatMessage  # type: ignore
            return (
                db.query(TgChatMessage)
                .filter(
                    TgChatMessage.chat_id == chat_id,
                    TgChatMessage.message_date >= date_from,
                    TgChatMessage.message_date <= date_to,
                )
                .count()
            )
        except Exception:  # noqa: BLE001
            return None


async def weekly_health_check(db: Session, current_user: Dict[str, Any], scope: Optional[dict], arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Run a full health check across all monitored chats for the past 7 days."""
    end = _parse_dt(arguments.get("date_to")) or datetime.utcnow()
    start = _parse_dt(arguments.get("date_from")) or (end - timedelta(days=7))

    chats: List[Dict[str, Any]] = []
    chat_ids = _scope_chat_ids(scope)
    monitored = db.query(MonitoredBotChat).filter(MonitoredBotChat.enabled.is_(True)).all()
    for ch in monitored:
        if chat_ids is not None and ch.chat_id not in chat_ids:
            continue
        result = await chat_vs_db_reconcile(
            db=db,
            current_user=current_user,
            scope=scope,
            arguments={
                "chat_id": ch.chat_id,
                "date_from": start.isoformat(),
                "date_to": end.isoformat(),
            },
        )
        chats.append(
            {
                "chat_id": ch.chat_id,
                "chat_title": getattr(ch, "chat_title", None) or str(ch.chat_id),
                "summary": result.get("summary"),
                "data": result.get("data") or {},
            }
        )

    total_tx = sum((c["data"].get("transactions") or 0) for c in chats)
    total_failed = sum(
        ((c["data"].get("tasks") or {}).get("failed") or 0) for c in chats
    )
    total_stuck = sum(
        ((c["data"].get("tasks") or {}).get("processing") or 0) for c in chats
    )
    total_orphan_groups = 0  # filled below

    dups = await find_duplicate_transactions(
        db=db,
        current_user=current_user,
        scope=scope,
        arguments={
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "limit": 100,
        },
    )
    duplicate_groups = (dups.get("data") or {}).get("groups") or []

    orphans = await find_orphan_transactions(
        db=db,
        current_user=current_user,
        scope=scope,
        arguments={
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "limit": 500,
        },
    )
    orphan_rows = (orphans.get("data") or {}).get("rows") or []
    total_orphan_groups = len(orphan_rows)

    has_issues = bool(
        total_failed or total_stuck or duplicate_groups or orphan_rows
    )

    summary = (
        f"Здоровье ({start.strftime('%d.%m')} — {end.strftime('%d.%m')}): "
        f"{len(chats)} чатов, {total_tx} тр., "
        f"{total_failed} failed, {len(duplicate_groups)} дубл-групп, "
        f"{total_orphan_groups} без маппинга"
    )

    return _ok(
        summary,
        assistant_message=summary,
        data={
            "period": [start.isoformat(), end.isoformat()],
            "chats": chats,
            "totals": {
                "transactions": total_tx,
                "failed": total_failed,
                "stuck": total_stuck,
                "duplicate_groups": len(duplicate_groups),
                "orphan_rows": total_orphan_groups,
            },
            "duplicate_groups": duplicate_groups,
            "orphan_rows": orphan_rows[:50],
            "has_issues": has_issues,
        },
        cards=[
            {
                "type": "audit",
                "title": "Недельный health-check",
                "body": {
                    "period": f"{start.strftime('%d.%m')} — {end.strftime('%d.%m')}",
                    "chats_scanned": len(chats),
                    "total_transactions": total_tx,
                    "failed": total_failed,
                    "stuck": total_stuck,
                    "duplicate_groups": len(duplicate_groups),
                    "orphan_rows": total_orphan_groups,
                    "has_issues": has_issues,
                },
            }
        ],
    )


async def weekly_report_autofix(db: Session, current_user: Dict[str, Any], scope: Optional[dict], arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Build a confirmation_payload that, when confirmed, fixes the weekly issues.

    Aggregates duplicate-group merges and orphan reparses, returns a single
    preview that the user must confirm via the standard confirm flow.
    """
    from services.ai_agent.authorization import actor_id, current_agent_authorization

    auth = current_agent_authorization(db, actor_id(current_user))
    auth.require_admin("weekly_autofix")

    health = await weekly_health_check(
        db=db, current_user=current_user, scope=scope, arguments=arguments
    )
    data = health.get("data") or {}
    duplicate_groups = data.get("duplicate_groups") or []
    orphan_rows = data.get("orphan_rows") or []

    if not (duplicate_groups or orphan_rows):
        return _ok(
            "Нечего исправлять — здоровье в норме",
            assistant_message="По текущему health-check всё чисто. Исправлять нечего.",
        )

    actions: List[Dict[str, Any]] = []
    for group in duplicate_groups[:25]:
        ids = list(group.get("transaction_ids") or [])
        if len(ids) < 2:
            continue
        actions.append(
            {
                "kind": "merge_duplicates",
                "transaction_ids": ids,
                "keep_id": min(ids),
                "amount": group.get("amount"),
                "transaction_date": group.get("transaction_date"),
            }
        )
    for row in orphan_rows[:25]:
        actions.append({"kind": "reparse_transaction", "transaction_id": row["id"]})

    summary = (
        f"План исправлений: {len(actions)} действий "
        f"(дубл: {len(duplicate_groups)}, orphan: {len(orphan_rows)})"
    )
    return _ok(
        summary,
        assistant_message=summary + ". Нажмите «Исправить», чтобы применить.",
        cards=[
            {
                "type": "audit",
                "title": "Авто-исправление",
                "body": {
                    "duplicate_groups": len(duplicate_groups),
                    "orphan_rows": len(orphan_rows),
                    "preview_actions": actions[:8],
                },
            }
        ],
        data={
            "actions_total": len(actions),
            "duplicate_groups": len(duplicate_groups),
            "orphan_rows": len(orphan_rows),
        },
        confirmation_payload={
            "action": "weekly_autofix",
            "args": {"actions": actions},
            "idempotency_key": f"weekly-autofix-{int(datetime.utcnow().timestamp())}",
        },
        requires_confirmation=True,
    )
