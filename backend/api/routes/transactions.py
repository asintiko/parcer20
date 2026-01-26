"""
Transaction API routes
Server-side pagination, sorting, and filtering for financial transactions
"""
import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

import pytz
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc, extract, func
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from database.connection import get_db_session
from database.models import Transaction, Check
from services.telegram_tdlib_manager import TelegramTDLibManager, get_tdlib_manager
from services.receipt_processor import process_tdlib_message
from api.dependencies import get_current_user

# Normalization helpers
EMOJI_PATTERN = re.compile(r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF]")

SOURCE_DISPLAY_MAP = {
    "TELEGRAM": "Телеграм",
    "SMS": "СМС",
    "MANUAL": "Ручной",
}

TRANSACTION_TYPE_DISPLAY_MAP = {
    "DEBIT": "Списание",
    "CREDIT": "Пополнение",
    "CONVERSION": "Конверсия",
    "REVERSAL": "Отмена",
}


def normalize_source_type(source_type: Optional[str]) -> str:
    """
    Normalize source type to AUTO|MANUAL.
    """
    if not source_type:
        return "MANUAL"
    value = source_type.strip().upper()
    return "AUTO" if value == "AUTO" else "MANUAL"


def detect_source_channel(source_type: Optional[str], raw_text: Optional[str]) -> str:
    """
    Determine source channel for UI: TELEGRAM, SMS, or MANUAL.
    """
    if source_type:
        st = source_type.upper()
        if st == "MANUAL":
            return "MANUAL"
        if st in ("AUTO", "TELEGRAM", "USERBOT", "BOT", "AUTO"):
            return "TELEGRAM"
    if raw_text and EMOJI_PATTERN.search(raw_text):
        return "TELEGRAM"
    return "SMS"


def infer_transaction_type(raw_type: Optional[str], raw_text: Optional[str]) -> str:
    """
    Infer canonical transaction type using raw type and text with priority:
    REVERSAL > CONVERSION > explicit sign > keyword mapping > fallback DEBIT.
    """
    combined_upper = " ".join(
        part for part in [raw_type or "", raw_text or ""] if part
    ).upper()

    reversal_keywords = {"REVERSAL", "ОТМЕНА", "OTMENA", "CANCEL"}
    if any(keyword in combined_upper for keyword in reversal_keywords):
        return "REVERSAL"

    conversion_keywords = {"CONVERSION", "КОНВЕРСИЯ", "KONVERSIY", "KONVERS"}
    if any(keyword in combined_upper for keyword in conversion_keywords):
        return "CONVERSION"

    sign_text = f"{raw_type or ''} {raw_text or ''}"
    if "➕" in sign_text:
        return "CREDIT"
    if "➖" in sign_text:
        return "DEBIT"

    credit_keywords = {
        "CREDIT",
        "ПОПОЛНЕНИЕ",
        "POPOLNENIE",
        "KIRIM",
        "ПОСТУПЛЕНИЕ",
        "POSTUPLENIE",
    }
    if any(keyword in combined_upper for keyword in credit_keywords):
        return "CREDIT"

    debit_keywords = {
        "DEBIT",
        "СПИСАНИЕ",
        "SPISANIE",
        "ОПЛАТА",
        "OPLATA",
        "POKUPKA",
        "PLATEZH",
        "E-COM",
    }
    if any(keyword in combined_upper for keyword in debit_keywords):
        return "DEBIT"

    return "DEBIT"


def normalize_transaction_type(raw: Optional[str], raw_text: Optional[str] = None) -> str:
    """
    Map Russian / legacy transaction types to canonical enums using inference helper.
    """
    return infer_transaction_type(raw, raw_text)


def normalize_amount_for_response(amount: Decimal) -> str:
    """
    Present amount as positive string for UI
    """
    return f"{abs(Decimal(amount))}"


def normalize_optional_amount_for_response(amount: Optional[Decimal]) -> Optional[str]:
    """
    Present optional amount as positive string for UI
    """
    if amount is None:
        return None
    return normalize_amount_for_response(amount)


def compute_weekday_label(dt: datetime) -> str:
    weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    return weekdays[dt.weekday()]


def compute_date_display(dt: datetime) -> str:
    months = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
    return f"{dt.day} {months[dt.month - 1]}"


def compute_time_display(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def get_source_display(channel: str) -> str:
    return SOURCE_DISPLAY_MAP.get(channel, SOURCE_DISPLAY_MAP["SMS"])


def get_transaction_type_display(tx_type: str) -> str:
    return TRANSACTION_TYPE_DISPLAY_MAP.get(tx_type, TRANSACTION_TYPE_DISPLAY_MAP["DEBIT"])

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
    transaction_type_display: str
    balance_after: Optional[str]
    source_type: str
    source_channel: str
    source_display: str
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


class ProcessReceiptRequest(BaseModel):
    chat_id: int
    message_id: int
    force: bool = False


class ParsingInfo(BaseModel):
    method: Optional[str] = None
    confidence: Optional[float] = None
    notes: Optional[str] = None


class ProcessReceiptResponse(BaseModel):
    created: bool
    duplicate: bool
    transaction: TransactionResponse
    parsing: ParsingInfo


class ProcessReceiptBatchRequest(BaseModel):
    chat_id: int
    message_ids: List[int]
    force: bool = False


class ProcessReceiptBatchItem(BaseModel):
    message_id: int
    success: bool
    error: Optional[str] = None
    created: Optional[bool] = None
    duplicate: Optional[bool] = None
    transaction: Optional[TransactionResponse] = None
    parsing: Optional[ParsingInfo] = None


class ProcessReceiptBatchResponse(BaseModel):
    results: List[ProcessReceiptBatchItem]


class ProcessedStatusResponse(BaseModel):
    statuses: Dict[int, bool]


def build_transaction_response(c: Transaction) -> TransactionResponse:
    parsing_method = getattr(c, "parsing_method", None)
    parsing_confidence = getattr(c, "parsing_confidence", None)
    is_gpt_parsed = getattr(c, "is_gpt_parsed", None)
    metadata_json = getattr(c, "metadata_json", None) or getattr(c, "metadata", None) if hasattr(c, "metadata") else None
    if metadata_json:
        try:
            meta = json.loads(metadata_json)
            parsing_method = meta.get("parsing_method", parsing_method)
            parsing_confidence = meta.get("parsing_confidence", parsing_confidence)
            is_gpt_parsed = meta.get("is_gpt_parsed", is_gpt_parsed)
        except Exception:
            pass

    raw_message = getattr(c, "raw_message", None) or getattr(c, "raw_text", None)
    tx_date = getattr(c, "transaction_date", None) or getattr(c, "datetime", None)
    amount_val = getattr(c, "amount", Decimal("0"))
    card4 = getattr(c, "card_last_4", None) or getattr(c, "card_last4", None)
    operator_raw = getattr(c, "operator_raw", None) or getattr(c, "operator", None)
    app_mapped = getattr(c, "application_mapped", None) or getattr(c, "app", None)
    balance_val = getattr(c, "balance_after", None) or getattr(c, "balance", None)
    source_type_raw = getattr(c, "source_type", None)
    if not source_type_raw:
        added_via = getattr(c, "added_via", "") or ""
        source_type_raw = "AUTO" if added_via.lower() != "manual" else "MANUAL"

    canonical_type = infer_transaction_type(
        getattr(c, "transaction_type", None),
        raw_message
    )
    source_type_val = normalize_source_type(source_type_raw)
    source_channel = detect_source_channel(
        source_type_raw,
        raw_message
    )

    return TransactionResponse(
        id=c.id,
        transaction_date=tx_date,
        amount=normalize_amount_for_response(amount_val),
        currency=getattr(c, "currency", "UZS"),
        card_last_4=card4,
        operator_raw=operator_raw,
        application_mapped=app_mapped,
        transaction_type=canonical_type,
        transaction_type_display=get_transaction_type_display(canonical_type),
        balance_after=normalize_optional_amount_for_response(balance_val),
        source_type=source_type_val,
        source_channel=source_channel,
        source_display=get_source_display(source_channel),
        parsing_method=parsing_method,
        parsing_confidence=parsing_confidence,
        is_p2p=getattr(c, "is_p2p", None),
        created_at=getattr(c, "created_at", None),
        updated_at=getattr(c, "updated_at", None),
        raw_message=raw_message
    )



@router.post("/process-receipt", response_model=ProcessReceiptResponse)
async def process_receipt_from_telegram(
    payload: ProcessReceiptRequest,
    db: Session = Depends(get_db_session),
    manager: TelegramTDLibManager = Depends(get_tdlib_manager),
    current_user: dict = Depends(get_current_user),
):
    """
    Process a Telegram message (chat_id, message_id) into a transaction.
    """
    return await process_tdlib_message(
        chat_id=payload.chat_id,
        message_id=payload.message_id,
        force=payload.force,
        db=db,
        manager=manager,
    )


@router.post("/process-receipt-batch", response_model=ProcessReceiptBatchResponse)
async def process_receipt_batch(
    payload: ProcessReceiptBatchRequest,
    db: Session = Depends(get_db_session),
    manager: TelegramTDLibManager = Depends(get_tdlib_manager),
    current_user: dict = Depends(get_current_user),
):
    results: List[ProcessReceiptBatchItem] = []
    for msg_id in payload.message_ids:
        try:
            res = await process_tdlib_message(
                chat_id=payload.chat_id,
                message_id=msg_id,
                force=payload.force,
                db=db,
                manager=manager,
            )
            results.append(
                ProcessReceiptBatchItem(
                    message_id=msg_id,
                    success=True,
                    created=res.created,
                    duplicate=res.duplicate,
                    transaction=res.transaction,
                    parsing=res.parsing,
                )
            )
        except HTTPException as exc:
            results.append(
                ProcessReceiptBatchItem(
                    message_id=msg_id,
                    success=False,
                    error=exc.detail if isinstance(exc.detail, str) else str(exc.detail),
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                ProcessReceiptBatchItem(
                    message_id=msg_id,
                    success=False,
                    error=str(exc),
                )
            )
    return ProcessReceiptBatchResponse(results=results)


@router.get("/processed-status", response_model=ProcessedStatusResponse)
async def get_processed_status(
    chat_id: int = Query(...),
    message_ids: str = Query(..., description="Comma-separated list of message IDs"),
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
):
    try:
        ids = [int(x) for x in message_ids.split(",") if x.strip().isdigit()]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid message_ids parameter")
    if not ids:
        return ProcessedStatusResponse(statuses={})

    rows = (
        db.query(Transaction.source_message_id)
        .filter(
            Transaction.source_chat_id == str(chat_id),
            Transaction.source_message_id.in_([str(i) for i in ids]),
        )
        .all()
    )
    found_ids = {int(r[0]) for r in rows}
    statuses = {mid: (mid in found_ids) for mid in ids}
    return ProcessedStatusResponse(statuses=statuses)


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
    datetime: datetime
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
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
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
            c = db.query(Transaction).filter(Transaction.id == item.id).first()
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
                c.transaction_type = infer_transaction_type(
                    fields["transaction_type"],
                    getattr(c, "raw_message", None)
                )

            if "source_type" in fields:
                src = fields["source_type"]
                c.added_via = "bot" if src == "AUTO" else "manual"

            if "transaction_date" in fields:
                c.transaction_date = fields["transaction_date"]

            if "operator_raw" in fields:
                c.operator_raw = fields["operator_raw"]

            if "application_mapped" in fields:
                c.application_mapped = fields["application_mapped"]

            if "currency" in fields:
                c.currency = fields["currency"]

            if "card_last_4" in fields:
                c.card_last_4 = fields["card_last_4"]

            if "is_p2p" in fields:
                c.is_p2p = fields["is_p2p"]

            if "balance_after" in fields:
                c.balance = fields["balance_after"]

            if "amount" in fields:
                amt = Decimal(str(fields["amount"]))
                txn_type = infer_transaction_type(
                    c.transaction_type,
                    getattr(c, "raw_message", None)
                )
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
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
):
    """
    Get paginated list of transactions (Transactions) with server-side filters and sorting.
    """
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
        query = query.filter(func.abs(Transaction.amount) >= amount_min)
    if amount_max is not None:
        query = query.filter(func.abs(Transaction.amount) <= amount_max)
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
        norm_type = normalize_transaction_type(transaction_type)
        query = query.filter(Transaction.transaction_type == norm_type)
    tx_type_list = _split_csv(transaction_types)
    if tx_type_list:
        norm_list = [normalize_transaction_type(t) for t in tx_type_list]
        query = query.filter(Transaction.transaction_type.in_(norm_list))
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
        "amount": func.abs(Transaction.amount),
        "created_at": Transaction.created_at,
        "parsing_confidence": Transaction.parsing_confidence,
        "updated_at": Transaction.updated_at,
    }
    sort_column = sort_map.get(sort_by, Transaction.transaction_date)
    order_fn = desc if sort_dir.lower() == "desc" else asc
    query = query.order_by(order_fn(sort_column), Transaction.id.desc())

    # Pagination
    offset = (page - 1) * page_size
    rows = query.offset(offset).limit(page_size).all()

    items: List[TransactionResponse] = [build_transaction_response(c) for c in rows]

    return TransactionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items
    )


@router.post("/", response_model=TransactionResponse)
async def create_transaction(
    payload: TransactionCreateRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
):
    """
    Manually create a new transaction/check.
    """
    try:
        txn_type = infer_transaction_type(payload.transaction_type, payload.raw_text)
        amount = Decimal(str(payload.amount))
        store_amount = -abs(amount) if txn_type == "DEBIT" else abs(amount)

        dt = payload.datetime

        # Generate raw_message from payload if not provided
        raw_message = payload.raw_text or f"{txn_type}\n{payload.operator}\nСумма: {amount} {payload.currency}\nКарта: *{payload.card_last4}"

        txn = Transaction(
            transaction_date=dt,
            operator_raw=payload.operator,
            application_mapped=payload.app,
            amount=store_amount,
            balance_after=payload.balance,
            card_last_4=payload.card_last4,
            is_p2p=payload.is_p2p or False,
            transaction_type=txn_type,
            currency=payload.currency,
            source_type="MANUAL",
            source_chat_id=0,  # 0 for manual transactions
            raw_message=raw_message,
            parsing_method="REGEX_SMS",  # Use valid parsing method
            parsing_confidence=None,
            is_gpt_parsed=False,
        )

        db.add(txn)
        db.commit()
        db.refresh(txn)

        # Auto-map application if not provided
        if not payload.app and txn.operator_raw:
            try:
                from parsers.operator_mapper import OperatorMapper
                mapper = OperatorMapper(db)
                match = mapper.map_operator_details(txn.operator_raw)
                if match and match.get("application_name"):
                    txn.application_mapped = match["application_name"]
                    if match.get("is_p2p") is not None:
                        txn.is_p2p = match["is_p2p"]
                    db.commit()
                    db.refresh(txn)
            except Exception as e:
                print(f"⚠️ Failed to auto-map operator: {e}")

        return build_transaction_response(txn)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Create failed: {str(e)}")


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: int,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
):
    """Get single transaction by ID"""
    tx = db.query(Transaction).filter(Transaction.id == transaction_id).first()

    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return build_transaction_response(tx)


@router.put("/{transaction_id}", response_model=TransactionUpdateResponse)
async def update_transaction(
    transaction_id: int,
    update_data: TransactionUpdateRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
):
    """
    Update a transaction by ID (partial updates supported).
    """
    try:
        c = db.query(Transaction).filter(Transaction.id == transaction_id).first()

        if not c:
            raise HTTPException(status_code=404, detail=f"Transaction {transaction_id} not found")

        update_dict = update_data.model_dump(exclude_unset=True)

        # Normalize transaction type
        if "transaction_type" in update_dict:
            c.transaction_type = infer_transaction_type(
                update_dict["transaction_type"],
                getattr(c, "raw_message", None)
            )

        if "source_type" in update_dict and update_dict["source_type"]:
            src = update_dict["source_type"]
            c.source_type = "AUTO" if src == "AUTO" else "MANUAL"

        if "transaction_date" in update_dict:
            c.transaction_date = update_dict["transaction_date"]

        if "operator_raw" in update_dict:
            c.operator_raw = update_dict["operator_raw"]

        if "application_mapped" in update_dict:
            c.application_mapped = update_dict["application_mapped"]

        if "currency" in update_dict:
            c.currency = update_dict["currency"]

        if "card_last_4" in update_dict:
            c.card_last_4 = update_dict["card_last_4"]

        if "is_p2p" in update_dict:
            c.is_p2p = update_dict["is_p2p"]

        if "balance_after" in update_dict:
            c.balance_after = update_dict["balance_after"]

        # Amount normalization: store debits as negative, credits/etc as positive
        if "amount" in update_dict:
            amt = Decimal(str(update_dict["amount"]))
            txn_type = infer_transaction_type(
                c.transaction_type,
                getattr(c, "raw_message", None)
            )
            store_amount = -abs(amt) if txn_type == "DEBIT" else abs(amt)
            c.amount = store_amount

        c.updated_at = func.now()

        db.commit()
        db.refresh(c)

        return TransactionUpdateResponse(
            success=True,
            message="Transaction updated successfully",
            transaction=build_transaction_response(c)
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
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
):
    """
    Delete a transaction by ID
    """
    try:
        check = db.query(Transaction).filter(Transaction.id == transaction_id).first()

        if not check:
            raise HTTPException(status_code=404, detail=f"Transaction {transaction_id} not found")

        db.delete(check)
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
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
):
    """
    Delete multiple transactions at once
    """
    try:
        ids = request.ids
        existing_ids = set(id_ for (id_,) in db.query(Transaction.id).filter(Transaction.id.in_(ids)).all())
        failed_ids = [i for i in ids if i not in existing_ids]

        deleted_count = db.query(Transaction).filter(Transaction.id.in_(existing_ids)).delete(synchronize_session=False)
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
