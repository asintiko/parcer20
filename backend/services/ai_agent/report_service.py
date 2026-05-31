from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_
from sqlalchemy import literal
from sqlalchemy.orm import Session

from config.ai_models import AI_AGENT_RECEIPT_GRACE_MINUTES
from database.models import (
    AgentReport,
    AgentReportItem,
    AutomationSuggestion,
    DuplicateSuggestion,
    ReceiptProcessingTask,
    ReconciliationSuggestion,
    Transaction,
)
from services.ai_agent.notification_service import create_notification
from services.telegram_cache_service import TelegramCacheService


JsonDict = Dict[str, Any]


def _dump_json(payload: Optional[JsonDict]) -> str:
    return json.dumps(payload or {}, ensure_ascii=False)


def _load_json(value: Optional[str]) -> JsonDict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def serialize_report_item(row: AgentReportItem) -> JsonDict:
    return {
        "id": str(row.id),
        "report_id": str(row.report_id),
        "issue_type": row.issue_type,
        "severity": row.severity,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "confidence": row.confidence,
        "status": row.status,
        "title": row.title,
        "description": row.description,
        "suggested_action": _load_json(row.suggested_action_json),
        "assignee_user_id": int(row.assignee_user_id) if row.assignee_user_id is not None else None,
        "claimed_at": row.claimed_at.isoformat() if row.claimed_at else None,
        "released_at": row.released_at.isoformat() if row.released_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def serialize_report(row: AgentReport, items: Optional[List[AgentReportItem]] = None) -> JsonDict:
    return {
        "id": str(row.id),
        "created_by_user_id": int(row.created_by_user_id),
        "thread_id": str(row.thread_id) if row.thread_id else None,
        "scope": row.scope,
        "title": row.title,
        "period_start": row.period_start.isoformat() if row.period_start else None,
        "period_end": row.period_end.isoformat() if row.period_end else None,
        "status": row.status,
        "summary": _load_json(row.summary_json),
        "payload": _load_json(row.payload_json),
        "items": [serialize_report_item(item) for item in (items or [])],
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _build_report_title(scope: str, period_start: Optional[datetime], period_end: Optional[datetime]) -> str:
    if period_start and period_end:
        return f"Отчет ИИ-агента {period_start.date().isoformat()} - {period_end.date().isoformat()}"
    return "Командный weekly-отчет" if scope == "team" else "Личный отчет ИИ-агента"


def _create_report_item(
    db: Session,
    *,
    report_id: UUID,
    issue_type: str,
    severity: str,
    entity_type: str,
    entity_id: Optional[str],
    title: str,
    description: Optional[str],
    confidence: Optional[float] = None,
    suggested_action: Optional[JsonDict] = None,
) -> AgentReportItem:
    row = AgentReportItem(
        id=uuid4(),
        report_id=report_id,
        issue_type=issue_type,
        severity=severity,
        entity_type=entity_type,
        entity_id=entity_id,
        title=title[:255],
        description=description,
        confidence=confidence,
        suggested_action_json=_dump_json(suggested_action),
    )
    db.add(row)
    db.flush()
    return row


def _audit_issue_action(issue: JsonDict) -> JsonDict:
    filters: JsonDict = {}
    chat_id = issue.get("chat_id")
    if chat_id is not None:
        filters["source_chat_ids"] = [int(chat_id)]
    if issue.get("message_id") is not None:
        filters["search"] = str(issue.get("message_id"))
    return {
        "kind": "open_transaction",
        "transaction_id": int(issue.get("transaction_id")) if issue.get("transaction_id") is not None else None,
        "navigation_target": {
            "route": "/transactions",
            "row_id": int(issue.get("transaction_id")) if issue.get("transaction_id") is not None else None,
            "column_id": "raw_message" if issue.get("category") in {"FAILED_PARSE", "MISSING_IN_DB"} else "amount",
            "focus_mode": "row" if issue.get("transaction_id") is not None else "filter",
            "suggested_filters": filters,
            "sort_hint": {"sort_by": "transaction_date", "sort_dir": "desc"},
            "page_hint": 1,
        },
    }


def _audit_issue_severity(category: str) -> str:
    if category in {"FAILED_PARSE", "MISSING_IN_DB", "CURSOR_STALE", "CACHE_GAP"}:
        return "high"
    if category in {"DUPLICATE", "ORPHANED_IN_DB"}:
        return "medium"
    return "low"


def _maybe_add_sample_items(db: Session, report_id: UUID, period_start: Optional[datetime], period_end: Optional[datetime]) -> List[AgentReportItem]:
    items: List[AgentReportItem] = []
    if period_start is not None and period_end is not None:
        audit_summary = TelegramCacheService(db).audit_monitored_chats(
            date_from=period_start,
            date_to=period_end,
            grace_minutes=AI_AGENT_RECEIPT_GRACE_MINUTES,
        )
    else:
        audit_summary = {"issues": [], "categories": {}}

    for issue in (audit_summary.get("issues") or [])[:12]:
        items.append(
            _create_report_item(
                db,
                report_id=report_id,
                issue_type=str(issue.get("category") or "monitor_issue").lower(),
                severity=_audit_issue_severity(str(issue.get("category") or "")),
                entity_type="telegram_cache_message" if issue.get("message_id") is not None else "monitor_chat",
                entity_id=f"{issue.get('chat_id')}:{issue.get('message_id')}" if issue.get("message_id") is not None else str(issue.get("chat_id") or ""),
                title=str(issue.get("title") or "Проблема мониторинга")[:255],
                description=str(issue.get("summary") or "")[:500],
                suggested_action=_audit_issue_action(issue),
            )
        )

    tx_query = db.query(Transaction)
    if period_start:
        tx_query = tx_query.filter(Transaction.transaction_date >= period_start)
    if period_end:
        tx_query = tx_query.filter(Transaction.transaction_date <= period_end)

    unmapped = (
        tx_query.filter(or_(Transaction.application_mapped == None, Transaction.application_mapped == ""))  # noqa: E711
        .order_by(Transaction.transaction_date.desc())
        .limit(5)
        .all()
    )
    for tx in unmapped:
        items.append(
            _create_report_item(
                db,
                report_id=report_id,
                issue_type="unmapped_transaction",
                severity="medium",
                entity_type="transaction",
                entity_id=str(tx.id),
                title=f"Неразмеченная транзакция #{tx.id}",
                description=(tx.operator_raw or tx.raw_message or "")[:500],
                confidence=tx.parsing_confidence,
                suggested_action={"kind": "open_transaction", "transaction_id": int(tx.id)},
            )
        )

    failed_tasks_query = db.query(ReceiptProcessingTask).filter(ReceiptProcessingTask.status == "failed")
    if period_start:
        failed_tasks_query = failed_tasks_query.filter(ReceiptProcessingTask.created_at >= period_start)
    if period_end:
        failed_tasks_query = failed_tasks_query.filter(ReceiptProcessingTask.created_at <= period_end)
    failed_tasks = failed_tasks_query.order_by(ReceiptProcessingTask.updated_at.desc()).limit(5).all()
    for task in failed_tasks:
        items.append(
            _create_report_item(
                db,
                report_id=report_id,
                issue_type="failed_parse",
                severity="high",
                entity_type="receipt_processing_task",
                entity_id=str(task.id),
                title=f"Ошибка парсинга сообщения {task.chat_id}/{task.message_id}",
                description=(task.error or task.raw_message or "")[:500],
                suggested_action={
                    "kind": "investigate_processing_error",
                    "chat_id": int(task.chat_id),
                    "message_id": int(task.message_id),
                },
            )
        )

    dupes = (
        db.query(DuplicateSuggestion)
        .filter(DuplicateSuggestion.status == "pending")
        .order_by(DuplicateSuggestion.created_at.desc())
        .limit(5)
        .all()
    )
    for item in dupes:
        items.append(
            _create_report_item(
                db,
                report_id=report_id,
                issue_type="duplicate_candidate",
                severity="medium",
                entity_type="duplicate_suggestion",
                entity_id=str(item.id),
                title=f"Кандидат на merge дубля #{item.primary_transaction_id}/{item.duplicate_transaction_id}",
                description=(item.reasoning or "")[:500],
                confidence=item.confidence,
                suggested_action={
                    "kind": "review_duplicate",
                    "duplicate_suggestion_id": str(item.id),
                    "primary_transaction_id": int(item.primary_transaction_id),
                    "duplicate_transaction_id": int(item.duplicate_transaction_id),
                },
            )
        )

    reconcile = (
        db.query(ReconciliationSuggestion)
        .filter(ReconciliationSuggestion.status == "pending")
        .order_by(ReconciliationSuggestion.created_at.desc())
        .limit(5)
        .all()
    )
    for item in reconcile:
        items.append(
            _create_report_item(
                db,
                report_id=report_id,
                issue_type="reconciliation_pending",
                severity="medium",
                entity_type="reconciliation_suggestion",
                entity_id=str(item.id),
                title=f"Reconciliation {item.category} для {item.chat_id}/{item.message_id}",
                description=(item.reasoning or "")[:500],
                confidence=item.confidence,
                suggested_action={
                    "kind": "review_reconciliation",
                    "reconciliation_suggestion_id": str(item.id),
                    "chat_id": int(item.chat_id),
                    "message_id": int(item.message_id),
                    "transaction_id": int(item.transaction_id) if item.transaction_id is not None else None,
                },
            )
        )

    return items


def generate_report(
    db: Session,
    *,
    created_by_user_id: int,
    thread_id: Optional[UUID] = None,
    scope: str = "personal",
    period_start: Optional[datetime] = None,
    period_end: Optional[datetime] = None,
    group_by: Optional[str] = None,
    publish_team_notification: bool = False,
    publish_immediately: Optional[bool] = None,
) -> JsonDict:
    if period_start is not None and period_end is not None:
        audit_summary = TelegramCacheService(db).audit_monitored_chats(
            date_from=period_start,
            date_to=period_end,
            grace_minutes=AI_AGENT_RECEIPT_GRACE_MINUTES,
        )
    else:
        audit_summary = {"categories": {}, "issues": []}
    audit_categories = audit_summary.get("categories") or {}
    tx_query = db.query(Transaction)
    if period_start:
        tx_query = tx_query.filter(Transaction.transaction_date >= period_start)
    if period_end:
        tx_query = tx_query.filter(Transaction.transaction_date <= period_end)

    total_transactions = tx_query.count()
    unmapped_count = tx_query.filter(or_(Transaction.application_mapped == None, Transaction.application_mapped == "")).count()  # noqa: E711

    failed_query = db.query(ReceiptProcessingTask).filter(ReceiptProcessingTask.status == "failed")
    if period_start:
        failed_query = failed_query.filter(ReceiptProcessingTask.created_at >= period_start)
    if period_end:
        failed_query = failed_query.filter(ReceiptProcessingTask.created_at <= period_end)
    failed_parse_count = failed_query.count()

    pending_mapping_query = db.query(AutomationSuggestion).filter(AutomationSuggestion.status == "pending")
    if period_start:
        pending_mapping_query = pending_mapping_query.filter(AutomationSuggestion.created_at >= period_start)
    if period_end:
        pending_mapping_query = pending_mapping_query.filter(AutomationSuggestion.created_at <= period_end)
    pending_mapping_count = pending_mapping_query.count()

    pending_duplicates_query = db.query(DuplicateSuggestion).filter(DuplicateSuggestion.status == "pending")
    if period_start:
        pending_duplicates_query = pending_duplicates_query.filter(DuplicateSuggestion.created_at >= period_start)
    if period_end:
        pending_duplicates_query = pending_duplicates_query.filter(DuplicateSuggestion.created_at <= period_end)
    pending_duplicates_count = pending_duplicates_query.count()

    pending_reconciliation_query = db.query(ReconciliationSuggestion).filter(ReconciliationSuggestion.status == "pending")
    if period_start:
        pending_reconciliation_query = pending_reconciliation_query.filter(ReconciliationSuggestion.created_at >= period_start)
    if period_end:
        pending_reconciliation_query = pending_reconciliation_query.filter(ReconciliationSuggestion.created_at <= period_end)
    pending_reconciliation_count = pending_reconciliation_query.count()

    summary = {
        "total_transactions": total_transactions,
        "unmapped_transactions": unmapped_count,
        "failed_parse_tasks": failed_parse_count,
        "pending_mapping_suggestions": pending_mapping_count,
        "pending_duplicate_suggestions": pending_duplicates_count,
        "pending_reconciliation_suggestions": pending_reconciliation_count,
        "missing_receipts": int(audit_categories.get("MISSING_IN_DB") or 0),
        "sync_gaps": int(audit_categories.get("CACHE_GAP") or 0),
        "stale_cursors": int(audit_categories.get("CURSOR_STALE") or 0),
        "duplicate_receipts": int(audit_categories.get("DUPLICATE") or 0),
    }

    groupings: List[Dict[str, Any]] = []
    if group_by:
        group_expr = None
        if group_by == "day":
            group_expr = func.date_trunc("day", Transaction.transaction_date)
        elif group_by == "week":
            group_expr = func.date_trunc("week", Transaction.transaction_date)
        elif group_by == "month":
            group_expr = func.date_trunc("month", Transaction.transaction_date)
        elif group_by == "application":
            group_expr = func.coalesce(Transaction.application_mapped, literal("Без приложения"))
        elif group_by == "source":
            group_expr = Transaction.source_chat_id

        if group_expr is not None:
            try:
                rows = (
                    tx_query.with_entities(
                        group_expr.label("bucket"),
                        func.count(Transaction.id),
                        func.coalesce(func.sum(func.abs(Transaction.amount)), 0),
                    )
                    .group_by("bucket")
                    .order_by(func.count(Transaction.id).desc())
                    .limit(50)
                    .all()
                )
                for bucket, cnt, total in rows:
                    if isinstance(bucket, datetime):
                        key = bucket.date().isoformat()
                    elif bucket is None:
                        key = ""
                    else:
                        key = str(bucket)
                    groupings.append({"key": key, "count": int(cnt or 0), "total": str(total or 0)})
            except Exception:
                groupings = []

    payload = {
        "highlights": [
            f"Всего транзакций: {total_transactions}",
            f"Неразмеченных транзакций: {unmapped_count}",
            f"Ошибок парсинга: {failed_parse_count}",
            f"Чеков не дошло до таблицы: {int(audit_categories.get('MISSING_IN_DB') or 0)}",
            f"Пробелов в кеше: {int(audit_categories.get('CACHE_GAP') or 0)}",
            f"Проблемных курсоров: {int(audit_categories.get('CURSOR_STALE') or 0)}",
            f"Ожидают сопоставления: {pending_mapping_count}",
            f"Подозрение на дубли: {pending_duplicates_count}",
            f"Ожидают сверки: {pending_reconciliation_count}",
        ],
        "audit_summary": audit_summary,
        "group_by": group_by,
        "groupings": groupings,
    }

    should_publish = bool(scope == "team" or publish_team_notification) if publish_immediately is None else bool(publish_immediately)

    report = AgentReport(
        id=uuid4(),
        created_by_user_id=int(created_by_user_id),
        thread_id=thread_id,
        scope=scope,
        title=_build_report_title(scope, period_start, period_end),
        period_start=period_start,
        period_end=period_end,
        status="published" if should_publish else "ready",
        summary_json=_dump_json(summary),
        payload_json=_dump_json(payload),
    )
    db.add(report)
    db.flush()
    items = _maybe_add_sample_items(db, report.id, period_start, period_end)
    db.commit()
    db.refresh(report)

    if should_publish:
        create_notification(
            db,
            scope="team",
            notification_type="weekly_report_ready",
            report_id=report.id,
            payload={"report_id": str(report.id), "title": report.title, "summary": summary},
        )
    elif scope != "team":
        create_notification(
            db,
            scope="personal",
            user_id=int(created_by_user_id),
            notification_type="personal_report_ready",
            report_id=report.id,
            payload={"report_id": str(report.id), "title": report.title, "summary": summary},
        )

    return serialize_report(report, items)


def publish_report(db: Session, *, report_id: UUID, actor_user_id: int) -> JsonDict | None:
    row = db.get(AgentReport, report_id)
    if not row:
        return None

    if row.scope != "team":
        row.scope = "team"

    if row.status != "published":
        row.status = "published"
        db.add(row)
        db.commit()
        db.refresh(row)

        create_notification(
            db,
            scope="team",
            notification_type="weekly_report_ready",
            report_id=row.id,
            payload={
                "report_id": str(row.id),
                "title": row.title,
                "summary": _load_json(row.summary_json),
                "published_by_user_id": int(actor_user_id),
            },
        )

    items = (
        db.query(AgentReportItem)
        .filter(AgentReportItem.report_id == report_id)
        .order_by(AgentReportItem.created_at.asc())
        .all()
    )
    return serialize_report(row, items)


def list_reports(db: Session, *, user_id: int, include_team: bool = True, limit: int = 50) -> List[JsonDict]:
    query = db.query(AgentReport)
    if include_team:
        query = query.filter(or_(AgentReport.created_by_user_id == int(user_id), AgentReport.scope == "team"))
    else:
        query = query.filter(AgentReport.created_by_user_id == int(user_id))
    rows = query.order_by(AgentReport.created_at.desc()).limit(max(1, min(int(limit), 200))).all()
    return [serialize_report(row) for row in rows]


def get_report(db: Session, *, report_id: UUID, user_id: int) -> JsonDict | None:
    row = (
        db.query(AgentReport)
        .filter(AgentReport.id == report_id)
        .filter(or_(AgentReport.created_by_user_id == int(user_id), AgentReport.scope == "team"))
        .first()
    )
    if not row:
        return None
    items = db.query(AgentReportItem).filter(AgentReportItem.report_id == report_id).order_by(AgentReportItem.created_at.asc()).all()
    return serialize_report(row, items)


def claim_report_item(db: Session, *, item_id: UUID, user_id: int) -> JsonDict | None:
    row = db.get(AgentReportItem, item_id)
    if not row:
        return None
    if row.assignee_user_id and int(row.assignee_user_id) != int(user_id) and row.status == "claimed":
        raise ValueError("claim_conflict")
    row.assignee_user_id = int(user_id)
    row.status = "claimed"
    row.claimed_at = datetime.utcnow()
    row.released_at = None
    db.add(row)
    db.commit()
    db.refresh(row)
    create_notification(
        db,
        scope="team",
        notification_type="report_item_claimed",
        report_id=row.report_id,
        report_item_id=row.id,
        payload={"report_item_id": str(row.id), "assignee_user_id": int(user_id), "title": row.title},
    )
    return serialize_report_item(row)


def release_report_item(db: Session, *, item_id: UUID, user_id: int, force: bool = False) -> JsonDict | None:
    row = db.get(AgentReportItem, item_id)
    if not row:
        return None
    if row.assignee_user_id and int(row.assignee_user_id) != int(user_id) and not force:
        raise ValueError("release_conflict")
    row.status = "released"
    row.released_at = datetime.utcnow()
    row.assignee_user_id = None
    db.add(row)
    db.commit()
    db.refresh(row)
    create_notification(
        db,
        scope="team",
        notification_type="report_item_released",
        report_id=row.report_id,
        report_item_id=row.id,
        payload={"report_item_id": str(row.id), "title": row.title},
    )
    return serialize_report_item(row)


def reassign_report_item(db: Session, *, item_id: UUID, assignee_user_id: int) -> JsonDict | None:
    row = db.get(AgentReportItem, item_id)
    if not row:
        return None
    row.assignee_user_id = int(assignee_user_id)
    row.status = "claimed"
    row.claimed_at = datetime.utcnow()
    db.add(row)
    db.commit()
    db.refresh(row)
    create_notification(
        db,
        scope="team",
        notification_type="report_item_reassigned",
        report_id=row.report_id,
        report_item_id=row.id,
        payload={"report_item_id": str(row.id), "assignee_user_id": int(assignee_user_id), "title": row.title},
    )
    return serialize_report_item(row)


def build_previous_week_window(now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    current = now or datetime.utcnow()
    current_date = current.date()
    start_of_this_week = current_date - timedelta(days=current_date.weekday())
    start_of_prev_week = start_of_this_week - timedelta(days=7)
    end_of_prev_week = start_of_this_week - timedelta(seconds=1)
    start_dt = datetime.combine(start_of_prev_week, time.min)
    end_dt = datetime.combine(start_of_this_week - timedelta(days=1), time.max)
    return start_dt, end_dt
