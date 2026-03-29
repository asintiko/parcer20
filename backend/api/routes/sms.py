"""Mobile SMS ingestion API."""
from __future__ import annotations

import os
import time
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pytz
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.dependencies import require_mobile_ingest_key
from database.connection import get_db_session
from database.models import Transaction
from parsers.parser_orchestrator import ParserOrchestrator
from services.access_control_service import write_audit_log
from services.auth_bot_service import get_redis
from services.fingerprint import compute_fingerprint_candidates

router = APIRouter(
    prefix="/api/sms",
    tags=["sms"],
    dependencies=[Depends(require_mobile_ingest_key)],
)


class SmsMessage(BaseModel):
    device_sms_id: str = Field(..., max_length=128)
    sender: str = Field(..., max_length=64)
    text: str = Field(..., min_length=1, max_length=4096)
    received_at: datetime
    sim_slot: Optional[int] = None


class SmsIngestRequest(BaseModel):
    device_id: Optional[str] = Field(default="", max_length=128)
    messages: List[SmsMessage] = Field(..., min_length=1, max_length=50)


class SmsIngestResultItem(BaseModel):
    device_sms_id: str
    status: str  # created | duplicate | skipped | parse_error
    transaction_id: Optional[int] = None
    fingerprint: Optional[str] = None
    error: Optional[str] = None


class SmsIngestResponse(BaseModel):
    processed: int
    created: int
    duplicates: int
    skipped: int
    errors: int
    results: List[SmsIngestResultItem]


class SmsHealthResponse(BaseModel):
    status: str
    db: str
    version: str
    server_time: str


ALLOWED_TRANSACTION_TYPES = {"DEBIT", "CREDIT", "CONVERSION", "REVERSAL"}
ALLOWED_PARSING_METHODS = {
    "REGEX_HUMO",
    "REGEX_SMS",
    "REGEX_SEMICOLON",
    "REGEX_CARDXABAR",
    "REGEX_TRANSFER",
    "GPT",
    "GPT_VISION",
}


def _ingest_rate_limit_per_min() -> int:
    return max(1, int(os.getenv("MOBILE_SMS_INGEST_RATE_LIMIT_PER_MIN", "10")))


def _ingest_max_batch() -> int:
    return min(50, max(1, int(os.getenv("MOBILE_SMS_INGEST_MAX_BATCH", "50"))))


def _request_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _app_timezone() -> pytz.BaseTzInfo:
    name = (os.getenv("APP_TIMEZONE", "Asia/Tashkent") or "Asia/Tashkent").strip()
    if not name:
        name = "Asia/Tashkent"
    try:
        return pytz.timezone(name)
    except Exception:
        return pytz.timezone("Asia/Tashkent")


def _normalize_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except Exception:
            return None
    if not isinstance(value, datetime):
        return None

    tz = _app_timezone()
    if value.tzinfo:
        value = value.astimezone(tz)
    else:
        value = tz.localize(value)
    return value.replace(tzinfo=None)


def _normalize_amount(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _normalize_card_last4(value: Any) -> Optional[str]:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if not digits:
        return None
    return digits[-4:].zfill(4)


def _infer_transaction_type(raw_type: Any, raw_text: Optional[str]) -> str:
    combined_upper = " ".join(part for part in [str(raw_type or ""), raw_text or ""] if part).upper()

    if any(keyword in combined_upper for keyword in {"REVERSAL", "ОТМЕНА", "OTMENA", "CANCEL"}):
        return "REVERSAL"
    if any(keyword in combined_upper for keyword in {"CONVERSION", "КОНВЕРСИЯ", "KONVERSIY", "KONVERS"}):
        return "CONVERSION"

    sign_text = f"{raw_type or ''} {raw_text or ''}"
    if "➕" in sign_text:
        return "CREDIT"
    if "➖" in sign_text:
        return "DEBIT"

    if any(keyword in combined_upper for keyword in {"CREDIT", "ПОПОЛНЕНИЕ", "POPOLNENIE", "KIRIM", "ПОСТУПЛЕНИЕ", "POSTUPLENIE"}):
        return "CREDIT"

    if any(keyword in combined_upper for keyword in {"DEBIT", "СПИСАНИЕ", "SPISANIE", "ОПЛАТА", "OPLATA", "POKUPKA", "PLATEZH", "E-COM"}):
        return "DEBIT"

    return "DEBIT"


def _normalize_parsing_method(value: Any) -> str:
    method = str(value or "").upper()
    if method in ALLOWED_PARSING_METHODS:
        return method
    return "REGEX_SMS"


def _normalize_confidence(value: Any) -> float:
    try:
        num = float(value)
    except Exception:
        return 0.0
    return max(0.0, min(1.0, num))


async def _enforce_sms_ingest_rate_limit(request: Request, db: Session, device_id: str) -> None:
    actor = (device_id or "").strip() or _request_ip(request)
    minute_slot = int(time.time() // 60)
    key = f"sms_ingest:rate:{actor}:{minute_slot}"

    try:
        redis = await get_redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 65)
        if int(count) > _ingest_rate_limit_per_min():
            write_audit_log(
                db,
                action="sms_ingest_rate_limited",
                success=False,
                ip_address=_request_ip(request),
                details={"device_id": device_id, "actor": actor, "count": int(count)},
            )
            raise HTTPException(status_code=429, detail="SMS ingest rate limit exceeded")
    except HTTPException:
        raise
    except Exception:
        try:
            write_audit_log(
                db,
                action="sms_ingest_rate_limit_error",
                success=False,
                ip_address=_request_ip(request),
                details={"device_id": device_id, "actor": actor, "reason": "redis_unavailable"},
            )
        except Exception:
            pass
        # Non-blocking fallback if Redis is temporarily unavailable.
        return


@router.get("/health", response_model=SmsHealthResponse)
async def sms_health(db: Session = Depends(get_db_session)) -> SmsHealthResponse:
    db_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    now_local = datetime.now(_app_timezone())
    return SmsHealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        db=db_status,
        version=os.getenv("APP_VERSION", "1.2.0"),
        server_time=now_local.replace(tzinfo=None).isoformat() + "Z",
    )


@router.post("/ingest", response_model=SmsIngestResponse)
async def ingest_sms(
    payload: SmsIngestRequest,
    request: Request,
    db: Session = Depends(get_db_session),
) -> SmsIngestResponse:
    max_batch = _ingest_max_batch()
    if len(payload.messages) > max_batch:
        raise HTTPException(status_code=422, detail=f"Maximum {max_batch} messages per request")

    await _enforce_sms_ingest_rate_limit(request, db, payload.device_id)
    orchestrator = ParserOrchestrator(db)

    results: List[SmsIngestResultItem] = []

    for msg in payload.messages:
        try:
            parsed = orchestrator.parse_text(msg.text)
        except Exception as exc:  # noqa: BLE001
            results.append(
                SmsIngestResultItem(
                    device_sms_id=msg.device_sms_id,
                    status="parse_error",
                    error=f"parser_error:{str(exc)[:180]}",
                )
            )
            continue

        if not parsed:
            results.append(
                SmsIngestResultItem(
                    device_sms_id=msg.device_sms_id,
                    status="skipped",
                    error="not_a_transaction",
                )
            )
            continue

        try:
            with db.begin_nested():
                transaction_date = _normalize_datetime(parsed.get("transaction_date"))
                amount = _normalize_amount(parsed.get("amount"))
                if transaction_date is None:
                    raise ValueError("missing_transaction_date")
                if amount is None:
                    raise ValueError("missing_amount")

                card_last4 = _normalize_card_last4(parsed.get("card_last_4") or parsed.get("card_last4"))
                txn_type = _infer_transaction_type(parsed.get("transaction_type"), msg.text)
                if txn_type not in ALLOWED_TRANSACTION_TYPES:
                    txn_type = "DEBIT"

                operator_raw = parsed.get("operator_raw") or parsed.get("operator")
                fp_candidates = compute_fingerprint_candidates(
                    amount=amount,
                    transaction_date=transaction_date,
                    card_last4=card_last4,
                    operator_raw=operator_raw,
                )
                fp = fp_candidates[0]
                existing = db.query(Transaction).filter(Transaction.fingerprint.in_(fp_candidates)).first()
                if existing:
                    results.append(
                        SmsIngestResultItem(
                            device_sms_id=msg.device_sms_id,
                            status="duplicate",
                            transaction_id=int(existing.id),
                            fingerprint=fp,
                        )
                    )
                    continue

                store_amount = -abs(amount) if txn_type == "DEBIT" else abs(amount)
                txn = Transaction(
                    raw_message=msg.text,
                    source_type="SMS",
                    source_chat_id=0,
                    source_message_id=None,
                    transaction_date=transaction_date,
                    amount=store_amount,
                    currency=str(parsed.get("currency") or "UZS")[:3].upper(),
                    card_last_4=card_last4,
                    operator_raw=operator_raw,
                    application_mapped=parsed.get("application_mapped") or parsed.get("application"),
                    transaction_type=txn_type,
                    balance_after=_normalize_amount(parsed.get("balance_after")),
                    receiver_name=(parsed.get("receiver_name") or None),
                    receiver_card=(parsed.get("receiver_card") or None),
                    is_p2p=bool(parsed.get("is_p2p") or False),
                    parsing_method=_normalize_parsing_method(parsed.get("parsing_method")),
                    parsing_confidence=_normalize_confidence(parsed.get("parsing_confidence")),
                    fingerprint=fp,
                )
                db.add(txn)
                db.flush()

                results.append(
                    SmsIngestResultItem(
                        device_sms_id=msg.device_sms_id,
                        status="created",
                        transaction_id=int(txn.id),
                        fingerprint=fp,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            results.append(
                SmsIngestResultItem(
                    device_sms_id=msg.device_sms_id,
                    status="parse_error",
                    error=f"ingest_error:{str(exc)[:180]}",
                )
            )

    db.commit()

    created = sum(1 for item in results if item.status == "created")
    duplicates = sum(1 for item in results if item.status == "duplicate")
    skipped = sum(1 for item in results if item.status == "skipped")
    errors = sum(1 for item in results if item.status == "parse_error")

    try:
        write_audit_log(
            db,
            action="sms_ingest",
            success=True,
            ip_address=_request_ip(request),
            details={
                "device_id": (payload.device_id or "").strip(),
                "processed": len(results),
                "created": created,
                "duplicates": duplicates,
                "skipped": skipped,
                "errors": errors,
                "ip": _request_ip(request),
            },
        )
    except Exception:
        # Audit write failure must not break ingest response.
        pass

    return SmsIngestResponse(
        processed=len(results),
        created=created,
        duplicates=duplicates,
        skipped=skipped,
        errors=errors,
        results=results,
    )
