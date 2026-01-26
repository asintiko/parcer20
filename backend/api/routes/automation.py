"""
API Routes for AI-powered Transaction Automation (production-ready)
Stores tasks/suggestions in DB to survive restarts.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, Field
from uuid import uuid4, UUID
from datetime import datetime
import asyncio
import os
import json
import httpx
from bs4 import BeautifulSoup
from openai import AsyncOpenAI

from database.connection import get_db_session, SessionLocal
from database.models import (
    Transaction,
    OperatorReference,
    AutomationTask,
    AutomationSuggestion,
)
from api.dependencies import get_current_user

router = APIRouter(prefix="/api/automation", tags=["automation"])

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


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


def get_existing_applications(db: Session) -> List[str]:
    apps = (
        db.query(OperatorReference.application_name)
        .distinct()
        .filter(OperatorReference.is_active == True)  # noqa: E712
        .all()
    )
    return [a[0] for a in apps if a[0]]


async def search_web_for_operator(operator_raw: str) -> str:
    """Lightweight web search via DuckDuckGo HTML."""
    try:
        search_query = f"{operator_raw} Узбекистан приложение оплата"
        async with httpx.AsyncClient(timeout=10.0) as client_http:
            response = await client_http.get(
                "https://html.duckduckgo.com/html/",
                params={"q": search_query},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                snippets = []
                results = soup.find_all("a", class_="result__snippet", limit=3)
                for r in results:
                    text = r.get_text(strip=True)
                    if text and len(text) > 20:
                        snippets.append(text)
                if snippets:
                    return "\n".join(snippets[:3])
        return "Информация не найдена"
    except Exception as e:  # noqa: BLE001
        print(f"Web search error: {e}")
        return "Ошибка поиска"


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

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt.format(apps_list=apps_list)},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=200,
        )
        result = json.loads(response.choices[0].message.content)
        return AISuggestion(**result)
    except Exception as e:  # noqa: BLE001
        print(f"OpenAI API Error: {e}")
        return AISuggestion(
            application="Unknown",
            confidence=0.0,
            is_new=True,
            is_p2p=False,
            reasoning=f"Error: {str(e)}",
        )


async def process_transactions_batch(task_id: UUID, transaction_ids: List[int]) -> None:
    """Background processing of transactions; persists progress/results."""
    def update_task(session: Session, **kwargs) -> None:
        session.query(AutomationTask).filter(AutomationTask.id == task_id).update(
            kwargs, synchronize_session=False
        )
        session.commit()

    try:
        with SessionLocal() as db:
            task = db.get(AutomationTask, task_id)
            if not task:
                return
            update_task(db, status="processing", progress_json=json.dumps({"total": len(transaction_ids), "processed": 0, "percent": 0}))

            txs = (
                db.query(Transaction)
                .filter(Transaction.id.in_(transaction_ids))
                .order_by(Transaction.transaction_date.desc())
                .all()
            )
            existing_apps = set(get_existing_applications(db))

        total = len(txs)
        processed = 0
        suggestion_count = 0
        high_conf = 0

        for tx in txs:
            try:
                context = {
                    "transaction_type": tx.transaction_type,
                    "amount": str(tx.amount) if tx.amount is not None else None,
                    "datetime": tx.transaction_date.isoformat() if tx.transaction_date else None,
                }
                ai_result = await analyze_with_ai(tx.operator_raw or "Unknown", list(existing_apps), context)

                with SessionLocal() as db:
                    db.add(
                        AutomationSuggestion(
                            id=uuid4(),
                            task_id=task_id,
                            transaction_id=tx.id,
                            suggested_application=ai_result.application,
                            confidence=ai_result.confidence,
                            is_p2p=ai_result.is_p2p,
                            status="pending",
                            reasoning=ai_result.reasoning,
                        )
                    )
                    db.commit()

                suggestion_count += 1
                if ai_result.confidence >= 0.8:
                    high_conf += 1
            except Exception as e:  # noqa: BLE001
                print(f"Error processing tx {tx.id}: {e}")

            processed += 1
            with SessionLocal() as db:
                update_task(
                    db,
                    progress_json=json.dumps(
                        {
                            "total": total,
                            "processed": processed,
                            "percent": round((processed / max(total, 1)) * 100, 1),
                        }
                    ),
                )
            await asyncio.sleep(0.2)  # gentle pacing

        with SessionLocal() as db:
            update_task(
                db,
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
            update_task(
                db,
                status="failed",
                result_json=json.dumps({"error": str(e)}),
            )


@router.post("/analyze-transactions", response_model=AnalyzeResponse)
async def analyze_transactions(
    request: AnalyzeRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
):
    query = db.query(Transaction)
    if request.only_unmapped:
        query = query.filter((Transaction.application_mapped == None) | (Transaction.application_mapped == ""))  # noqa: E711
    if request.currency_filter:
        query = query.filter(Transaction.currency == request.currency_filter)
    txs = query.order_by(Transaction.transaction_date.desc()).limit(request.limit).all()

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

    asyncio.create_task(process_transactions_batch(task_id, [t.id for t in txs]))

    return AnalyzeResponse(task_id=task_id, status="started", message=f"Analysis started for {len(txs)} transactions")


@router.get("/analyze-status/{task_id}", response_model=AnalyzeStatusResponse)
async def get_analyze_status(
    task_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
):
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
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
):
    q = (
        db.query(AutomationSuggestion, Transaction)
        .join(Transaction, Transaction.id == AutomationSuggestion.transaction_id)
    )
    if status:
        q = q.filter(AutomationSuggestion.status == status)
    if confidence_min:
        q = q.filter(AutomationSuggestion.confidence >= confidence_min)
    if task_id:
        q = q.filter(AutomationSuggestion.task_id == task_id)

    rows = q.order_by(AutomationSuggestion.created_at.desc()).all()

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
                is_new_application=False,
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
    current_user: dict = Depends(get_current_user),
):
    sug = db.get(AutomationSuggestion, suggestion_id)
    if not sug:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    tx = db.query(Transaction).filter(Transaction.id == sug.transaction_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    tx.application_mapped = sug.suggested_application
    tx.is_p2p = sug.is_p2p
    sug.status = "approved"
    db.commit()
    db.refresh(tx)

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
    current_user: dict = Depends(get_current_user),
):
    sug = db.get(AutomationSuggestion, suggestion_id)
    if not sug:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    sug.status = "rejected"
    db.commit()
    return {"success": True}


@router.post("/suggestions/batch-apply")
async def batch_apply_suggestions(
    suggestion_ids: List[UUID],
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
):
    applied = 0
    errors = []
    updated_transactions = []

    for sug_id in suggestion_ids:
        try:
            sug = db.get(AutomationSuggestion, sug_id)
            if not sug:
                errors.append({"suggestion_id": str(sug_id), "error": "Suggestion not found"})
                continue

            tx = db.query(Transaction).filter(Transaction.id == sug.transaction_id).first()
            if not tx:
                errors.append({"suggestion_id": str(sug_id), "error": "Transaction not found"})
                continue

            tx.application_mapped = sug.suggested_application
            tx.is_p2p = sug.is_p2p
            sug.status = "approved"
            db.commit()
            db.refresh(tx)

            updated_transactions.append({
                "id": tx.id,
                "operator_raw": tx.operator_raw,
                "application_mapped": tx.application_mapped,
                "is_p2p": tx.is_p2p,
            })
            applied += 1
        except Exception as e:  # noqa: BLE001
            db.rollback()
            errors.append({"suggestion_id": str(sug_id), "error": str(e)})

    return {
        "success": True,
        "applied": applied,
        "errors": errors,
        "updated_transactions": updated_transactions
    }
