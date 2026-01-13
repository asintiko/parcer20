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
from database.models import Transaction, Check

# Normalization helpers
def normalize_source_type(added_via: Optional[str]) -> str:
    """
    Map legacy source/added_via values to AUTO|MANUAL
    """
    if not added_via:
        return "MANUAL"
    value = added_via.strip().lower()
    if value in {"bot", "auto", "telegram", "userbot"}:
        return "AUTO"
    return "MANUAL"


def normalize_transaction_type(raw: Optional[str]) -> str:
    """
    Map Russian / legacy transaction types to canonical enums
    """
    if not raw:
        return "DEBIT"
    upper = raw.upper()
    if upper in {"DEBIT", "CREDIT", "CONVERSION", "REVERSAL"}:
        return upper
    mapping = {
        "СПИСАНИЕ": "DEBIT",
        "ПОПОЛНЕНИЕ": "CREDIT",
        "ПОСТУПЛЕНИЕ": "CREDIT",
        "КОНВЕРСИЯ": "CONVERSION",
        "ОТМЕНА": "REVERSAL",
        "OTMENA": "REVERSAL",
    }
    return mapping.get(upper, "DEBIT")


def normalize_amount_for_response(amount: Decimal) -> str:
    """
    Present amount as positive string for UI
    """
    return f"{abs(Decimal(amount))}"

def compute_weekday_label(dt: datetime) -> str:
    weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    return weekdays[dt.weekday()]


def compute_date_display(dt: datetime) -> str:
    months = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
    return f"{dt.day} {months[dt.month - 1]}"


def compute_time_display(dt: datetime) -> str:
    return dt.strftime("%H:%M")

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
    updated_at: Optional[datetime] = None
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


class BulkUpdateItem(BaseModel):
    id: int
    fields: dict


class BulkUpdateRequest(BaseModel):
    updates: List[BulkUpdateItem] = Field(..., min_items=1, max_items=500)


class BulkUpdateResponse(BaseModel):
    success: bool
    updated_count: int
    failed_ids: List[int]
    errors: List[str]


class TransactionCreateRequest(BaseModel):
    datetime: datetime = Field(..., description="Transaction datetime")
    operator: str = Field(..., min_length=1, max_length=255)
    amount: Decimal = Field(..., ge=0)
    card_last4: str = Field(..., pattern=r'^\d{4}$')
    transaction_type: str = Field(..., pattern=r'^(DEBIT|CREDIT|CONVERSION|REVERSAL)$')
    currency: str = Field(..., pattern=r'^(UZS|USD)$')
    app: Optional[str] = Field(None, max_length=100)
    balance: Optional[Decimal] = None
    is_p2p: Optional[bool] = False
    raw_text: Optional[str] = None


@router.patch("/bulk-update", response_model=BulkUpdateResponse)
async def bulk_update_transactions(
    request: BulkUpdateRequest,
    db: Session = Depends(get_db_session)
):
    """
    Apply multiple updates in one request.
    """
    allowed_fields = {
        "transaction_date",
        "operator_raw",
        "application_mapped",
        "amount",
        "balance_after",
        "card_last_4",
        "transaction_type",
        "currency",
        "source_type",
        "is_p2p",
    }

    failed_ids: List[int] = []
    errors: List[str] = []
    updated_count = 0

    try:
        for item in request.updates:
            c = db.query(Check).filter(Check.id == item.id).first()
            if not c:
                failed_ids.append(item.id)
                errors.append(f"ID {item.id} not found")
                continue

            fields = item.fields
            # reject unknown fields
            for key in list(fields.keys()):
                if key not in allowed_fields:
                    fields.pop(key, None)

            # Normalize fields
            if "transaction_type" in fields:
                c.transaction_type = normalize_transaction_type(fields["transaction_type"])

            if "source_type" in fields:
                src = fields["source_type"]
                c.added_via = "bot" if src == "AUTO" else "manual"

            if "transaction_date" in fields:
                c.datetime = fields["transaction_date"]

            if "operator_raw" in fields:
                c.operator = fields["operator_raw"]

            if "application_mapped" in fields:
                c.app = fields["application_mapped"]

            if "currency" in fields:
                c.currency = fields["currency"]

            if "card_last_4" in fields:
                c.card_last4 = fields["card_last_4"]

            if "is_p2p" in fields:
                c.is_p2p = fields["is_p2p"]

            if "balance_after" in fields:
                c.balance = fields["balance_after"]

            if "amount" in fields:
                amt = Decimal(str(fields["amount"]))
                txn_type = c.transaction_type or normalize_transaction_type(None)
                store_amount = -abs(amt) if txn_type == "DEBIT" else abs(amt)
                c.amount = store_amount

            c.updated_at = func.now()
            updated_count += 1

        db.commit()

        return BulkUpdateResponse(
            success=len(failed_ids) == 0,
            updated_count=updated_count,
            failed_ids=failed_ids,
            errors=errors
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Bulk update failed: {str(e)}")


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
    Get paginated list of transactions (Checks) with server-side filters and sorting.
    """
    query = db.query(Check)

    # Filters
    if date_from:
        query = query.filter(Check.datetime >= date_from)
    if date_to:
        query = query.filter(Check.datetime <= date_to)
    if operator:
        query = query.filter(Check.operator.ilike(f"%{operator}%"))
    operator_list = _split_csv(operators)
    if operator_list:
        query = query.filter(Check.operator.in_(operator_list))
    if app:
        query = query.filter(Check.app.ilike(f"%{app}%"))
    app_list = _split_csv(apps)
    if app_list:
        query = query.filter(Check.app.in_(app_list))
    if amount_min is not None:
        query = query.filter(Check.amount >= amount_min)
    if amount_max is not None:
        query = query.filter(Check.amount <= amount_max)
    if parsing_method:
        query = query.filter(Check.added_via.ilike(f"%{parsing_method}%"))
    if search:
        query = query.filter(Check.raw_text.ilike(f"%{search}%"))
    if source_type:
        # map AUTO -> bot, MANUAL -> manual
        if source_type == "AUTO":
            query = query.filter(Check.added_via.ilike("%bot%"))
        else:
            query = query.filter(Check.added_via.ilike("%manual%"))
    if transaction_type:
        norm_type = normalize_transaction_type(transaction_type)
        query = query.filter(Check.transaction_type == norm_type)
    tx_type_list = _split_csv(transaction_types)
    if tx_type_list:
        norm_list = [normalize_transaction_type(t) for t in tx_type_list]
        query = query.filter(Check.transaction_type.in_(norm_list))
    if currency:
        query = query.filter(Check.currency == currency)
    if card:
        query = query.filter(Check.card_last4 == card)
    dow_values = [int(x) for x in _split_csv(days_of_week) if x.isdigit()]
    if dow_values:
        query = query.filter(extract("dow", Check.datetime).in_(dow_values))

    total = query.count()

    # Sorting (whitelisted)
    sort_map: dict[str, Callable] = {
        "transaction_date": Check.datetime,
        "amount": Check.amount,
        "created_at": Check.created_at,
        "parsing_confidence": Check.metadata_json,  # placeholder for absence, fall back to created_at
        "updated_at": Check.updated_at,
    }
    sort_column = sort_map.get(sort_by, Check.datetime)
    order_fn = desc if sort_dir.lower() == "desc" else asc
    query = query.order_by(order_fn(sort_column), Transaction.id.desc())

    # Pagination
    offset = (page - 1) * page_size
    rows = query.offset(offset).limit(page_size).all()

    items: List[TransactionResponse] = []
    for c in rows:
        canonical_type = normalize_transaction_type(getattr(c, "transaction_type", None))
        source_val = normalize_source_type(getattr(c, "added_via", None) or getattr(c, "source", None))
        amount_val = normalize_amount_for_response(getattr(c, "amount", Decimal("0")))

        items.append(TransactionResponse(
            id=c.id,
            transaction_date=c.datetime,
            amount=amount_val,
            currency=c.currency,
            card_last_4=c.card_last4,
            operator_raw=c.operator,
            application_mapped=c.app,
            transaction_type=canonical_type,
            balance_after=str(c.balance) if c.balance is not None else None,
            source_type=source_val,
            parsing_method=getattr(c, "added_via", None),
            parsing_confidence=None,
            is_p2p=c.is_p2p,
            created_at=c.created_at,
            updated_at=getattr(c, "updated_at", None),
            raw_message=getattr(c, "raw_text", None)
        ))

    return TransactionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items
    )


@router.post("/", response_model=TransactionResponse)
async def create_transaction(
    payload: TransactionCreateRequest,
    db: Session = Depends(get_db_session)
):
    """
    Manually create a new transaction/check.
    """
    try:
        txn_type = normalize_transaction_type(payload.transaction_type)
        amount = Decimal(str(payload.amount))
        store_amount = -abs(amount) if txn_type == "DEBIT" else abs(amount)

        dt = payload.datetime
        weekday_label = compute_weekday_label(dt)
        date_display = compute_date_display(dt)
        time_display = compute_time_display(dt)

        check = Check(
            datetime=dt,
            weekday=weekday_label,
            date_display=date_display,
            time_display=time_display,
            operator=payload.operator,
            app=payload.app,
            amount=store_amount,
            balance=payload.balance,
            card_last4=payload.card_last4,
            is_p2p=payload.is_p2p or False,
            transaction_type=txn_type,
            currency=payload.currency,
            source="Manual",
            added_via="manual",
            raw_text=payload.raw_text,
        )

        db.add(check)
        db.commit()
        db.refresh(check)

        return TransactionResponse(
            id=check.id,
            transaction_date=check.datetime,
            amount=normalize_amount_for_response(check.amount),
            currency=check.currency,
            card_last_4=check.card_last4,
            operator_raw=check.operator,
            application_mapped=check.app,
            transaction_type=check.transaction_type,
            balance_after=str(check.balance) if check.balance is not None else None,
            source_type=normalize_source_type(check.added_via),
            parsing_method=check.added_via,
            parsing_confidence=None,
            is_p2p=check.is_p2p,
            created_at=check.created_at,
            updated_at=check.updated_at,
            raw_message=check.raw_text
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Create failed: {str(e)}")


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: int,
    db: Session = Depends(get_db_session)
):
    """Get single transaction by ID"""
    c = db.query(Check).filter(Check.id == transaction_id).first()

    if not c:
        raise HTTPException(status_code=404, detail="Transaction not found")

    canonical_type = normalize_transaction_type(getattr(c, "transaction_type", None))
    source_val = normalize_source_type(getattr(c, "added_via", None) or getattr(c, "source", None))
    amount_val = normalize_amount_for_response(getattr(c, "amount", Decimal("0")))

    return TransactionResponse(
        id=c.id,
        transaction_date=c.datetime,
        amount=amount_val,
        currency=c.currency,
        card_last_4=c.card_last4,
        operator_raw=c.operator,
        application_mapped=c.app,
        transaction_type=canonical_type,
        balance_after=str(c.balance) if c.balance is not None else None,
        source_type=source_val,
        parsing_method=getattr(c, "added_via", None),
        parsing_confidence=None,
        is_p2p=c.is_p2p,
        created_at=c.created_at,
        updated_at=getattr(c, "updated_at", None),
        raw_message=getattr(c, "raw_text", None)
    )


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
        c = db.query(Check).filter(Check.id == transaction_id).first()

        if not c:
            raise HTTPException(status_code=404, detail=f"Transaction {transaction_id} not found")

        update_dict = update_data.model_dump(exclude_unset=True)

        # Normalize transaction type
        if "transaction_type" in update_dict:
            c.transaction_type = normalize_transaction_type(update_dict["transaction_type"])

        # Normalize source_type -> added_via
        if "source_type" in update_dict and update_dict["source_type"]:
            src = update_dict["source_type"]
            c.added_via = "bot" if src == "AUTO" else "manual"

        if "transaction_date" in update_dict:
            c.datetime = update_dict["transaction_date"]

        if "operator_raw" in update_dict:
            c.operator = update_dict["operator_raw"]

        if "application_mapped" in update_dict:
            c.app = update_dict["application_mapped"]

        if "currency" in update_dict:
            c.currency = update_dict["currency"]

        if "card_last_4" in update_dict:
            c.card_last4 = update_dict["card_last_4"]

        if "is_p2p" in update_dict:
            c.is_p2p = update_dict["is_p2p"]

        if "balance_after" in update_dict:
            c.balance = update_dict["balance_after"]

        # Amount normalization: store debits as negative, credits/etc as positive
        if "amount" in update_dict:
            amt = Decimal(str(update_dict["amount"]))
            txn_type = c.transaction_type or normalize_transaction_type(None)
            store_amount = -abs(amt) if txn_type == "DEBIT" else abs(amt)
            c.amount = store_amount

        c.updated_at = func.now()

        db.commit()
        db.refresh(transaction)

        return TransactionUpdateResponse(
            success=True,
            message="Transaction updated successfully",
            transaction=TransactionResponse(
                id=c.id,
                transaction_date=c.datetime,
                amount=normalize_amount_for_response(c.amount),
                currency=c.currency,
                card_last_4=c.card_last4,
                operator_raw=c.operator,
                application_mapped=c.app,
                transaction_type=c.transaction_type,
                balance_after=str(c.balance) if c.balance is not None else None,
                source_type=normalize_source_type(c.added_via),
                parsing_method=c.added_via,
                parsing_confidence=None,
                is_p2p=c.is_p2p,
                created_at=c.created_at,
                updated_at=c.updated_at,
                raw_message=c.raw_text
            )
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


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


@router.post("/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_transactions(
    request: BulkDeleteRequest,
    db: Session = Depends(get_db_session)
):
    """
    Delete multiple transactions at once
    """
    try:
        ids = request.ids
        existing_ids = set(id_ for (id_,) in db.query(Check.id).filter(Check.id.in_(ids)).all())
        failed_ids = [i for i in ids if i not in existing_ids]

        deleted_count = db.query(Check).filter(Check.id.in_(existing_ids)).delete(synchronize_session=False)
        db.commit()

        return BulkDeleteResponse(
            success=len(failed_ids) == 0,
            deleted_count=deleted_count,
            failed_ids=failed_ids,
            errors=[f"ID {fid} not found" for fid in failed_ids]
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Bulk delete failed: {str(e)}")
