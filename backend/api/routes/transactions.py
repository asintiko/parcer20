"""
Transaction API routes
Server-side pagination, sorting, and filtering for financial transactions
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, asc, desc, extract
from typing import List, Optional, Callable
from datetime import datetime
from pydantic import BaseModel, Field
from decimal import Decimal

from database.connection import get_db_session
from database.models import Transaction

router = APIRouter()


# Pydantic schemas
class TransactionResponse(BaseModel):
    id: int
    transaction_date: datetime
    amount: str
    currency: str
    card_last_4: Optional[str]
    operator_raw: Optional[str]
    application_mapped: Optional[str]
    transaction_type: str
    balance_after: Optional[str]
    source_type: str
    parsing_method: Optional[str]
    parsing_confidence: Optional[float]
    is_p2p: Optional[bool] = None  # Not stored on Transaction yet
    created_at: datetime
    raw_message: Optional[str] = None

    class Config:
        from_attributes = True


class TransactionListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[TransactionResponse]


# Update/Delete schemas
class TransactionUpdateRequest(BaseModel):
    """Schema for updating transaction fields"""
    transaction_date: Optional[datetime] = None
    operator_raw: Optional[str] = Field(None, max_length=255)
    application_mapped: Optional[str] = Field(None, max_length=100)
    amount: Optional[Decimal] = Field(None, ge=0)
    balance_after: Optional[Decimal] = None
    card_last_4: Optional[str] = Field(None, pattern=r'^\d{4}$')
    transaction_type: Optional[str] = Field(None, pattern=r'^(DEBIT|CREDIT|CONVERSION|REVERSAL)$')
    currency: Optional[str] = Field(None, pattern=r'^(UZS|USD)$')
    source_type: Optional[str] = Field(None, pattern=r'^(AUTO|MANUAL)$')
    parsing_method: Optional[str] = None
    parsing_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    # Kept for backward compatibility with UI but ignored server-side
    is_p2p: Optional[bool] = None

    class Config:
        json_schema_extra = {
            "example": {
                "operator_raw": "Updated Operator Name",
                "amount": "150000.00",
                "application_mapped": "Payme",
                "transaction_type": "DEBIT"
            }
        }


class TransactionUpdateResponse(BaseModel):
    """Response after successful update"""
    success: bool
    message: str
    transaction: TransactionResponse


class DeleteResponse(BaseModel):
    """Response after deletion"""
    success: bool
    message: str
    deleted_id: int


class BulkDeleteRequest(BaseModel):
    """Schema for bulk delete operations"""
    ids: List[int] = Field(..., min_length=1, max_length=100)


class BulkDeleteResponse(BaseModel):
    """Response for bulk delete"""
    success: bool
    deleted_count: int
    failed_ids: List[int] = []
    errors: List[str] = []


def _split_csv(values: Optional[str]) -> List[str]:
    if not values:
        return []
    return [v.strip() for v in values.split(",") if v.strip()]


@router.get("/", response_model=TransactionListResponse)
async def get_transactions(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(100, ge=1, le=1000, description="Items per page"),
    sort_by: str = Query("transaction_date", description="Sort field"),
    sort_dir: str = Query("desc", description="Sort direction: asc|desc"),
    date_from: Optional[datetime] = Query(None, description="Start date"),
    date_to: Optional[datetime] = Query(None, description="End date"),
    operator: Optional[str] = Query(None, description="Operator contains"),
    operators: Optional[str] = Query(None, description="Comma-separated operators for IN filter"),
    app: Optional[str] = Query(None, description="Application contains"),
    apps: Optional[str] = Query(None, description="Comma-separated apps for IN filter"),
    amount_min: Optional[Decimal] = Query(None, ge=0),
    amount_max: Optional[Decimal] = Query(None, ge=0),
    parsing_method: Optional[str] = Query(None),
    confidence_min: Optional[float] = Query(None, ge=0.0, le=1.0),
    confidence_max: Optional[float] = Query(None, ge=0.0, le=1.0),
    search: Optional[str] = Query(None, description="Free-text search in raw_message"),
    source_type: Optional[str] = Query(None, pattern="^(AUTO|MANUAL)$"),
    transaction_type: Optional[str] = Query(None, pattern="^(DEBIT|CREDIT|CONVERSION|REVERSAL)$"),
    transaction_types: Optional[str] = Query(None, description="Comma-separated transaction types for IN filter"),
    currency: Optional[str] = Query(None, pattern="^(UZS|USD)$"),
    card: Optional[str] = Query(None, description="Filter by last 4 digits of card"),
    days_of_week: Optional[str] = Query(None, description="Comma-separated day of week numbers 0-6"),
    db: Session = Depends(get_db_session)
):
    """
    Get paginated list of transactions with server-side filters and sorting.
    """
    try:
        query = db.query(Transaction)

        # Filters
        if date_from:
            query = query.filter(Transaction.transaction_date >= date_from)
        if date_to:
            query = query.filter(Transaction.transaction_date <= date_to)
        if operator:
            query = query.filter(Transaction.operator_raw.ilike(f"%{operator}%"))
        operator_list = _split_csv(operators)
        if operator_list:
            query = query.filter(Transaction.operator_raw.in_(operator_list))
        if app:
            query = query.filter(Transaction.application_mapped.ilike(f"%{app}%"))
        app_list = _split_csv(apps)
        if app_list:
            query = query.filter(Transaction.application_mapped.in_(app_list))
        if amount_min is not None:
            query = query.filter(Transaction.amount >= amount_min)
        if amount_max is not None:
            query = query.filter(Transaction.amount <= amount_max)
        if parsing_method:
            query = query.filter(Transaction.parsing_method == parsing_method)
        if confidence_min is not None:
            query = query.filter(Transaction.parsing_confidence >= confidence_min)
        if confidence_max is not None:
            query = query.filter(Transaction.parsing_confidence <= confidence_max)
        if search:
            query = query.filter(Transaction.raw_message.ilike(f"%{search}%"))
        if source_type:
            query = query.filter(Transaction.source_type == source_type)
        if transaction_type:
            query = query.filter(Transaction.transaction_type == transaction_type)
        tx_type_list = _split_csv(transaction_types)
        if tx_type_list:
            query = query.filter(Transaction.transaction_type.in_(tx_type_list))
        if currency:
            query = query.filter(Transaction.currency == currency)
        if card:
            query = query.filter(Transaction.card_last_4 == card)
        dow_values = [int(x) for x in _split_csv(days_of_week) if x.isdigit()]
        if dow_values:
            query = query.filter(extract("dow", Transaction.transaction_date).in_(dow_values))

        total = query.count()

        # Sorting (whitelisted)
        sort_map: dict[str, Callable] = {
            "transaction_date": Transaction.transaction_date,
            "amount": Transaction.amount,
            "created_at": Transaction.created_at,
            "parsing_confidence": Transaction.parsing_confidence,
        }
        sort_column = sort_map.get(sort_by, Transaction.transaction_date)
        order_fn = desc if sort_dir.lower() == "desc" else asc
        query = query.order_by(order_fn(sort_column), Transaction.id.desc())

        # Pagination
        offset = (page - 1) * page_size
        rows = query.offset(offset).limit(page_size).all()

        return TransactionListResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=rows
        )

    finally:
        db.close()


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: int,
    db: Session = Depends(get_db_session)
):
    """Get single transaction by ID"""
    try:
        transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()

        if not transaction:
            raise HTTPException(status_code=404, detail="Transaction not found")

        return transaction
    finally:
        db.close()


@router.put("/{transaction_id}", response_model=TransactionUpdateResponse)
async def update_transaction(
    transaction_id: int,
    update_data: TransactionUpdateRequest,
    db: Session = Depends(get_db_session)
):
    """
    Update a transaction by ID (partial updates supported).
    """
    try:
        transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()

        if not transaction:
            raise HTTPException(status_code=404, detail=f"Transaction {transaction_id} not found")

        update_dict = update_data.model_dump(exclude_unset=True)

        field_map = {
            "transaction_date": "transaction_date",
            "operator_raw": "operator_raw",
            "application_mapped": "application_mapped",
            "amount": "amount",
            "balance_after": "balance_after",
            "card_last_4": "card_last_4",
            "transaction_type": "transaction_type",
            "currency": "currency",
            "source_type": "source_type",
            "parsing_method": "parsing_method",
            "parsing_confidence": "parsing_confidence",
        }

        for field, value in update_dict.items():
            target_field = field_map.get(field)
            if target_field is None:
                continue
            setattr(transaction, target_field, value)

        transaction.updated_at = func.now()

        db.commit()
        db.refresh(transaction)

        return TransactionUpdateResponse(
            success=True,
            message="Transaction updated successfully",
            transaction=transaction
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")
    finally:
        db.close()


@router.delete("/{transaction_id}", response_model=DeleteResponse)
async def delete_transaction(
    transaction_id: int,
    db: Session = Depends(get_db_session)
):
    """
    Delete a transaction by ID
    """
    try:
        transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()

        if not transaction:
            raise HTTPException(status_code=404, detail=f"Transaction {transaction_id} not found")

        db.delete(transaction)
        db.commit()

        return DeleteResponse(
            success=True,
            message="Transaction deleted successfully",
            deleted_id=transaction_id
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")
    finally:
        db.close()


@router.post("/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_transactions(
    request: BulkDeleteRequest,
    db: Session = Depends(get_db_session)
):
    """
    Delete multiple transactions at once
    """
    try:
        deleted_count = 0
        failed_ids = []
        errors = []

        for transaction_id in request.ids:
            try:
                transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
                if transaction:
                    db.delete(transaction)
                    deleted_count += 1
                else:
                    failed_ids.append(transaction_id)
                    errors.append(f"ID {transaction_id} not found")
            except Exception as e:
                failed_ids.append(transaction_id)
                errors.append(f"ID {transaction_id}: {str(e)}")

        db.commit()

        return BulkDeleteResponse(
            success=len(failed_ids) == 0,
            deleted_count=deleted_count,
            failed_ids=failed_ids,
            errors=errors
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Bulk delete failed: {str(e)}")
    finally:
        db.close()
