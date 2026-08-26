from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from database.models import Transaction
from services.ai_agent.authorization import actor_id, current_agent_authorization


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _idempotency_key(action: str, payload: Dict[str, Any]) -> str:
    raw = json.dumps(
        {"action": action, "payload": payload},
        sort_keys=True,
        default=_json_default,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _scope_chat_ids(scope: Optional[dict]) -> Optional[List[int]]:
    if not isinstance(scope, dict):
        return None
    raw = scope.get("allowed_chat_ids")
    if not raw:
        return None
    out: List[int] = []
    for v in raw:
        try:
            out.append(int(v))
        except Exception:
            continue
    return out or None


def _serialize_transaction(tx: Transaction) -> Dict[str, Any]:
    return {
        "id": int(tx.id),
        "transaction_date": tx.transaction_date.isoformat() if tx.transaction_date else None,
        "operator_raw": tx.operator_raw,
        "application_mapped": tx.application_mapped,
        "amount": str(tx.amount) if tx.amount is not None else None,
        "balance_after": str(tx.balance_after) if tx.balance_after is not None else None,
        "card_last_4": tx.card_last_4,
        "transaction_type": tx.transaction_type,
        "currency": tx.currency,
        "is_p2p": bool(tx.is_p2p) if tx.is_p2p is not None else None,
        "receiver_name": tx.receiver_name,
        "receiver_card": tx.receiver_card,
    }


def _patch_diff(before: Dict[str, Any], patch: Dict[str, Any]) -> List[Dict[str, Any]]:
    diff: List[Dict[str, Any]] = []
    for field, new_value in patch.items():
        if new_value is None:
            continue
        old_value = before.get(field)
        if isinstance(new_value, (Decimal, datetime)):
            new_repr = _json_default(new_value)
        else:
            new_repr = new_value
        if old_value == new_repr:
            continue
        diff.append({"field": field, "before": old_value, "after": new_repr})
    return diff


async def create_transaction(
    db: Session,
    current_user: Dict[str, Any],
    scope: Optional[dict],
    args: Dict[str, Any],
) -> Dict[str, Any]:
    payload = {k: v for k, v in args.items() if not k.startswith("_")}
    auth = current_agent_authorization(db, actor_id(current_user))
    auth.require_admin("create_transaction")
    auth.require_dashboard()
    auth.authorize_date(db, payload.get("transaction_datetime"))

    summary_lines: List[str] = [
        f"Дата: {payload.get('transaction_datetime')}",
        f"Тип: {payload.get('transaction_type')}",
        f"Сумма: {payload.get('amount')} {payload.get('currency')}",
        f"Оператор: {payload.get('operator')}",
        f"Карта: ****{payload.get('card_last4')}",
    ]
    if payload.get("app"):
        summary_lines.append(f"Приложение: {payload['app']}")
    if payload.get("is_p2p"):
        summary_lines.append("P2P перевод")
        if payload.get("receiver_name"):
            summary_lines.append(f"Получатель: {payload['receiver_name']}")
        if payload.get("receiver_card"):
            summary_lines.append(f"Карта получателя: ****{payload['receiver_card']}")

    body = "\n".join(summary_lines)
    confirmation_payload = {
        "action": "create_transaction",
        "args": payload,
        "idempotency_key": _idempotency_key("create_transaction", payload),
    }

    return {
        "summary": "Подготовлено создание транзакции — нужно подтверждение.",
        "assistant_message": "Проверьте параметры новой транзакции и нажмите Подтвердить.",
        "requires_confirmation": True,
        "confirmation_payload": confirmation_payload,
        "cards": [
            {
                "type": "preview_create_tx",
                "title": "Создание транзакции",
                "body": body,
                "payload": {
                    "action": "create_transaction",
                    "fields": payload,
                },
            }
        ],
    }


async def update_transaction(
    db: Session,
    current_user: Dict[str, Any],
    scope: Optional[dict],
    args: Dict[str, Any],
) -> Dict[str, Any]:
    transaction_id = int(args.get("transaction_id") or 0)
    patch = args.get("patch") or {}
    if not transaction_id or not isinstance(patch, dict) or not patch:
        return {
            "summary": "Нет данных для обновления.",
            "assistant_message": "Не передан transaction_id или patch.",
            "cards": [
                {
                    "type": "warning",
                    "title": "Update transaction",
                    "body": "Не указан transaction_id или patch пуст.",
                }
            ],
        }

    tx = db.get(Transaction, transaction_id)
    if tx is None:
        return {
            "summary": f"Транзакция #{transaction_id} не найдена.",
            "assistant_message": f"Транзакция #{transaction_id} не найдена.",
            "cards": [
                {
                    "type": "warning",
                    "title": "Update transaction",
                    "body": f"Транзакция #{transaction_id} не найдена.",
                }
            ],
        }

    auth = current_agent_authorization(db, actor_id(current_user))
    auth.authorize_transaction(db, tx, proposed_date=patch.get("transaction_date"))

    before = _serialize_transaction(tx)
    diff = _patch_diff(before, patch)

    if not diff:
        return {
            "summary": "Все указанные поля уже соответствуют значениям в БД.",
            "assistant_message": "Изменений нет — все поля уже актуальны.",
            "cards": [
                {
                    "type": "warning",
                    "title": "Update transaction",
                    "body": "Изменений нет — все поля уже актуальны.",
                }
            ],
        }

    confirmation_payload = {
        "action": "update_transaction",
        "args": {"transaction_id": transaction_id, "patch": patch},
        "idempotency_key": _idempotency_key("update_transaction", {"id": transaction_id, "patch": patch}),
    }

    body_lines = [f"Транзакция #{transaction_id}"] + [
        f"• {item['field']}: {item['before']} → {item['after']}" for item in diff
    ]
    body = "\n".join(body_lines)

    return {
        "summary": f"Подготовлено редактирование транзакции #{transaction_id}.",
        "assistant_message": "Проверьте изменения и нажмите Подтвердить.",
        "requires_confirmation": True,
        "confirmation_payload": confirmation_payload,
        "cards": [
            {
                "type": "preview_update_tx",
                "title": f"Редактирование транзакции #{transaction_id}",
                "body": body,
                "payload": {
                    "action": "update_transaction",
                    "transaction_id": transaction_id,
                    "before": before,
                    "diff": diff,
                },
            }
        ],
    }


async def bulk_update_transactions(
    db: Session,
    current_user: Dict[str, Any],
    scope: Optional[dict],
    args: Dict[str, Any],
) -> Dict[str, Any]:
    raw_ids = args.get("transaction_ids") or []
    transaction_ids: List[int] = []
    for v in raw_ids:
        try:
            transaction_ids.append(int(v))
        except Exception:
            continue

    patch = args.get("patch") or {}
    transaction_ids = list(dict.fromkeys(transaction_ids))
    if not transaction_ids or not isinstance(patch, dict) or not patch:
        return {
            "summary": "Нет данных для массового обновления.",
            "assistant_message": "Список transaction_ids пуст или patch не задан.",
            "cards": [
                {
                    "type": "warning",
                    "title": "Bulk update",
                    "body": "Список transaction_ids пуст или patch не задан.",
                }
            ],
        }

    if len(transaction_ids) > 200:
        raise ValueError("bulk_update_limit_exceeded:200")

    rows = db.query(Transaction).filter(Transaction.id.in_(transaction_ids)).all()
    found_ids = {int(row.id) for row in rows}
    missing_ids = [tid for tid in transaction_ids if tid not in found_ids]
    if missing_ids:
        raise ValueError("bulk_update_missing_transactions:" + ",".join(str(item) for item in missing_ids[:20]))

    auth = current_agent_authorization(db, actor_id(current_user))
    for row in rows:
        auth.authorize_transaction(db, row, proposed_date=patch.get("transaction_date"))

    sample_diff: List[Dict[str, Any]] = []
    for row in rows[:5]:
        before = _serialize_transaction(row)
        diff = _patch_diff(before, patch)
        sample_diff.append({"id": int(row.id), "diff": diff})

    confirmation_payload = {
        "action": "bulk_update_transactions",
        "args": {"transaction_ids": transaction_ids, "patch": patch},
        "idempotency_key": _idempotency_key(
            "bulk_update_transactions",
            {"ids": sorted(int(row.id) for row in rows), "patch": patch},
        ),
    }

    body_lines = [
        f"Транзакций в патче: {len(rows)}",
    ]
    if missing_ids:
        body_lines.append("Не найдены: " + ", ".join(str(x) for x in missing_ids[:10]))
    body_lines.append("Изменения (sample):")
    for item in sample_diff:
        if not item["diff"]:
            continue
        body_lines.append(
            f"• #{item['id']}: " + ", ".join(
                f"{d['field']} {d['before']}→{d['after']}" for d in item["diff"]
            )
        )

    body = "\n".join(body_lines)

    return {
        "summary": f"Подготовлено массовое редактирование {len(rows)} транзакций.",
        "assistant_message": "Проверьте изменения и нажмите Подтвердить.",
        "requires_confirmation": True,
        "confirmation_payload": confirmation_payload,
        "cards": [
            {
                "type": "preview_bulk_update_tx",
                "title": "Массовое редактирование",
                "body": body,
                "payload": {
                    "action": "bulk_update_transactions",
                    "transaction_ids": [int(row.id) for row in rows],
                    "missing_ids": missing_ids,
                    "patch": patch,
                    "sample": sample_diff,
                },
            }
        ],
    }
