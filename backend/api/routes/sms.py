"""Mobile SMS ingestion API."""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import time
from functools import lru_cache
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pytz
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, func, text
from sqlalchemy.orm import Session

from database import connection as database_connection
from database.connection import get_db_session
from database.models import DuplicateSuggestion, Transaction
from parsers.parser_orchestrator import ParserOrchestrator
from services import receipt_logger
from services.access_control_service import write_audit_log
from services.auth_bot_service import get_redis
from services.fingerprint import compute_fingerprint_candidates

router = APIRouter(
    prefix="/api/sms",
    tags=["sms"],
)

# In-process fallback rate-limit state, used only when Redis is unavailable so
# the endpoint never fails fully open. Keyed by "actor:minute_slot". Bounded by
# opportunistic cleanup of stale slots.
_FALLBACK_RATE: Dict[str, int] = {}
_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _normalize_device_id(value: str) -> str:
    candidate = str(value or "")
    if candidate != candidate.strip() or not _DEVICE_ID_RE.fullmatch(candidate):
        raise ValueError("Invalid mobile device id")
    return candidate


@lru_cache(maxsize=4)
def _parse_mobile_device_keys(raw_config: str) -> Dict[str, tuple[str, ...]]:
    """Parse fail-closed per-device current/previous keys from environment JSON."""
    if not raw_config.strip():
        raise ValueError("MOBILE_DEVICE_KEYS_JSON is not configured")
    try:
        payload = json.loads(raw_config)
    except json.JSONDecodeError as exc:
        raise ValueError("MOBILE_DEVICE_KEYS_JSON is invalid JSON") from exc
    if not isinstance(payload, dict) or not payload:
        raise ValueError("MOBILE_DEVICE_KEYS_JSON must be a non-empty object")

    parsed: Dict[str, tuple[str, ...]] = {}
    for raw_device_id, entry in payload.items():
        device_id = _normalize_device_id(raw_device_id)
        if device_id != raw_device_id:
            raise ValueError("MOBILE_DEVICE_KEYS_JSON contains a non-canonical device id")

        if isinstance(entry, str):
            current = entry
            previous: List[str] = []
        elif isinstance(entry, dict) and set(entry).issubset({"current", "previous"}):
            current = entry.get("current")
            raw_previous = entry.get("previous", [])
            if isinstance(raw_previous, str):
                previous = [raw_previous]
            elif isinstance(raw_previous, list) and all(isinstance(item, str) for item in raw_previous):
                previous = raw_previous
            else:
                raise ValueError("Mobile previous keys must be a string or list of strings")
        else:
            raise ValueError("Each mobile device must define current and optional previous keys")

        keys = [current, *previous]
        if not all(isinstance(key, str) and len(key) >= 32 and key == key.strip() for key in keys):
            raise ValueError("Mobile device keys must be canonical strings of at least 32 characters")
        unique_keys = tuple(dict.fromkeys(keys))
        parsed[device_id] = unique_keys
    return parsed


async def _require_mobile_device(
    device_id: Optional[str] = Header(default=None, alias="X-Mobile-Device-Id"),
    ingest_key: Optional[str] = Header(default=None, alias="X-Mobile-Ingest-Key"),
) -> str:
    try:
        canonical_device_id = _normalize_device_id(device_id or "")
        device_keys = _parse_mobile_device_keys(os.getenv("MOBILE_DEVICE_KEYS_JSON", ""))
    except ValueError as exc:
        if not os.getenv("MOBILE_DEVICE_KEYS_JSON", "").strip():
            raise HTTPException(status_code=503, detail="Mobile device authentication is not configured") from exc
        if not device_id or not _DEVICE_ID_RE.fullmatch(str(device_id)):
            raise HTTPException(status_code=403, detail="Invalid mobile device credentials") from exc
        raise HTTPException(status_code=503, detail="Mobile device authentication configuration is invalid") from exc

    supplied_key = ingest_key or ""
    candidates = device_keys.get(canonical_device_id, ("0" * 32,))
    matched = False
    for candidate in candidates:
        matched = secrets.compare_digest(supplied_key, candidate) or matched
    if not matched:
        raise HTTPException(status_code=403, detail="Invalid mobile device credentials")
    return canonical_device_id


def _fallback_rate_check(key: str, limit: int) -> bool:
    """Return True if allowed under the in-process limiter, False if exceeded."""
    # Drop stale minute-slot keys (slot is the trailing ":<int>" segment).
    current_slot = int(time.time() // 60)
    for k in list(_FALLBACK_RATE.keys()):
        try:
            if int(k.rsplit(":", 1)[1]) < current_slot:
                _FALLBACK_RATE.pop(k, None)
        except (ValueError, IndexError):
            _FALLBACK_RATE.pop(k, None)
    count = _FALLBACK_RATE.get(key, 0) + 1
    _FALLBACK_RATE[key] = count
    return count <= limit


class SmsMessage(BaseModel):
    device_sms_id: str = Field(..., max_length=128)
    sender: str = Field(..., max_length=64)
    text: str = Field(..., min_length=1, max_length=4096)
    received_at: datetime
    sim_slot: Optional[int] = None


class SmsIngestRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=128)
    messages: List[SmsMessage] = Field(..., min_length=1, max_length=50)


class SmsParsedSummary(BaseModel):
    amount: Optional[str] = None
    direction: Optional[str] = None
    currency: Optional[str] = None
    transaction_date: Optional[str] = None
    card_last_4: Optional[str] = None
    operator: Optional[str] = None
    transaction_type: Optional[str] = None
    balance_after: Optional[str] = None
    application: Optional[str] = None


class SmsIngestResultItem(BaseModel):
    device_sms_id: str
    status: str  # created | duplicate | skipped | parse_error
    transaction_id: Optional[int] = None
    fingerprint: Optional[str] = None
    error: Optional[str] = None
    parsed: Optional[SmsParsedSummary] = None


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


class SmsStatsSourceRow(BaseModel):
    source: str  # SMS | TELEGRAM | MANUAL
    count: int
    volume: str


class SmsStatsCardRow(BaseModel):
    card_last_4: str
    count: int
    volume: str


class SmsStatsResponse(BaseModel):
    currency: str
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    total_volume: str
    debit_volume: str
    credit_volume: str
    transaction_count: int
    debit_count: int
    credit_count: int
    by_source: List[SmsStatsSourceRow]
    by_card: List[SmsStatsCardRow]


class SmsSourceItem(BaseModel):
    chat_id: int
    title: Optional[str] = None
    count: int


class SmsSourcesResponse(BaseModel):
    items: List[SmsSourceItem]


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


def _parse_sms_in_worker(text_value: str, received_at: datetime) -> Optional[Dict[str, Any]]:
    """Keep parser/AI work off the API event loop and DB sessions thread-local."""
    with database_connection.SessionLocal() as parser_db:
        return ParserOrchestrator(parser_db).parse_text(
            text_value,
            fallback_datetime=received_at,
        )


async def _enforce_sms_ingest_rate_limit(request: Request, db: Session, device_id: str) -> None:
    actor = f"{device_id}:{_request_ip(request)}"
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
        # Redis down: fall back to an in-process limiter instead of failing open,
        # so a Redis blip can't remove the throttle entirely.
        if not _fallback_rate_check(key, _ingest_rate_limit_per_min()):
            raise HTTPException(status_code=429, detail="SMS ingest rate limit exceeded")
        return


@router.get("/health", response_model=SmsHealthResponse)
async def sms_health(
    _authenticated_device_id: str = Depends(_require_mobile_device),
    db: Session = Depends(get_db_session),
) -> SmsHealthResponse:
    db_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    now_local = datetime.now(_app_timezone())
    return SmsHealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        db=db_status,
        version=os.getenv("APP_VERSION", "1.4.24"),
        server_time=now_local.replace(tzinfo=None).isoformat() + "Z",
    )


@router.post("/ingest", response_model=SmsIngestResponse)
async def ingest_sms(
    payload: SmsIngestRequest,
    request: Request,
    authenticated_device_id: str = Depends(_require_mobile_device),
    db: Session = Depends(get_db_session),
) -> SmsIngestResponse:
    if payload.device_id != authenticated_device_id:
        raise HTTPException(status_code=403, detail="Body device_id does not match authenticated device")
    max_batch = _ingest_max_batch()
    if len(payload.messages) > max_batch:
        raise HTTPException(status_code=422, detail=f"Maximum {max_batch} messages per request")

    await _enforce_sms_ingest_rate_limit(request, db, authenticated_device_id)
    results: List[SmsIngestResultItem] = []
    log_events: List[Dict[str, Any]] = []
    src_device_id = authenticated_device_id

    for msg in payload.messages:
        # Idempotency by (device_id, device_sms_id): a re-sent batch (network
        # retry, WorkManager replay) must not create a second transaction, and a
        # forged fingerprint can no longer suppress a genuine SMS — each device
        # message is unique by its own id regardless of fingerprint collisions.
        src_sms_id = (msg.device_sms_id or "").strip() or None
        if src_sms_id is not None:
            dup_q = db.query(Transaction).filter(Transaction.source_device_sms_id == src_sms_id)
            dup_q = (
                dup_q.filter(Transaction.source_device_id.is_(None))
                if src_device_id is None
                else dup_q.filter(Transaction.source_device_id == src_device_id)
            )
            prior = dup_q.first()
            if prior is not None:
                results.append(
                    SmsIngestResultItem(
                        device_sms_id=msg.device_sms_id,
                        status="duplicate",
                        transaction_id=int(prior.id),
                        fingerprint=prior.fingerprint,
                        parsed=_summary_from_txn(prior),
                    )
                )
                log_events.append({"kind": "duplicate", "txn": prior})
                continue

        try:
            parsed = await asyncio.to_thread(_parse_sms_in_worker, msg.text, msg.received_at)
        except Exception as exc:  # noqa: BLE001
            results.append(
                SmsIngestResultItem(
                    device_sms_id=msg.device_sms_id,
                    status="parse_error",
                    error=f"parser_error:{str(exc)[:180]}",
                )
            )
            log_events.append({"kind": "failed", "reason": str(exc), "text": msg.text})
            continue

        if not parsed:
            results.append(
                SmsIngestResultItem(
                    device_sms_id=msg.device_sms_id,
                    status="skipped",
                    error="not_a_transaction",
                )
            )
            log_events.append({"kind": "failed", "reason": "not_a_transaction", "text": msg.text})
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
                    transaction_type=txn_type,
                )
                fp = fp_candidates[0]
                fingerprint_candidate = (
                    db.query(Transaction)
                    .filter(Transaction.fingerprint.in_(fp_candidates))
                    .filter(func.upper(func.coalesce(Transaction.source_type, "")) != "SMS")
                    .order_by(Transaction.id.asc())
                    .first()
                )
                store_amount = -abs(amount) if txn_type == "DEBIT" else abs(amount)
                txn = Transaction(
                    raw_message=msg.text,
                    source_type="SMS",
                    source_chat_id=0,
                    source_message_id=None,
                    source_device_id=src_device_id,
                    source_device_sms_id=src_sms_id,
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
                if fingerprint_candidate is not None:
                    db.add(
                        DuplicateSuggestion(
                            task_id=None,
                            primary_transaction_id=int(fingerprint_candidate.id),
                            duplicate_transaction_id=int(txn.id),
                            confidence=0.6,
                            reasoning="fuzzy_fingerprint_match_requires_review",
                            payload_json=json.dumps(
                                {"fingerprint": fp, "candidates": fp_candidates},
                                ensure_ascii=False,
                            ),
                        )
                    )

                results.append(
                    SmsIngestResultItem(
                        device_sms_id=msg.device_sms_id,
                        status="created",
                        transaction_id=int(txn.id),
                        fingerprint=fp,
                        parsed=_summary_from_txn(txn),
                    )
                )
                log_events.append({"kind": "created", "txn": txn})
        except Exception as exc:  # noqa: BLE001
            results.append(
                SmsIngestResultItem(
                    device_sms_id=msg.device_sms_id,
                    status="parse_error",
                    error=f"ingest_error:{str(exc)[:180]}",
                )
            )
            log_events.append({"kind": "failed", "reason": str(exc), "text": msg.text})

    db.commit()

    device_marker = (payload.device_id or "").strip() or "unknown"
    SMS_CHAT_TITLE = "📱 SMS (mobile)"
    for ev in log_events:
        try:
            kind = ev["kind"]
            if kind in ("created", "duplicate"):
                t = ev["txn"]
                if kind == "created":
                    receipt_logger.log_processed(
                        task_id=None,
                        transaction_id=int(t.id),
                        chat_id=0,
                        chat_title=SMS_CHAT_TITLE,
                        message_id=None,
                        amount=t.amount,
                        currency=t.currency or "UZS",
                        transaction_date=t.transaction_date,
                        operator=t.operator_raw,
                        receiver_name=t.receiver_name,
                        receiver_card=t.receiver_card,
                        sender_card=t.card_last_4,
                        parsing_method=t.parsing_method,
                        parsing_confidence=t.parsing_confidence,
                        is_p2p=bool(t.is_p2p),
                        ocr_preview=t.raw_message,
                        request_id=f"sms:{device_marker}",
                    )
                else:
                    receipt_logger.log_duplicate(
                        task_id=None,
                        transaction_id=int(t.id),
                        duplicate_of_id=int(t.id),
                        chat_id=0,
                        chat_title=SMS_CHAT_TITLE,
                        message_id=None,
                        amount=t.amount,
                        currency=t.currency or "UZS",
                        transaction_date=t.transaction_date,
                        operator=t.operator_raw,
                        request_id=f"sms:{device_marker}",
                    )
            else:
                receipt_logger.log_failed(
                    task_id=None,
                    chat_id=0,
                    chat_title=SMS_CHAT_TITLE,
                    message_id=None,
                    rejection_reason=ev.get("reason"),
                    error_summary=ev.get("reason"),
                    ocr_preview=ev.get("text"),
                    request_id=f"sms:{device_marker}",
                )
        except Exception:
            pass

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


def _summary_from_txn(txn: Transaction) -> SmsParsedSummary:
    ttype = (txn.transaction_type or "").upper()
    amt = txn.amount
    bal = txn.balance_after
    return SmsParsedSummary(
        amount=f"{abs(Decimal(str(amt))):.2f}" if amt is not None else None,
        direction="credit" if ttype == "CREDIT" else "debit",
        currency=txn.currency,
        transaction_date=txn.transaction_date.isoformat() if txn.transaction_date else None,
        card_last_4=txn.card_last_4,
        operator=txn.operator_raw,
        transaction_type=ttype or None,
        balance_after=f"{abs(Decimal(str(bal))):.2f}" if bal is not None else None,
        application=txn.application_mapped,
    )


def _source_label(source_type: Optional[str]) -> str:
    st = (source_type or "").upper()
    if st == "SMS":
        return "SMS"
    if st == "MANUAL":
        return "MANUAL"
    return "TELEGRAM"


@router.get("/stats", response_model=SmsStatsResponse)
async def sms_stats(
    authenticated_device_id: str = Depends(_require_mobile_device),
    db: Session = Depends(get_db_session),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    source: str = "all",
    source_chat_id: Optional[int] = None,
    card: Optional[str] = None,
    currency: str = "UZS",
) -> SmsStatsResponse:
    currency = (currency or "UZS").upper()[:3]
    base = db.query(Transaction).filter(
        Transaction.currency == currency,
        Transaction.source_type == "SMS",
        Transaction.source_device_id == authenticated_device_id,
    )

    nd_from = _normalize_datetime(date_from) if date_from is not None else None
    nd_to = _normalize_datetime(date_to) if date_to is not None else None
    if nd_from is not None:
        base = base.filter(Transaction.transaction_date >= nd_from)
    if nd_to is not None:
        base = base.filter(Transaction.transaction_date <= nd_to)

    src = (source or "all").lower()
    if src not in {"all", "sms"} or source_chat_id is not None:
        raise HTTPException(status_code=422, detail="Mobile stats are limited to the authenticated SMS device")

    card_norm = _normalize_card_last4(card) if card else None
    if card_norm:
        base = base.filter(Transaction.card_last_4 == card_norm)

    subq = base.with_entities(
        Transaction.id, Transaction.amount, Transaction.transaction_type,
        Transaction.source_type, Transaction.card_last_4,
    ).subquery()

    agg = db.query(
        func.coalesce(func.sum(func.abs(subq.c.amount)), 0),
        func.count(subq.c.id),
        func.coalesce(func.sum(case((subq.c.transaction_type == "DEBIT", 1), else_=0)), 0),
        func.coalesce(func.sum(case((subq.c.transaction_type == "CREDIT", 1), else_=0)), 0),
        func.coalesce(func.sum(case((subq.c.transaction_type == "DEBIT", func.abs(subq.c.amount)), else_=0)), 0),
        func.coalesce(func.sum(case((subq.c.transaction_type == "CREDIT", func.abs(subq.c.amount)), else_=0)), 0),
    ).one()
    total_volume, transaction_count, debit_count, credit_count, debit_volume, credit_volume = agg

    source_rows = (
        db.query(subq.c.source_type, func.count(subq.c.id), func.coalesce(func.sum(func.abs(subq.c.amount)), 0))
        .group_by(subq.c.source_type)
        .all()
    )
    by_source_acc: Dict[str, Dict[str, Any]] = {}
    for st, cnt, vol in source_rows:
        label = _source_label(st)
        acc = by_source_acc.setdefault(label, {"count": 0, "volume": Decimal(0)})
        acc["count"] += int(cnt)
        acc["volume"] += Decimal(str(vol or 0))
    by_source = [
        SmsStatsSourceRow(source=label, count=acc["count"], volume=f"{acc['volume']:.2f}")
        for label, acc in sorted(by_source_acc.items(), key=lambda kv: kv[1]["count"], reverse=True)
    ]

    card_rows = (
        db.query(subq.c.card_last_4, func.count(subq.c.id), func.coalesce(func.sum(func.abs(subq.c.amount)), 0))
        .filter(subq.c.card_last_4.isnot(None))
        .group_by(subq.c.card_last_4)
        .order_by(func.sum(func.abs(subq.c.amount)).desc())
        .limit(20)
        .all()
    )
    by_card = [
        SmsStatsCardRow(card_last_4=str(c4), count=int(cnt), volume=f"{Decimal(str(vol or 0)):.2f}")
        for c4, cnt, vol in card_rows
    ]

    return SmsStatsResponse(
        currency=currency,
        period_start=nd_from.isoformat() if nd_from else None,
        period_end=nd_to.isoformat() if nd_to else None,
        total_volume=f"{Decimal(str(total_volume)):.2f}",
        debit_volume=f"{Decimal(str(debit_volume)):.2f}",
        credit_volume=f"{Decimal(str(credit_volume)):.2f}",
        transaction_count=int(transaction_count),
        debit_count=int(debit_count),
        credit_count=int(credit_count),
        by_source=by_source,
        by_card=by_card,
    )


@router.get("/sources", response_model=SmsSourcesResponse)
async def sms_sources(
    _authenticated_device_id: str = Depends(_require_mobile_device),
) -> SmsSourcesResponse:
    return SmsSourcesResponse(items=[])
