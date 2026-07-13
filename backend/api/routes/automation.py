"""
API Routes for AI-powered Transaction Automation (production-ready)
Stores tasks/suggestions in DB to survive restarts.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from uuid import uuid4, UUID
from datetime import datetime
import asyncio
import os
import json
import time
import threading
import logging

from config.ai_models import (
    AI_RETRY_COUNT,
    MAPPING_AI_MODEL,
    MAPPING_AI_TEMPERATURE,
    MAPPING_AI_MAX_TOKENS,
    VERIFY_AI_MODEL,
    VERIFY_AI_TEMPERATURE,
    VERIFY_AI_MAX_TOKENS,
)

from decimal import Decimal, InvalidOperation
from database.connection import get_db_session, SessionLocal
from database.models import (
    Transaction,
    OperatorReference,
    AutomationTask,
    AutomationSuggestion,
    VerificationSuggestion,
)
from api.dependencies import require_tab_access, require_transactions_scope
from services.access_control_service import get_scope_window, is_datetime_allowed, write_audit_log
from services.period_lock_service import period_lock_service
from services.ai_provider import get_text_ai_provider
from services.web_search import search_operator_text

router = APIRouter(prefix="/api/automation", tags=["automation"])
logger = logging.getLogger(__name__)

AUTOMATION_APPS_CACHE_TTL_SECONDS = int(os.getenv("AUTOMATION_APPS_CACHE_TTL_SECONDS", "300"))
AUTOMATION_AI_RETRY_COUNT = int(os.getenv("AUTOMATION_AI_RETRY_COUNT", str(AI_RETRY_COUNT)))
BATCH_APPLY_MAX_ITEMS = int(os.getenv("AUTOMATION_BATCH_MAX_ITEMS", "200"))
_applications_cache: dict = {"expires_at": 0.0, "items": []}
_applications_cache_lock = threading.Lock()
text_ai_provider = get_text_ai_provider()


class AnalyzeRequest(BaseModel):
    limit: Optional[int] = Field(default=100, ge=1, le=1000)
    only_unmapped: bool = True
    currency_filter: Optional[str] = None  # UZS, USD, or None for all


class AISuggestion(BaseModel):
    application: str
    confidence: float
    is_new: bool
    is_p2p: bool
    reasoning: str


class SuggestionResponse(BaseModel):
    id: UUID
    task_id: UUID
    transaction_id: int
    operator_raw: str
    current_application: Optional[str]
    suggested_application: str
    confidence: float
    reasoning: Optional[str] = None
    is_new_application: bool
    is_p2p: bool
    status: str
    created_at: datetime


class AnalyzeResponse(BaseModel):
    task_id: UUID
    status: str
    message: str


class AnalyzeStatusResponse(BaseModel):
    task_id: UUID
    status: str
    progress: dict
    results: Optional[dict] = None


def _apply_scope_filter(query, scope: Optional[dict]):
    if not scope:
        return query
    scope_from, scope_to, scope_years = get_scope_window(scope)
    if scope_from:
        query = query.filter(Transaction.transaction_date >= scope_from)
    if scope_to:
        query = query.filter(Transaction.transaction_date <= scope_to)
    if scope_years:
        query = query.filter(func.extract("year", Transaction.transaction_date).in_(scope_years))
    return query


def _apply_locked_periods_filter(query, db: Session):
    locks = period_lock_service.get_active_locks(db)
    if not locks:
        return query
    blocked = []
    for lock in locks:
        blocked.append(
            and_(
                func.date(Transaction.transaction_date) >= lock.date_from,
                func.date(Transaction.transaction_date) <= lock.date_to,
            )
        )
    if blocked:
        query = query.filter(~or_(*blocked))
    return query


def _assert_tx_edit_allowed(tx: Transaction, scope: Optional[dict], db: Session) -> None:
    denial_reason = _tx_edit_denial_reason(tx, scope, db)
    if denial_reason:
        raise HTTPException(status_code=403, detail=denial_reason)


def _tx_edit_denial_reason(tx: Transaction, scope: Optional[dict], db: Session) -> Optional[str]:
    tx_date = tx.transaction_date
    if not tx_date:
        return "Transaction is out of scope"
    if not is_datetime_allowed(scope, tx_date):
        return "Transaction is out of scope"
    tx_day = tx_date.date()
    if period_lock_service.is_date_locked(tx_day, db):
        return "Transaction date is locked"
    return None


def _audit_automation_action(
    db: Session,
    *,
    action: str,
    current_user: Optional[dict],
    details: Optional[dict] = None,
) -> None:
    try:
        write_audit_log(
            db,
            action=action,
            success=True,
            user_id=current_user.get("user_id") if current_user else None,
            details=details or {},
        )
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        logger.exception("Failed to write automation audit log: %s", action)


def _update_task_atomic(
    session: Session,
    task_id: UUID,
    *,
    expected_status: Optional[str] = None,
    **values: Any,
) -> bool:
    update_payload = dict(values)
    update_payload["version"] = AutomationTask.version + 1  # optimistic lock bump
    query = session.query(AutomationTask).filter(AutomationTask.id == task_id)
    if expected_status:
        query = query.filter(AutomationTask.status == expected_status)
    updated = query.update(update_payload, synchronize_session=False)
    session.commit()
    return bool(updated)


async def _run_background_task(task_id: UUID, task_name: str, coro) -> None:
    logger.debug("Starting background task '%s'", task_name)
    try:
        await coro
        logger.debug("Background task '%s' finished successfully", task_name)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background task '%s' crashed", task_name)
        try:
            with SessionLocal() as db:
                updated = _update_task_atomic(
                    db,
                    task_id,
                    expected_status="processing",
                    status="failed",
                    result_json=json.dumps({"error": str(exc)[:500]}),
                )
                if not updated:
                    logger.warning("Automation task CAS conflict while failing task %s", task_id)
        except Exception:
            pass


def _normalize_error_text(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        detail = getattr(exc, "detail", None)
        return str(detail) if detail is not None else "Request failed"
    return str(exc)


def _apply_verification_field(tx: Transaction, field: str, value: Optional[str]) -> None:
    if field == "amount":
        if value is None or str(value).strip() == "":
            raise ValueError("amount is empty")
        tx.amount = Decimal(str(value))
        return
    if field == "balance_after":
        tx.balance_after = Decimal(str(value)) if value else None
        return
    if field == "transaction_date":
        if value is None or str(value).strip() == "":
            raise ValueError("transaction_date is empty")
        tx.transaction_date = datetime.fromisoformat(str(value))
        return
    if field in ("currency", "operator_raw", "card_last_4", "transaction_type", "receiver_name", "receiver_card"):
        setattr(tx, field, value)
        return
    raise ValueError(f"unsupported field: {field}")


def get_existing_applications(db: Session) -> List[str]:
    now = time.time()
    with _applications_cache_lock:
        if _applications_cache["expires_at"] > now and _applications_cache["items"]:
            return list(_applications_cache["items"])
    apps = (
        db.query(OperatorReference.application_name)
        .distinct()
        .filter(OperatorReference.is_active == True)  # noqa: E712
        .all()
    )
    items = [a[0] for a in apps if a[0]]
    with _applications_cache_lock:
        _applications_cache["items"] = items
        _applications_cache["expires_at"] = now + max(5, AUTOMATION_APPS_CACHE_TTL_SECONDS)
    return items


async def search_web_for_operator(operator_raw: str) -> str:
    """Lightweight web search via DuckDuckGo HTML (delegates to services.web_search)."""
    return await search_operator_text(operator_raw)


async def analyze_with_ai(operator_raw: str, existing_apps: List[str], transaction_context: dict | None = None) -> AISuggestion:
    web_info = await search_web_for_operator(operator_raw)

    system_prompt = """Ты эксперт по финансовым транзакциям в Узбекистане.
Твоя задача - определить приложение и P2P статус оператора.
Существующие приложения:
{apps_list}
Верни JSON:
{{
  "application": "string",
  "confidence": 0.0-1.0,
  "is_new": true/false,
  "is_p2p": true/false,
  "reasoning": "кратко"
}}
"""
    apps_list = "\n".join(f"- {app}" for app in existing_apps) if existing_apps else "нет данных"

    context_lines = [
        f"Тип: {transaction_context.get('transaction_type')}" if transaction_context else "",
        f"Сумма: {transaction_context.get('amount')}" if transaction_context else "",
        f"Дата: {transaction_context.get('datetime')}" if transaction_context else "",
    ]
    user_prompt = f"""Оператор: "{operator_raw}"
{os.linesep.join(context_lines)}

Интернет:
{web_info}"""

    retry_count = max(0, int(AUTOMATION_AI_RETRY_COUNT))
    retry_delay = 0.8
    for attempt in range(retry_count + 1):
        try:
            result = await text_ai_provider.complete_json(
                model=MAPPING_AI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt.format(apps_list=apps_list)},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=MAPPING_AI_TEMPERATURE,
                max_tokens=MAPPING_AI_MAX_TOKENS,
            )
            return AISuggestion(**result)
        except Exception as e:  # noqa: BLE001
            if attempt >= retry_count:
                logger.warning("Text AI error: %s", e)
                return AISuggestion(
                    application="Unknown",
                    confidence=0.0,
                    is_new=True,
                    is_p2p=False,
                    reasoning=f"Error: {str(e)}",
                )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 5.0)
    return AISuggestion(
        application="Unknown",
        confidence=0.0,
        is_new=True,
        is_p2p=False,
        reasoning="No attempts made",
    )


async def process_transactions_batch(task_id: UUID, transaction_ids: List[int]) -> None:
    """Background processing of transactions; persists progress/results."""
    try:
        tx_limit = max(1, int(BATCH_APPLY_MAX_ITEMS))
        limited_ids = [int(tid) for tid in transaction_ids[:tx_limit]]
        with SessionLocal() as db:
            initialized = _update_task_atomic(
                db,
                task_id,
                expected_status="pending",
                status="processing",
                progress_json=json.dumps({"total": len(limited_ids), "processed": 0, "percent": 0}),
            )
            if not initialized:
                logger.warning("Automation task %s cannot start (already changed status)", task_id)
                return

            tx_rows = (
                db.query(Transaction)
                .filter(Transaction.id.in_(limited_ids))
                .order_by(Transaction.transaction_date.desc())
                .all()
            )
            existing_apps = set(get_existing_applications(db))
            txs: List[Dict[str, Any]] = [
                {
                    "id": tx.id,
                    "operator_raw": tx.operator_raw,
                    "transaction_type": tx.transaction_type,
                    "amount": tx.amount,
                    "transaction_date": tx.transaction_date,
                }
                for tx in tx_rows
            ]

        total = len(txs)
        processed = 0
        suggestion_count = 0
        high_conf = 0
        operator_cache: dict[str, AISuggestion] = {}
        progress_every = 50

        with SessionLocal() as write_db:
            for tx in txs:
                try:
                    context = {
                        "transaction_type": tx.get("transaction_type"),
                        "amount": str(tx.get("amount")) if tx.get("amount") is not None else None,
                        "datetime": tx.get("transaction_date").isoformat() if tx.get("transaction_date") else None,
                    }
                    operator_value = (tx.get("operator_raw") or "Unknown")
                    operator_key = operator_value.strip().lower()
                    ai_result = operator_cache.get(operator_key)
                    if ai_result is None:
                        ai_result = await analyze_with_ai(operator_value, list(existing_apps), context)
                        operator_cache[operator_key] = ai_result

                    write_db.add(
                        AutomationSuggestion(
                            id=uuid4(),
                            task_id=task_id,
                            transaction_id=int(tx["id"]),
                            suggested_application=ai_result.application,
                            confidence=ai_result.confidence,
                            is_p2p=ai_result.is_p2p,
                            status="pending",
                            reasoning=ai_result.reasoning,
                        )
                    )
                    suggestion_count += 1
                    if ai_result.confidence >= 0.8:
                        high_conf += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning("Error processing tx %s: %s", tx.get("id"), e)

                processed += 1
                if processed % progress_every == 0 or processed == total:
                    write_db.commit()
                    _update_task_atomic(
                        write_db,
                        task_id,
                        expected_status="processing",
                        progress_json=json.dumps(
                            {
                                "total": total,
                                "processed": processed,
                                "percent": round((processed / max(total, 1)) * 100, 1),
                            }
                        ),
                    )
                await asyncio.sleep(0.2)  # gentle pacing

            write_db.commit()
            _update_task_atomic(
                write_db,
                task_id,
                expected_status="processing",
                status="completed",
                result_json=json.dumps(
                    {
                        "suggestions_count": suggestion_count,
                        "high_confidence": high_conf,
                        "low_confidence": suggestion_count - high_conf,
                    }
                ),
            )
    except Exception as e:  # noqa: BLE001
        with SessionLocal() as db:
            _update_task_atomic(
                db,
                task_id,
                expected_status="processing",
                status="failed",
                result_json=json.dumps({"error": str(e)}),
            )


@router.post("/analyze-transactions", response_model=AnalyzeResponse)
async def analyze_transactions(
    request: AnalyzeRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("automation")),
    scope: Optional[dict] = Depends(require_transactions_scope),
):
    _ = current_user
    query = db.query(Transaction)
    query = _apply_scope_filter(query, scope)
    query = _apply_locked_periods_filter(query, db)
    if request.only_unmapped:
        query = query.filter((Transaction.application_mapped == None) | (Transaction.application_mapped == ""))  # noqa: E711
    if request.currency_filter:
        query = query.filter(Transaction.currency == request.currency_filter)
    safe_limit = min(max(1, int(request.limit or 100)), max(1, int(BATCH_APPLY_MAX_ITEMS)))
    txs = query.order_by(Transaction.transaction_date.desc()).limit(safe_limit).all()

    # Always create task record, even if no transactions found
    task_id = uuid4()

    if not txs:
        task = AutomationTask(
            id=task_id,
            status="completed",
            progress_json=json.dumps({"total": 0, "processed": 0, "percent": 100}),
            result_json=json.dumps({"suggestions_count": 0, "high_confidence": 0, "low_confidence": 0}),
        )
        db.add(task)
        db.commit()

        return AnalyzeResponse(
            task_id=task_id,
            status="empty",
            message="No transactions found for analysis",
        )

    task = AutomationTask(
        id=task_id,
        status="pending",
        progress_json=json.dumps({"total": len(txs), "processed": 0, "percent": 0}),
    )
    db.add(task)
    db.commit()

    asyncio.create_task(
        _run_background_task(
            task_id,
            f"automation-analyze-{task_id}",
            process_transactions_batch(task_id, [t.id for t in txs]),
        )
    )

    return AnalyzeResponse(task_id=task_id, status="started", message=f"Analysis started for {len(txs)} transactions")


@router.get("/analyze-status/{task_id}", response_model=AnalyzeStatusResponse)
async def get_analyze_status(
    task_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("automation")),
    scope: Optional[dict] = Depends(require_transactions_scope),
):
    _ = current_user, scope
    task = db.get(AutomationTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return AnalyzeStatusResponse(
        task_id=task.id,
        status=task.status,
        progress=json.loads(task.progress_json or "{}"),
        results=json.loads(task.result_json or "{}") if task.result_json else None,
    )


@router.get("/suggestions", response_model=List[SuggestionResponse])
async def get_suggestions(
    status: Optional[str] = "pending",
    confidence_min: Optional[float] = 0.0,
    task_id: Optional[UUID] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("automation")),
    scope: Optional[dict] = Depends(require_transactions_scope),
):
    _ = current_user
    existing_apps = {
        (name or "").strip().lower()
        for name, in db.query(OperatorReference.application_name)
        .filter(OperatorReference.is_active == True)  # noqa: E712
        .all()
        if name
    }
    q = (
        db.query(AutomationSuggestion, Transaction)
        .join(Transaction, Transaction.id == AutomationSuggestion.transaction_id)
    )
    q = _apply_scope_filter(q, scope)
    q = _apply_locked_periods_filter(q, db)
    if status:
        q = q.filter(AutomationSuggestion.status == status)
    if confidence_min:
        q = q.filter(AutomationSuggestion.confidence >= confidence_min)
    if task_id:
        q = q.filter(AutomationSuggestion.task_id == task_id)

    rows = q.order_by(AutomationSuggestion.created_at.desc()).offset(offset).limit(limit).all()

    suggestions: List[SuggestionResponse] = []
    for sug, tx in rows:
        suggestions.append(
            SuggestionResponse(
                id=sug.id,
                task_id=sug.task_id,
                transaction_id=sug.transaction_id,
                operator_raw=tx.operator_raw,
                current_application=tx.application_mapped,
                suggested_application=sug.suggested_application,
                confidence=sug.confidence,
                reasoning=sug.reasoning,
                is_new_application=(sug.suggested_application or "").strip().lower() not in existing_apps,
                is_p2p=sug.is_p2p,
                status=sug.status,
                created_at=sug.created_at,
            )
        )
    return suggestions


@router.post("/suggestions/{suggestion_id}/apply")
async def apply_suggestion(
    suggestion_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("automation")),
    scope: Optional[dict] = Depends(require_transactions_scope),
):
    _ = current_user
    sug = db.get(AutomationSuggestion, suggestion_id)
    if not sug:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    tx = db.query(Transaction).filter(Transaction.id == sug.transaction_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    _assert_tx_edit_allowed(tx, scope, db)

    tx.application_mapped = sug.suggested_application
    tx.is_p2p = sug.is_p2p
    sug.status = "approved"
    db.commit()
    db.refresh(tx)
    _audit_automation_action(
        db,
        action="automation_apply_suggestion",
        current_user=current_user,
        details={"suggestion_id": str(suggestion_id), "transaction_id": tx.id},
    )

    # Return updated transaction data for frontend
    return {
        "success": True,
        "transaction_id": tx.id,
        "transaction": {
            "id": tx.id,
            "operator_raw": tx.operator_raw,
            "application_mapped": tx.application_mapped,
            "is_p2p": tx.is_p2p,
            "amount": float(tx.amount) if tx.amount else None,
            "currency": tx.currency,
            "transaction_date": tx.transaction_date.isoformat() if tx.transaction_date else None,
        }
    }


@router.post("/suggestions/{suggestion_id}/reject")
async def reject_suggestion(
    suggestion_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("automation")),
    scope: Optional[dict] = Depends(require_transactions_scope),
):
    _ = current_user, scope
    sug = db.get(AutomationSuggestion, suggestion_id)
    if not sug:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    sug.status = "rejected"
    db.commit()
    _audit_automation_action(
        db,
        action="automation_reject_suggestion",
        current_user=current_user,
        details={"suggestion_id": str(suggestion_id), "transaction_id": sug.transaction_id},
    )
    return {"success": True}


@router.post("/suggestions/batch-apply")
async def batch_apply_suggestions(
    suggestion_ids: List[UUID],
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("automation")),
    scope: Optional[dict] = Depends(require_transactions_scope),
):
    _ = current_user
    if len(suggestion_ids) > max(1, int(BATCH_APPLY_MAX_ITEMS)):
        raise HTTPException(
            status_code=400,
            detail=f"Too many suggestions (max {max(1, int(BATCH_APPLY_MAX_ITEMS))})",
        )

    applied = 0
    errors = []
    updated_transactions = []

    for sug_id in suggestion_ids:
        try:
            with db.begin_nested():
                sug = db.get(AutomationSuggestion, sug_id)
                if not sug:
                    errors.append({"suggestion_id": str(sug_id), "error": "Suggestion not found"})
                    continue

                tx = db.query(Transaction).filter(Transaction.id == sug.transaction_id).first()
                if not tx:
                    errors.append({"suggestion_id": str(sug_id), "error": "Transaction not found"})
                    continue
                denial_reason = _tx_edit_denial_reason(tx, scope, db)
                if denial_reason:
                    errors.append({"suggestion_id": str(sug_id), "error": denial_reason})
                    continue

                tx.application_mapped = sug.suggested_application
                tx.is_p2p = sug.is_p2p
                sug.status = "approved"
                db.flush()

                updated_transactions.append({
                    "id": tx.id,
                    "operator_raw": tx.operator_raw,
                    "application_mapped": tx.application_mapped,
                    "is_p2p": tx.is_p2p,
                })
                applied += 1
        except Exception as e:  # noqa: BLE001
            errors.append({"suggestion_id": str(sug_id), "error": _normalize_error_text(e)})
    db.commit()
    _audit_automation_action(
        db,
        action="automation_batch_apply_suggestions",
        current_user=current_user,
        details={"requested": len(suggestion_ids), "applied": applied, "errors": len(errors)},
    )

    return {
        "success": True,
        "applied": applied,
        "errors": errors,
        "updated_transactions": updated_transactions
    }


# ─────────────────────────────────────────────────────────────
#  AI Data Verification: compare raw_message vs parsed fields
# ─────────────────────────────────────────────────────────────

VERIFIABLE_FIELDS = [
    "transaction_date", "amount", "currency", "operator_raw",
    "card_last_4", "balance_after", "transaction_type",
    "receiver_name", "receiver_card",
]

FIELD_LABELS_RU = {
    "transaction_date": "Дата/время",
    "amount": "Сумма",
    "currency": "Валюта",
    "operator_raw": "Оператор",
    "card_last_4": "Карта",
    "balance_after": "Баланс",
    "transaction_type": "Тип",
    "receiver_name": "Получатель",
    "receiver_card": "Карта получателя",
}


class VerifyRequest(BaseModel):
    limit: Optional[int] = Field(default=50, ge=1, le=500)
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class VerifyResponse(BaseModel):
    task_id: UUID
    status: str
    message: str


class VerifyStatusResponse(BaseModel):
    task_id: UUID
    status: str
    progress: dict
    results: Optional[dict] = None


class VerificationSuggestionResponse(BaseModel):
    id: UUID
    task_id: UUID
    transaction_id: int
    field_name: str
    field_label: str
    current_value: Optional[str]
    suggested_value: Optional[str]
    confidence: float
    reasoning: Optional[str]
    status: str
    created_at: datetime


class FieldCorrection(BaseModel):
    field_name: str
    current_value: Optional[str] = None
    suggested_value: str
    confidence: float
    reasoning: str


class VerificationResult(BaseModel):
    has_errors: bool
    corrections: List[FieldCorrection]


async def verify_transaction_with_ai(raw_message: str, parsed_fields: dict) -> VerificationResult:
    """Compare raw receipt text with parsed fields using GPT-4o-mini."""
    system_prompt = """Ты агент верификации финансовых чеков Узбекистана.
Сравни исходный текст чека с уже распарсенными полями ниже.
Найди любые несоответствия в полях: дата/время, сумма, валюта, оператор, карта,
баланс, тип транзакции, получатель, карта получателя.

ВАЖНО о типах транзакций:
- Покупка/Оплата/Списание/Pokupka = DEBIT
- Пополнение/Popolnenie = CREDIT
- Конверсия = CONVERSION
- Отмена/OTMENA = REVERSAL

ВАЖНО о дате:
- Формат в чеке может быть DD.MM.YY HH:MM — сравни с распарсенным ISO форматом
- 08.02.26 17:50 = 2026-02-08T17:50:00

Верни JSON:
{
  "has_errors": true/false,
  "corrections": [
    {
      "field_name": "amount",
      "current_value": "15000.00",
      "suggested_value": "150000.00",
      "confidence": 0.95,
      "reasoning": "В тексте указано 150 000.00, а распарсено как 15000"
    }
  ]
}
Включай ТОЛЬКО поля с реальными ошибками. Если всё правильно — corrections пустой.
Допустимые field_name: transaction_date, amount, currency, operator_raw, card_last_4, balance_after, transaction_type, receiver_name, receiver_card.
Для transaction_date suggested_value должен быть в ISO формате: YYYY-MM-DDTHH:MM:SS"""

    fields_text = "\n".join(f"  {k}: {v}" for k, v in parsed_fields.items() if v is not None)
    user_prompt = f"""Исходный текст чека:
---
{raw_message}
---

Распарсенные поля:
{fields_text}"""

    retry_count = max(0, int(AUTOMATION_AI_RETRY_COUNT))
    retry_delay = 0.8
    for attempt in range(retry_count + 1):
        try:
            result = await text_ai_provider.complete_json(
                model=VERIFY_AI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=VERIFY_AI_TEMPERATURE,
                max_tokens=VERIFY_AI_MAX_TOKENS,
            )
            return VerificationResult(**result)
        except Exception as e:  # noqa: BLE001
            if attempt >= retry_count:
                logger.warning("Verification AI error: %s", e)
                return VerificationResult(has_errors=False, corrections=[])
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 5.0)
    return VerificationResult(has_errors=False, corrections=[])


async def process_verification_batch(task_id: UUID, transaction_ids: List[int]) -> None:
    """Background verification of transactions; persists progress/results."""
    try:
        tx_limit = max(1, int(BATCH_APPLY_MAX_ITEMS))
        limited_ids = [int(tid) for tid in transaction_ids[:tx_limit]]
        with SessionLocal() as db:
            initialized = _update_task_atomic(
                db,
                task_id,
                expected_status="pending",
                status="processing",
                progress_json=json.dumps({"total": len(limited_ids), "processed": 0, "percent": 0}),
            )
            if not initialized:
                logger.warning("Verification task %s cannot start (already changed status)", task_id)
                return

            tx_rows = (
                db.query(Transaction)
                .filter(Transaction.id.in_(limited_ids))
                .order_by(Transaction.transaction_date.desc())
                .all()
            )
            txs: List[Dict[str, Any]] = [
                {
                    "id": tx.id,
                    "raw_message": tx.raw_message,
                    "transaction_date": tx.transaction_date,
                    "amount": tx.amount,
                    "currency": tx.currency,
                    "operator_raw": tx.operator_raw,
                    "card_last_4": tx.card_last_4,
                    "balance_after": tx.balance_after,
                    "transaction_type": tx.transaction_type,
                    "receiver_name": tx.receiver_name,
                    "receiver_card": tx.receiver_card,
                }
                for tx in tx_rows
            ]

        total = len(txs)
        processed = 0
        correction_count = 0
        error_tx_count = 0
        progress_every = 50

        with SessionLocal() as write_db:
            for tx in txs:
                try:
                    if tx.get("raw_message"):
                        parsed_fields = {
                            "transaction_date": tx.get("transaction_date").isoformat() if tx.get("transaction_date") else None,
                            "amount": str(abs(tx.get("amount"))) if tx.get("amount") is not None else None,
                            "currency": tx.get("currency"),
                            "operator_raw": tx.get("operator_raw"),
                            "card_last_4": tx.get("card_last_4"),
                            "balance_after": str(tx.get("balance_after")) if tx.get("balance_after") is not None else None,
                            "transaction_type": tx.get("transaction_type"),
                            "receiver_name": tx.get("receiver_name"),
                            "receiver_card": tx.get("receiver_card"),
                        }

                        result = await verify_transaction_with_ai(tx["raw_message"], parsed_fields)

                        if result.has_errors and result.corrections:
                            for correction in result.corrections:
                                if correction.field_name not in VERIFIABLE_FIELDS:
                                    continue
                                write_db.add(VerificationSuggestion(
                                    id=uuid4(),
                                    task_id=task_id,
                                    transaction_id=int(tx["id"]),
                                    field_name=correction.field_name,
                                    current_value=correction.current_value,
                                    suggested_value=correction.suggested_value,
                                    confidence=correction.confidence,
                                    reasoning=correction.reasoning,
                                    status="pending",
                                ))
                                correction_count += 1
                            error_tx_count += 1

                except Exception as e:  # noqa: BLE001
                    logger.warning("Error verifying tx %s: %s", tx.get("id"), e)

                processed += 1
                if processed % progress_every == 0 or processed == total:
                    write_db.commit()
                    _update_task_atomic(
                        write_db,
                        task_id,
                        expected_status="processing",
                        progress_json=json.dumps({
                            "total": total,
                            "processed": processed,
                            "percent": round((processed / max(total, 1)) * 100, 1),
                        }),
                    )
                await asyncio.sleep(0.3)

            write_db.commit()
            _update_task_atomic(
                write_db,
                task_id,
                expected_status="processing",
                status="completed",
                result_json=json.dumps({
                    "total_verified": total,
                    "transactions_with_errors": error_tx_count,
                    "total_corrections": correction_count,
                }),
            )
    except Exception as e:  # noqa: BLE001
        with SessionLocal() as db:
            _update_task_atomic(
                db,
                task_id,
                expected_status="processing",
                status="failed",
                result_json=json.dumps({"error": str(e)}),
            )


@router.post("/verify-transactions", response_model=VerifyResponse)
async def verify_transactions(
    request: VerifyRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("automation")),
    scope: Optional[dict] = Depends(require_transactions_scope),
):
    _ = current_user
    query = db.query(Transaction).filter(
        Transaction.raw_message != None,  # noqa: E711
        Transaction.raw_message != "",
    )
    query = _apply_scope_filter(query, scope)
    query = _apply_locked_periods_filter(query, db)
    if request.date_from:
        query = query.filter(Transaction.transaction_date >= request.date_from)
    if request.date_to:
        query = query.filter(Transaction.transaction_date <= request.date_to)
    safe_limit = min(max(1, int(request.limit or 50)), max(1, int(BATCH_APPLY_MAX_ITEMS)))
    txs = query.order_by(Transaction.transaction_date.desc()).limit(safe_limit).all()

    task_id = uuid4()

    if not txs:
        task = AutomationTask(
            id=task_id,
            status="completed",
            progress_json=json.dumps({"total": 0, "processed": 0, "percent": 100}),
            result_json=json.dumps({"total_verified": 0, "transactions_with_errors": 0, "total_corrections": 0}),
        )
        db.add(task)
        db.commit()
        return VerifyResponse(task_id=task_id, status="empty", message="No transactions found for verification")

    task = AutomationTask(
        id=task_id,
        status="pending",
        progress_json=json.dumps({"total": len(txs), "processed": 0, "percent": 0}),
    )
    db.add(task)
    db.commit()

    asyncio.create_task(
        _run_background_task(
            task_id,
            f"automation-verify-{task_id}",
            process_verification_batch(task_id, [t.id for t in txs]),
        )
    )

    return VerifyResponse(
        task_id=task_id, status="started",
        message=f"Verification started for {len(txs)} transactions",
    )


@router.get("/verify-status/{task_id}", response_model=VerifyStatusResponse)
async def get_verify_status(
    task_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("automation")),
    scope: Optional[dict] = Depends(require_transactions_scope),
):
    _ = current_user, scope
    task = db.get(AutomationTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return VerifyStatusResponse(
        task_id=task.id,
        status=task.status,
        progress=json.loads(task.progress_json or "{}"),
        results=json.loads(task.result_json or "{}") if task.result_json else None,
    )


@router.get("/verification-suggestions", response_model=List[VerificationSuggestionResponse])
async def get_verification_suggestions(
    status: Optional[str] = "pending",
    task_id: Optional[UUID] = None,
    confidence_min: Optional[float] = 0.0,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("automation")),
    scope: Optional[dict] = Depends(require_transactions_scope),
):
    _ = current_user
    q = db.query(VerificationSuggestion, Transaction).join(
        Transaction, Transaction.id == VerificationSuggestion.transaction_id
    )
    q = _apply_scope_filter(q, scope)
    q = _apply_locked_periods_filter(q, db)
    if status:
        q = q.filter(VerificationSuggestion.status == status)
    if task_id:
        q = q.filter(VerificationSuggestion.task_id == task_id)
    if confidence_min:
        q = q.filter(VerificationSuggestion.confidence >= confidence_min)
    rows = q.order_by(VerificationSuggestion.created_at.desc()).offset(offset).limit(limit).all()
    return [
        VerificationSuggestionResponse(
            id=r.id,
            task_id=r.task_id,
            transaction_id=r.transaction_id,
            field_name=r.field_name,
            field_label=FIELD_LABELS_RU.get(r.field_name, r.field_name),
            current_value=r.current_value,
            suggested_value=r.suggested_value,
            confidence=r.confidence,
            reasoning=r.reasoning,
            status=r.status,
            created_at=r.created_at,
        )
        for r, _tx in rows
    ]


@router.post("/verification-suggestions/{suggestion_id}/apply")
async def apply_verification_suggestion(
    suggestion_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("automation")),
    scope: Optional[dict] = Depends(require_transactions_scope),
):
    _ = current_user
    sug = db.get(VerificationSuggestion, suggestion_id)
    if not sug:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    tx = db.query(Transaction).filter(Transaction.id == sug.transaction_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    _assert_tx_edit_allowed(tx, scope, db)

    field = sug.field_name
    value = sug.suggested_value

    try:
        _apply_verification_field(tx, field, value)
    except (ValueError, TypeError, ArithmeticError, InvalidOperation) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid value for {field}: {exc}") from exc

    sug.status = "approved"
    db.commit()
    _audit_automation_action(
        db,
        action="automation_apply_verification_suggestion",
        current_user=current_user,
        details={"suggestion_id": str(suggestion_id), "transaction_id": tx.id, "field": field},
    )
    return {"success": True, "transaction_id": tx.id, "field": field, "new_value": value}


@router.post("/verification-suggestions/{suggestion_id}/reject")
async def reject_verification_suggestion(
    suggestion_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("automation")),
    scope: Optional[dict] = Depends(require_transactions_scope),
):
    _ = current_user, scope
    sug = db.get(VerificationSuggestion, suggestion_id)
    if not sug:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    sug.status = "rejected"
    db.commit()
    _audit_automation_action(
        db,
        action="automation_reject_verification_suggestion",
        current_user=current_user,
        details={"suggestion_id": str(suggestion_id), "transaction_id": sug.transaction_id},
    )
    return {"success": True}


@router.post("/verification-suggestions/batch-apply")
async def batch_apply_verification_suggestions(
    suggestion_ids: List[UUID],
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("automation")),
    scope: Optional[dict] = Depends(require_transactions_scope),
):
    _ = current_user
    if len(suggestion_ids) > max(1, int(BATCH_APPLY_MAX_ITEMS)):
        raise HTTPException(
            status_code=400,
            detail=f"Too many suggestions (max {max(1, int(BATCH_APPLY_MAX_ITEMS))})",
        )

    applied = 0
    errors = []
    for sug_id in suggestion_ids:
        try:
            with db.begin_nested():
                sug = db.get(VerificationSuggestion, sug_id)
                if not sug:
                    errors.append({"suggestion_id": str(sug_id), "error": "Not found"})
                    continue
                tx = db.query(Transaction).filter(Transaction.id == sug.transaction_id).first()
                if not tx:
                    errors.append({"suggestion_id": str(sug_id), "error": "Transaction not found"})
                    continue
                denial_reason = _tx_edit_denial_reason(tx, scope, db)
                if denial_reason:
                    errors.append({"suggestion_id": str(sug_id), "error": denial_reason})
                    continue

                field = sug.field_name
                value = sug.suggested_value
                _apply_verification_field(tx, field, value)

                sug.status = "approved"
                db.flush()
                applied += 1
        except Exception as e:  # noqa: BLE001
            errors.append({"suggestion_id": str(sug_id), "error": _normalize_error_text(e)})
    db.commit()
    _audit_automation_action(
        db,
        action="automation_batch_apply_verification_suggestions",
        current_user=current_user,
        details={"requested": len(suggestion_ids), "applied": applied, "errors": len(errors)},
    )

    return {"success": True, "applied": applied, "errors": errors}
