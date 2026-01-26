"""
Logs API routes - логирование обработки чеков
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from api.routes.auth import get_current_user
from database.connection import get_db_session
from database.models import ReceiptProcessingTask, Transaction

router = APIRouter()


class LogEntry(BaseModel):
    """Модель записи лога"""
    id: int
    task_id: str
    chat_id: int
    message_id: int
    status: str  # queued | processing | done | failed
    error: Optional[str] = None
    transaction_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    # Дополнительная информация о транзакции
    is_duplicate: bool = False
    operator_raw: Optional[str] = None
    amount: Optional[str] = None

    class Config:
        from_attributes = True


class LogsResponse(BaseModel):
    """Ответ со списком логов"""
    total: int
    page: int
    page_size: int
    items: List[LogEntry]


class LogStats(BaseModel):
    """Статистика логов"""
    total: int
    success: int
    failed: int
    duplicates: int
    processing: int


@router.get("/stats", response_model=LogStats)
async def get_logs_stats(
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
):
    """Получить статистику логов обработки"""
    total = db.query(ReceiptProcessingTask).count()
    success = db.query(ReceiptProcessingTask).filter(
        ReceiptProcessingTask.status == "done"
    ).count()
    failed = db.query(ReceiptProcessingTask).filter(
        ReceiptProcessingTask.status == "failed"
    ).count()
    processing = db.query(ReceiptProcessingTask).filter(
        ReceiptProcessingTask.status.in_(["queued", "processing"])
    ).count()
    
    # Подсчёт дубликатов через поиск "duplicate" в error или через связанные транзакции
    duplicates = db.query(ReceiptProcessingTask).filter(
        or_(
            ReceiptProcessingTask.error.ilike("%duplicate%"),
            ReceiptProcessingTask.error.ilike("%дубликат%"),
        )
    ).count()
    
    return LogStats(
        total=total,
        success=success,
        failed=failed,
        duplicates=duplicates,
        processing=processing,
    )


@router.get("", response_model=LogsResponse)
async def get_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status: Optional[str] = Query(None, description="Filter by status: done, failed, queued, processing"),
    search: Optional[str] = Query(None, description="Search in error message"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    duplicates_only: bool = Query(False, description="Show only duplicates"),
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
):
    """Получить список логов обработки с пагинацией и фильтрами"""
    query = db.query(ReceiptProcessingTask)
    
    # Фильтр по статусу
    if status:
        query = query.filter(ReceiptProcessingTask.status == status)
    
    # Поиск в сообщении об ошибке
    if search:
        query = query.filter(ReceiptProcessingTask.error.ilike(f"%{search}%"))
    
    # Фильтр по дате
    if date_from:
        query = query.filter(ReceiptProcessingTask.created_at >= date_from)
    if date_to:
        query = query.filter(ReceiptProcessingTask.created_at <= date_to)
    
    # Только дубликаты
    if duplicates_only:
        query = query.filter(
            or_(
                ReceiptProcessingTask.error.ilike("%duplicate%"),
                ReceiptProcessingTask.error.ilike("%дубликат%"),
                ReceiptProcessingTask.error.ilike("%Already processed%"),
            )
        )
    
    # Подсчёт общего количества
    total = query.count()
    
    # Пагинация и сортировка (новые сверху)
    offset = (page - 1) * page_size
    tasks = query.order_by(desc(ReceiptProcessingTask.created_at)).offset(offset).limit(page_size).all()
    
    # Формируем ответ с дополнительной информацией
    items = []
    for task in tasks:
        is_duplicate = False
        operator_raw = None
        amount = None
        
        # Проверяем на дубликат
        if task.error and any(kw in task.error.lower() for kw in ["duplicate", "дубликат", "already processed"]):
            is_duplicate = True
        
        # Получаем информацию о связанной транзакции
        if task.transaction_id:
            txn = db.query(Transaction).filter(Transaction.id == task.transaction_id).first()
            if txn:
                operator_raw = txn.operator_raw
                amount = str(abs(txn.amount)) if txn.amount else None
        
        items.append(LogEntry(
            id=task.id,
            task_id=task.task_id,
            chat_id=task.chat_id,
            message_id=task.message_id,
            status=task.status,
            error=task.error,
            transaction_id=task.transaction_id,
            created_at=task.created_at,
            updated_at=task.updated_at,
            is_duplicate=is_duplicate,
            operator_raw=operator_raw,
            amount=amount,
        ))
    
    return LogsResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )
