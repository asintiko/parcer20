from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import (
    AgentRun,
    AgentRunEvent,
    AgentThread,
    AgentReport,
    AgentReportItem,
    AutomationSuggestion,
    DuplicateMergeLog,
    DuplicateSuggestion,
    ReceiptProcessingIncident,
    ReceiptProcessingTask,
    ReconciliationSuggestion,
    TgChatMessage,
    Transaction,
    VerificationSuggestion,
)
from services.ai_agent.report_service import publish_report
from services.ai_agent.authorization import (
    AgentAuthorization,
    actor_id,
    current_agent_authorization,
)
from services.receipt_processor import _merge_duplicate_transaction
from workers.celery_worker import queue_receipt_task

logger = logging.getLogger(__name__)


JsonDict = Dict[str, Any]


def _load_json(value: Optional[str]) -> JsonDict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _extract_formatted_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            return text
    return ""


def _confirmation_payload(run: AgentRun) -> JsonDict:
    result = _load_json(run.result_json)
    payload = result.get("confirmation_payload")
    return payload if isinstance(payload, dict) else {}


def _already_confirmed_payload(run: AgentRun) -> Optional[JsonDict]:
    result = _load_json(run.result_json)
    payload = result.get("confirmation_result")
    return payload if isinstance(payload, dict) else None


def _serialize_report_card(report: JsonDict) -> JsonDict:
    items = report.get("items") or []
    compact_report = {
        "id": report.get("id"),
        "title": report.get("title") or "Командный отчет",
        "scope": report.get("scope"),
        "status": report.get("status"),
        "summary": report.get("summary") or {},
        "items_count": len(items),
        "items_preview": items[:10],
    }
    return {
        "type": "report",
        "title": compact_report["title"],
        "report": compact_report,
    }


def _serialize_navigation_for_transactions(
    *,
    row_id: Optional[int] = None,
    row_ids: Optional[Iterable[int]] = None,
    column_id: Optional[str] = None,
    suggested_filters: Optional[JsonDict] = None,
    highlight_seconds: int = 4,
) -> JsonDict:
    cleaned_row_ids = [int(item) for item in (row_ids or []) if item is not None]
    return {
        "route": "/transactions",
        "row_id": int(row_id) if row_id is not None else (cleaned_row_ids[0] if cleaned_row_ids else None),
        "row_ids": cleaned_row_ids or None,
        "column_id": column_id,
        "focus_mode": "row" if row_id is not None or cleaned_row_ids else "filter",
        "suggested_filters": suggested_filters or {},
        "sort_hint": {"sort_by": "transaction_date", "sort_dir": "desc"},
        "page_hint": 1,
        "highlight_seconds": int(highlight_seconds),
        "exists": True,
    }


def _repoint_transaction_links(db: Session, *, old_id: int, new_id: int) -> None:
    db.query(ReceiptProcessingTask).filter(ReceiptProcessingTask.transaction_id == int(old_id)).update(
        {"transaction_id": int(new_id)},
        synchronize_session=False,
    )
    db.query(TgChatMessage).filter(TgChatMessage.receipt_transaction_id == int(old_id)).update(
        {"receipt_transaction_id": int(new_id), "duplicate_status": "merged"},
        synchronize_session=False,
    )
    db.query(VerificationSuggestion).filter(VerificationSuggestion.transaction_id == int(old_id)).update(
        {"transaction_id": int(new_id)},
        synchronize_session=False,
    )
    db.query(AutomationSuggestion).filter(AutomationSuggestion.transaction_id == int(old_id)).update(
        {"transaction_id": int(new_id)},
        synchronize_session=False,
    )
    db.query(ReconciliationSuggestion).filter(ReconciliationSuggestion.transaction_id == int(old_id)).update(
        {"transaction_id": int(new_id)},
        synchronize_session=False,
    )
    db.query(ReceiptProcessingIncident).filter(ReceiptProcessingIncident.transaction_id == int(old_id)).update(
        {"transaction_id": int(new_id)},
        synchronize_session=False,
    )


def _reject_related_duplicate_suggestions(db: Session, *, primary_id: int, duplicate_id: int, approved_id: UUID) -> None:
    related = (
        db.query(DuplicateSuggestion)
        .filter(
            DuplicateSuggestion.id != approved_id,
            (
                (DuplicateSuggestion.primary_transaction_id == int(primary_id))
                | (DuplicateSuggestion.primary_transaction_id == int(duplicate_id))
                | (DuplicateSuggestion.duplicate_transaction_id == int(primary_id))
                | (DuplicateSuggestion.duplicate_transaction_id == int(duplicate_id))
            ),
        )
        .all()
    )
    for row in related:
        row.status = "rejected"
        db.add(row)


def _merge_duplicate_pair(
    db: Session,
    *,
    suggestion: DuplicateSuggestion,
    auth: AgentAuthorization,
) -> JsonDict:
    primary = (
        db.query(Transaction)
        .filter(Transaction.id == suggestion.primary_transaction_id)
        .with_for_update()
        .first()
    )
    duplicate = (
        db.query(Transaction)
        .filter(Transaction.id == suggestion.duplicate_transaction_id)
        .with_for_update()
        .first()
    )

    if not primary:
        raise ValueError("primary_transaction_not_found")
    auth.authorize_transaction(db, primary)

    if duplicate is None:
        suggestion.status = "approved"
        db.add(suggestion)
        return {
            "applied": False,
            "idempotent": True,
            "primary_transaction_id": int(primary.id),
            "duplicate_transaction_id": int(suggestion.duplicate_transaction_id),
        }

    auth.authorize_transaction(db, duplicate)
    _merge_duplicate_transaction(
        primary,
        candidate_transaction_date=duplicate.transaction_date,
        candidate_operator_raw=duplicate.operator_raw or "",
        candidate_application_mapped=duplicate.application_mapped,
        candidate_balance_after=duplicate.balance_after,
        candidate_receiver_name=duplicate.receiver_name,
        candidate_receiver_card=duplicate.receiver_card,
        candidate_raw_message=duplicate.raw_message or "",
        candidate_is_p2p=duplicate.is_p2p,
        candidate_parsing_method=duplicate.parsing_method,
        candidate_parsing_confidence=duplicate.parsing_confidence,
        candidate_is_gpt=bool(duplicate.is_gpt_parsed),
        candidate_source_type=duplicate.source_type,
    )

    _repoint_transaction_links(db, old_id=int(duplicate.id), new_id=int(primary.id))
    _reject_related_duplicate_suggestions(
        db,
        primary_id=int(primary.id),
        duplicate_id=int(duplicate.id),
        approved_id=suggestion.id,
    )
    suggestion.status = "approved"
    db.add(suggestion)
    db.add(
        DuplicateMergeLog(
            fingerprint=duplicate.fingerprint or primary.fingerprint,
            existing_transaction_id=int(primary.id),
            source_chat_id=int(duplicate.source_chat_id) if duplicate.source_chat_id is not None else None,
            source_message_id=int(duplicate.source_message_id) if duplicate.source_message_id is not None else None,
            merged=True,
            candidate_method=duplicate.parsing_method,
            candidate_confidence=float(duplicate.parsing_confidence or 0.0) if duplicate.parsing_confidence is not None else None,
            existing_method=primary.parsing_method,
            existing_confidence=float(primary.parsing_confidence or 0.0) if primary.parsing_confidence is not None else None,
            details_json=json.dumps(
                {
                    "source": "agent_confirm",
                    "suggestion_id": str(suggestion.id),
                    "duplicate_transaction_id": int(duplicate.id),
                },
                ensure_ascii=False,
            ),
        )
    )
    db.delete(duplicate)

    return {
        "applied": True,
        "idempotent": False,
        "primary_transaction_id": int(primary.id),
        "duplicate_transaction_id": int(suggestion.duplicate_transaction_id),
        "navigation_target": _serialize_navigation_for_transactions(
            row_id=int(primary.id),
            row_ids=[int(primary.id)],
            column_id="amount",
            highlight_seconds=5,
        ),
    }


def _confirm_duplicate_merge(db: Session, *, args: JsonDict, auth: AgentAuthorization) -> JsonDict:
    suggestion_ids = [str(item) for item in (args.get("suggestion_ids") or []) if str(item).strip()]
    if not suggestion_ids:
        raise ValueError("no_duplicate_suggestions")
    suggestion_ids = list(dict.fromkeys(suggestion_ids))
    if len(suggestion_ids) > 50:
        raise ValueError("duplicate_merge_limit_exceeded:50")

    applied: List[JsonDict] = []
    parsed_ids = [UUID(str(raw_id)) for raw_id in suggestion_ids]
    suggestions = (
        db.query(DuplicateSuggestion)
        .filter(DuplicateSuggestion.id.in_(parsed_ids))
        .with_for_update()
        .all()
    )
    by_id = {row.id: row for row in suggestions}
    missing = [str(item) for item in parsed_ids if item not in by_id]
    if missing:
        raise ValueError("duplicate_suggestions_not_found:" + ",".join(missing[:10]))
    for suggestion_id in parsed_ids:
        suggestion = by_id[suggestion_id]
        if suggestion.status not in {"pending", "approved"}:
            raise ValueError(f"duplicate_suggestion_not_pending:{suggestion_id}")
        applied.append(_merge_duplicate_pair(db, suggestion=suggestion, auth=auth))
    db.commit()

    merged_rows = [item for item in applied if item.get("applied")]
    primary_ids = [int(item["primary_transaction_id"]) for item in applied if item.get("primary_transaction_id") is not None]
    message = (
        f"Подтвердил объединение дублей. Применено: {len(merged_rows)}. "
        f"Без повторного действия: {len(applied) - len(merged_rows)}."
    )
    return {
        "message": message,
        "cards": [
            {
                "type": "result",
                "title": "Объединение дублей выполнено",
                "body": message,
                "payload": {
                    "applied": len(merged_rows),
                    "idempotent": len(applied) - len(merged_rows),
                    "skipped": 0,
                },
                "details": applied,
            }
        ],
        "navigation_targets": [
            _serialize_navigation_for_transactions(
                row_id=primary_ids[0] if primary_ids else None,
                row_ids=primary_ids,
                column_id="amount",
                highlight_seconds=5,
            )
        ] if primary_ids else [],
        "confirmation_result": {
            "action": "merge_duplicates",
            "applied": len(merged_rows),
            "idempotent": len(applied) - len(merged_rows),
            "skipped": 0,
            "items": applied,
        },
    }


def _message_payload_from_cache_row(row: TgChatMessage) -> JsonDict:
    raw = _load_json(row.raw_json)
    content = raw.get("content") if isinstance(raw.get("content"), dict) else {}
    content_type = str(content.get("@type") or raw.get("content_type") or row.content_type or "")

    payload: JsonDict = {
        "raw_text": row.text or "",
        "source_type": "AUTO",
        "source_chat_id": int(row.chat_id),
        "source_message_id": int(row.message_id),
    }

    if content_type == "messageDocument":
        document = content.get("document") if isinstance(content.get("document"), dict) else {}
        document_file = document.get("document") if isinstance(document.get("document"), dict) else {}
        payload["document"] = {
            "file_id": document_file.get("id") or document.get("file_id"),
            "mime_type": document.get("mime_type") or raw.get("mime_type"),
            "file_name": document.get("file_name") or raw.get("file_name"),
            "caption": _extract_formatted_text(content.get("caption")) or row.text or "",
        }
    elif content_type == "messagePhoto":
        photo = content.get("photo") if isinstance(content.get("photo"), dict) else {}
        sizes = photo.get("sizes") if isinstance(photo.get("sizes"), list) else []
        file_id = None
        for item in reversed(sizes):
            if not isinstance(item, dict):
                continue
            photo_file = item.get("photo") if isinstance(item.get("photo"), dict) else {}
            file_id = photo_file.get("id") or item.get("file_id") or file_id
            if file_id:
                break
        payload["image"] = {
            "file_id": file_id,
            "mime_type": "image/jpeg",
            "caption": _extract_formatted_text(content.get("caption")) or row.text or "",
        }

    return payload


def _confirm_receipt_reparse(db: Session, *, args: JsonDict, auth: AgentAuthorization) -> JsonDict:
    chat_id = int(args.get("chat_id"))
    message_id = int(args.get("message_id"))
    row = (
        db.query(TgChatMessage)
        .filter(TgChatMessage.chat_id == chat_id, TgChatMessage.message_id == message_id)
        .first()
    )
    if not row:
        raise ValueError("message_not_found")
    auth.require_dashboard()
    auth.authorize_chat(chat_id)
    if row.message_date is not None:
        auth.authorize_date(db, row.message_date)

    task_data = _message_payload_from_cache_row(row)
    task_data.update(
        {
            "requested_by_user_id": auth.user_id,
            "requested_action": "agent_receipt_reparse",
            "requested_permissions_version": auth.permissions_version,
            "original_source_chat_id": chat_id,
            "original_source_message_id": message_id,
        }
    )
    task_id = queue_receipt_task(task_data, force=True)
    message = f"Повторный разбор поставлен в очередь для сообщения {chat_id}/{message_id}."
    return {
        "message": message,
        "cards": [
            {
                "type": "result",
                "title": "Повторный разбор запущен",
                "body": message,
                "payload": {"chat_id": chat_id, "message_id": message_id, "task_id": task_id},
                "details": task_data,
            }
        ],
        "navigation_targets": [
            _serialize_navigation_for_transactions(
                column_id="raw_message",
                suggested_filters={"source_chat_ids": [chat_id], "search": str(message_id)},
                highlight_seconds=4,
            )
        ],
        "confirmation_result": {
            "action": "reparse_receipt",
            "task_id": task_id,
            "chat_id": chat_id,
            "message_id": message_id,
        },
    }


def _confirm_report_publish(db: Session, *, args: JsonDict, auth: AgentAuthorization) -> JsonDict:
    auth.require_admin("publish_team_report")
    report_id = UUID(str(args.get("report_id")))
    report = publish_report(db, report_id=report_id, actor_user_id=auth.user_id)
    if not report:
        raise ValueError("report_not_found")

    message = "Командный отчет опубликован и добавлен в уведомления."
    return {
        "message": message,
        "cards": [_serialize_report_card(report)],
        "navigation_targets": [],
        "report_id": report.get("id"),
        "confirmation_result": {
            "action": "publish_report",
            "report_id": report.get("id"),
            "published": True,
        },
    }


def _normalize_transaction_type(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if raw in {"DEBIT", "CREDIT", "CONVERSION", "REVERSAL"}:
        return raw
    return "DEBIT"


def _store_amount_for_type(amount: Decimal, txn_type: str) -> Decimal:
    return -abs(amount) if txn_type == "DEBIT" else abs(amount)


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except Exception:
        return None


def _confirm_create_transaction(db: Session, *, args: JsonDict, auth: AgentAuthorization) -> JsonDict:
    txn_type = _normalize_transaction_type(args.get("transaction_type"))
    try:
        amount = Decimal(str(args.get("amount")))
    except Exception as exc:
        raise ValueError("invalid_amount") from exc
    store_amount = _store_amount_for_type(amount, txn_type)

    dt = _parse_iso_datetime(args.get("transaction_datetime"))
    if dt is None:
        raise ValueError("invalid_transaction_datetime")
    auth.require_admin("create_transaction")
    auth.require_dashboard()
    auth.authorize_date(db, dt)

    operator = str(args.get("operator") or "").strip()
    currency = str(args.get("currency") or "UZS").strip().upper()
    card_last4 = str(args.get("card_last4") or "").strip()
    raw_text = args.get("raw_text") or (
        f"{txn_type}\n{operator}\nСумма: {amount} {currency}\nКарта: *{card_last4}"
    )

    txn = Transaction(
        transaction_date=dt,
        operator_raw=operator,
        application_mapped=args.get("app"),
        amount=store_amount,
        balance_after=Decimal(str(args["balance"])) if args.get("balance") not in (None, "") else None,
        card_last_4=card_last4,
        is_p2p=bool(args.get("is_p2p") or False),
        receiver_name=args.get("receiver_name"),
        receiver_card=args.get("receiver_card"),
        transaction_type=txn_type,
        currency=currency,
        source_type="MANUAL",
        source_chat_id=0,
        raw_message=raw_text,
        parsing_method="REGEX_SMS",
        parsing_confidence=None,
        is_gpt_parsed=False,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)

    message = f"Создана транзакция #{int(txn.id)} на {amount} {currency}."
    return {
        "message": message,
        "cards": [
            {
                "type": "result",
                "title": "Транзакция создана",
                "body": message,
                "payload": {
                    "transaction_id": int(txn.id),
                    "amount": str(amount),
                    "currency": currency,
                    "transaction_type": txn_type,
                },
            }
        ],
        "navigation_targets": [
            _serialize_navigation_for_transactions(
                row_id=int(txn.id),
                row_ids=[int(txn.id)],
                column_id="amount",
                highlight_seconds=5,
            )
        ],
        "confirmation_result": {
            "action": "create_transaction",
            "transaction_id": int(txn.id),
        },
    }


_UPDATE_FIELD_WHITELIST = {
    "transaction_date",
    "operator_raw",
    "application_mapped",
    "amount",
    "balance_after",
    "card_last_4",
    "receiver_name",
    "receiver_card",
    "transaction_type",
    "currency",
    "is_p2p",
}


def _apply_patch_to_transaction(tx: Transaction, patch: JsonDict) -> List[str]:
    applied: List[str] = []
    for field, raw_value in patch.items():
        if field not in _UPDATE_FIELD_WHITELIST:
            continue
        if raw_value is None:
            continue
        if field == "transaction_date":
            parsed = _parse_iso_datetime(raw_value)
            if parsed is None:
                continue
            tx.transaction_date = parsed
        elif field == "transaction_type":
            tx.transaction_type = _normalize_transaction_type(raw_value)
            if tx.amount is not None:
                tx.amount = _store_amount_for_type(abs(Decimal(str(tx.amount))), tx.transaction_type)
        elif field == "amount":
            try:
                amt = Decimal(str(raw_value))
            except Exception:
                continue
            tx.amount = _store_amount_for_type(amt, tx.transaction_type or "DEBIT")
        elif field == "balance_after":
            try:
                tx.balance_after = Decimal(str(raw_value))
            except Exception:
                continue
        elif field == "is_p2p":
            tx.is_p2p = bool(raw_value)
        else:
            setattr(tx, field, raw_value)
        applied.append(field)
    if applied:
        tx.updated_at = func.now()
    return applied


def _confirm_update_transaction(db: Session, *, args: JsonDict, auth: AgentAuthorization) -> JsonDict:
    transaction_id = int(args.get("transaction_id") or 0)
    patch = args.get("patch") if isinstance(args.get("patch"), dict) else {}
    if not transaction_id or not patch:
        raise ValueError("missing_transaction_or_patch")

    tx = db.query(Transaction).filter(Transaction.id == transaction_id).with_for_update().first()
    if tx is None:
        raise ValueError("transaction_not_found")
    auth.authorize_transaction(db, tx, proposed_date=patch.get("transaction_date"))

    applied = _apply_patch_to_transaction(tx, patch)
    if not applied:
        raise ValueError("empty_patch")

    db.add(tx)
    db.commit()
    db.refresh(tx)

    message = f"Обновлена транзакция #{transaction_id} ({', '.join(applied)})."
    return {
        "message": message,
        "cards": [
            {
                "type": "result",
                "title": "Транзакция обновлена",
                "body": message,
                "payload": {
                    "transaction_id": int(tx.id),
                    "updated_fields": applied,
                },
            }
        ],
        "navigation_targets": [
            _serialize_navigation_for_transactions(
                row_id=int(tx.id),
                row_ids=[int(tx.id)],
                column_id="amount",
                highlight_seconds=5,
            )
        ],
        "confirmation_result": {
            "action": "update_transaction",
            "transaction_id": int(tx.id),
            "updated_fields": applied,
        },
    }


def _confirm_bulk_update_transactions(db: Session, *, args: JsonDict, auth: AgentAuthorization) -> JsonDict:
    raw_ids = args.get("transaction_ids") or []
    transaction_ids: List[int] = []
    for v in raw_ids:
        try:
            transaction_ids.append(int(v))
        except Exception:
            continue
    transaction_ids = list(dict.fromkeys(transaction_ids))
    patch = args.get("patch") if isinstance(args.get("patch"), dict) else {}
    if not transaction_ids or not patch:
        raise ValueError("missing_transaction_ids_or_patch")

    if len(transaction_ids) > 200:
        raise ValueError("bulk_update_limit_exceeded:200")
    rows = (
        db.query(Transaction)
        .filter(Transaction.id.in_(transaction_ids))
        .with_for_update()
        .all()
    )
    found_set = {int(row.id) for row in rows}
    missing = [tid for tid in transaction_ids if tid not in found_set]
    if missing:
        raise ValueError("bulk_update_missing_transactions:" + ",".join(str(item) for item in missing[:20]))
    for row in rows:
        auth.authorize_transaction(db, row, proposed_date=patch.get("transaction_date"))
    updated_ids: List[int] = []
    skipped: List[int] = []
    for row in rows:
        applied = _apply_patch_to_transaction(row, patch)
        if applied:
            db.add(row)
            updated_ids.append(int(row.id))
        else:
            skipped.append(int(row.id))

    db.commit()
    message = (
        f"Массовое обновление: применено {len(updated_ids)}, без изменений {len(skipped)}, "
        f"не найдено {len(missing)}."
    )
    return {
        "message": message,
        "cards": [
            {
                "type": "result",
                "title": "Массовое обновление",
                "body": message,
                "payload": {
                    "updated": updated_ids,
                    "skipped": skipped,
                    "missing": missing,
                },
            }
        ],
        "navigation_targets": [
            _serialize_navigation_for_transactions(
                row_ids=updated_ids,
                column_id="amount",
                highlight_seconds=5,
            )
        ] if updated_ids else [],
        "confirmation_result": {
            "action": "bulk_update_transactions",
            "updated": updated_ids,
            "skipped": skipped,
            "missing": missing,
        },
    }


def execute_confirmation_for_run(db: Session, *, run: AgentRun, current_user: JsonDict) -> JsonDict:
    existing = _already_confirmed_payload(run)
    if existing:
        return {
            "message": str(existing.get("message") or "Действие уже подтверждено."),
            "cards": existing.get("cards") or [],
            "navigation_targets": existing.get("navigation_targets") or [],
            "confirmation_result": existing,
        }

    payload = _confirmation_payload(run)
    action = str(payload.get("action") or "").strip()
    args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
    auth = current_agent_authorization(db, actor_id(current_user))
    if int(run.created_by_user_id) != auth.user_id:
        raise ValueError("confirmation_actor_mismatch")

    if action == "merge_duplicates":
        return _confirm_duplicate_merge(db, args=args, auth=auth)
    if action == "reparse_receipt":
        return _confirm_receipt_reparse(db, args=args, auth=auth)
    if action == "publish_report":
        return _confirm_report_publish(db, args=args, auth=auth)
    if action == "create_transaction":
        return _confirm_create_transaction(db, args=args, auth=auth)
    if action == "update_transaction":
        return _confirm_update_transaction(db, args=args, auth=auth)
    if action == "bulk_update_transactions":
        return _confirm_bulk_update_transactions(db, args=args, auth=auth)
    if action == "weekly_autofix":
        return _confirm_weekly_autofix(db, args=args, auth=auth)
    raise ValueError("confirmation_action_not_supported")


def _confirm_weekly_autofix(
    db: Session, *, args: JsonDict, auth: AgentAuthorization
) -> JsonDict:
    """Apply a batch of fix actions produced by `weekly_report_autofix`.

    Each action is one of:
        {kind: "merge_duplicates", transaction_ids: [...], keep_id: int}
        {kind: "reparse_transaction", transaction_id: int}
    """
    auth.require_admin("weekly_autofix")
    actions = args.get("actions") if isinstance(args.get("actions"), list) else []
    if not actions:
        raise ValueError("weekly_autofix_empty")
    if len(actions) > 50:
        raise ValueError("weekly_autofix_limit_exceeded:50")
    applied: List[Dict[str, Any]] = []
    prepared_merges: List[tuple[Transaction, List[Transaction]]] = []
    prepared_reparses: List[Transaction] = []
    referenced_ids: set[int] = set()

    # Validate and lock the entire immutable batch before changing any row.
    for entry in actions:
        if not isinstance(entry, dict):
            raise ValueError("weekly_autofix_invalid_action")
        kind = str(entry.get("kind") or "").strip()
        if kind == "merge_duplicates":
            ids = list(dict.fromkeys(int(item) for item in (entry.get("transaction_ids") or [])))
            if len(ids) < 2:
                raise ValueError("weekly_autofix_merge_requires_two_ids")
            keep_id = int(entry.get("keep_id") or min(ids))
            if keep_id not in ids:
                raise ValueError("weekly_autofix_keep_id_outside_group")
            referenced_ids.update(ids)
            rows = (
                db.query(Transaction)
                .filter(Transaction.id.in_(ids))
                .with_for_update()
                .all()
            )
            by_id = {int(row.id): row for row in rows}
            if set(ids) != set(by_id):
                raise ValueError("weekly_autofix_transaction_not_found")
            keep = by_id[keep_id]
            duplicates = [by_id[item] for item in ids if item != keep_id]
            for transaction in rows:
                auth.authorize_transaction(db, transaction)
            if any(not _same_duplicate_group(keep, duplicate) for duplicate in duplicates):
                raise ValueError("weekly_autofix_duplicate_evidence_changed")
            prepared_merges.append((keep, duplicates))
        elif kind == "reparse_transaction":
            tx_id = int(entry.get("transaction_id") or 0)
            if not tx_id:
                raise ValueError("weekly_autofix_reparse_missing_id")
            referenced_ids.add(tx_id)
            transaction = (
                db.query(Transaction)
                .filter(Transaction.id == tx_id)
                .with_for_update()
                .first()
            )
            if transaction is None:
                raise ValueError("weekly_autofix_transaction_not_found")
            auth.authorize_transaction(db, transaction)
            if not transaction.source_chat_id or not transaction.source_message_id:
                raise ValueError("weekly_autofix_transaction_has_no_source")
            prepared_reparses.append(transaction)
        else:
            raise ValueError(f"weekly_autofix_unknown_action:{kind or 'unknown'}")
    if len(referenced_ids) > 200:
        raise ValueError("weekly_autofix_transaction_limit_exceeded:200")

    for keep, duplicates in prepared_merges:
        for duplicate in duplicates:
            _merge_transaction_rows(db, keep=keep, duplicate=duplicate, source="weekly_autofix")
        applied.append(
            {
                "kind": "merge_duplicates",
                "ids": [int(keep.id), *(int(item.id) for item in duplicates)],
                "kept": int(keep.id),
            }
        )
    db.commit()

    # Reparses are durable outbox jobs. They are queued only after all current
    # policy checks and the atomic financial mutation batch have succeeded.
    for transaction in prepared_reparses:
        task_id = _enqueue_reparse_for_transaction(db, transaction=transaction, auth=auth)
        applied.append(
            {
                "kind": "reparse_transaction",
                "transaction_id": int(transaction.id),
                "task_id": task_id,
            }
        )
    return {
        "message": f"Применено: {len(applied)}, пропущено: 0.",
        "cards": [
            {
                "type": "audit",
                "title": "Авто-исправление выполнено",
                "body": {
                    "applied": len(applied),
                    "skipped": 0,
                    "preview_applied": applied[:5],
                    "preview_skipped": [],
                },
            }
        ],
        "navigation_targets": [],
        "confirmation_result": {"applied": applied, "skipped": []},
    }


def _same_duplicate_group(left: Transaction, right: Transaction) -> bool:
    return (
        left.amount == right.amount
        and left.transaction_date == right.transaction_date
        and (left.card_last_4 or "") == (right.card_last_4 or "")
        and (left.operator_raw or "") == (right.operator_raw or "")
    )


def _merge_transaction_rows(
    db: Session,
    *,
    keep: Transaction,
    duplicate: Transaction,
    source: str,
) -> None:
    _merge_duplicate_transaction(
        keep,
        candidate_transaction_date=duplicate.transaction_date,
        candidate_operator_raw=duplicate.operator_raw or "",
        candidate_application_mapped=duplicate.application_mapped,
        candidate_balance_after=duplicate.balance_after,
        candidate_receiver_name=duplicate.receiver_name,
        candidate_receiver_card=duplicate.receiver_card,
        candidate_raw_message=duplicate.raw_message or "",
        candidate_is_p2p=duplicate.is_p2p,
        candidate_parsing_method=duplicate.parsing_method,
        candidate_parsing_confidence=duplicate.parsing_confidence,
        candidate_is_gpt=bool(duplicate.is_gpt_parsed),
        candidate_source_type=duplicate.source_type,
    )
    _repoint_transaction_links(db, old_id=int(duplicate.id), new_id=int(keep.id))
    db.add(
        DuplicateMergeLog(
            fingerprint=duplicate.fingerprint or keep.fingerprint,
            existing_transaction_id=int(keep.id),
            source_chat_id=int(duplicate.source_chat_id) if duplicate.source_chat_id is not None else None,
            source_message_id=int(duplicate.source_message_id) if duplicate.source_message_id is not None else None,
            merged=True,
            candidate_method=duplicate.parsing_method,
            candidate_confidence=float(duplicate.parsing_confidence or 0.0) if duplicate.parsing_confidence is not None else None,
            existing_method=keep.parsing_method,
            existing_confidence=float(keep.parsing_confidence or 0.0) if keep.parsing_confidence is not None else None,
            details_json=json.dumps(
                {"source": source, "duplicate_transaction_id": int(duplicate.id)},
                ensure_ascii=False,
            ),
        )
    )
    db.delete(duplicate)


def _enqueue_reparse_for_transaction(
    db: Session,
    *,
    transaction: Transaction,
    auth: AgentAuthorization,
) -> str:
    current = current_agent_authorization(db, auth.user_id)
    current.require_admin("weekly_autofix")
    current.authorize_transaction(db, transaction)
    task_data = {
        "source_chat_id": int(transaction.source_chat_id),
        "source_message_id": int(transaction.source_message_id),
        "raw_text": transaction.raw_message or "",
        "source_type": "AUTO",
        "requested_by_user_id": current.user_id,
        "requested_action": "agent_receipt_reparse",
        "requested_permissions_version": current.permissions_version,
        "original_source_chat_id": int(transaction.source_chat_id),
        "original_source_message_id": int(transaction.source_message_id),
    }
    return queue_receipt_task(task_data, force=True)
