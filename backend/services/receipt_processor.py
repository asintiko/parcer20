"""Shared receipt processing logic for TDLib messages."""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

import pytz
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import AccessAuditLog, DuplicateMergeLog, TgChatMessage, Transaction
from parsers.parser_orchestrator import ParserOrchestrator
from parsers.pdf_extractor import (
    extract_text_from_image_path,
    extract_text_from_pdf,
)
from services.fingerprint import compute_fingerprint_candidates
from services.telegram_tdlib_manager import TDLibUnavailableError, TelegramTDLibManager
from database.connection import SessionLocal

if TYPE_CHECKING:
    # Avoid runtime circular import
    from api.routes.transactions import ProcessReceiptResponse

METHOD_QUALITY_BONUS = {
    "REGEX_TRANSFER": 18.0,
    "AI_TEXT": 14.0,
    "REGEX_HUMO": 12.0,
    "REGEX_CARDXABAR": 12.0,
    "REGEX_SMS": 10.0,
    "REGEX_SEMICOLON": 9.0,
}
DUPLICATE_LOG_BG_TIMEOUT_SEC = max(1.0, float(os.getenv("DUPLICATE_LOG_BG_TIMEOUT_SEC", "2.0")))
DUPLICATE_LOG_BG_RETRIES = max(0, int(os.getenv("DUPLICATE_LOG_BG_RETRIES", "2")))
logger = logging.getLogger(__name__)

def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized or normalized.upper() == "UNKNOWN":
            return False
        return True
    return True


def _value_richness(value: Any) -> int:
    if not _has_value(value):
        return 0
    if isinstance(value, str):
        return len(value.strip())
    return 1


def _method_bonus(parsing_method: Optional[str]) -> float:
    key = (parsing_method or "").upper()
    if key.startswith("GPT"):
        key = "AI_TEXT"
    return METHOD_QUALITY_BONUS.get(key, 0.0)


def _append_duplicate_log(
    *,
    fingerprint: str,
    existing_transaction_id: int,
    source_chat_id: Optional[int],
    source_message_id: Optional[int],
    merged: bool,
    candidate_method: Optional[str],
    candidate_confidence: Optional[float],
    existing_method: Optional[str],
    existing_confidence: Optional[float],
    details: Optional[Dict[str, Any]] = None,
) -> DuplicateMergeLog:
    row = DuplicateMergeLog(
        fingerprint=fingerprint,
        existing_transaction_id=int(existing_transaction_id),
        source_chat_id=int(source_chat_id) if source_chat_id is not None else None,
        source_message_id=int(source_message_id) if source_message_id is not None else None,
        merged=bool(merged),
        candidate_method=candidate_method,
        candidate_confidence=float(candidate_confidence) if candidate_confidence is not None else None,
        existing_method=existing_method,
        existing_confidence=float(existing_confidence or 0.0),
        details_json=json.dumps(details or {}, ensure_ascii=False) if details else None,
    )
    return row


def _persist_duplicate_log_row(row: DuplicateMergeLog) -> None:
    with SessionLocal() as bg_db:
        bg_db.add(row)
        bg_db.commit()


async def _append_duplicate_log_background(
    *,
    fingerprint: str,
    existing_transaction_id: int,
    source_chat_id: Optional[int],
    source_message_id: Optional[int],
    merged: bool,
    candidate_method: Optional[str],
    candidate_confidence: Optional[float],
    existing_method: Optional[str],
    existing_confidence: Optional[float],
    details: Optional[Dict[str, Any]] = None,
) -> None:
    last_error: Optional[Exception] = None
    for attempt in range(DUPLICATE_LOG_BG_RETRIES + 1):
        try:
            row = _append_duplicate_log(
                fingerprint=fingerprint,
                existing_transaction_id=existing_transaction_id,
                source_chat_id=source_chat_id,
                source_message_id=source_message_id,
                merged=merged,
                candidate_method=candidate_method,
                candidate_confidence=candidate_confidence,
                existing_method=existing_method,
                existing_confidence=existing_confidence,
                details=details,
            )
            await asyncio.wait_for(
                asyncio.to_thread(_persist_duplicate_log_row, row),
                timeout=DUPLICATE_LOG_BG_TIMEOUT_SEC,
            )
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < DUPLICATE_LOG_BG_RETRIES:
                await asyncio.sleep(min(0.2 * (attempt + 1), 0.75))
    logger.warning(
        "Failed to persist duplicate merge log after retries",
        exc_info=last_error,
    )


def _tx_quality_score(
    *,
    parsing_confidence: Optional[float],
    application_mapped: Optional[str],
    balance_after: Optional[Any],
    receiver_name: Optional[str],
    receiver_card: Optional[str],
    operator_raw: Optional[str],
    card_last4: Optional[str],
    parsing_method: Optional[str],
    transaction_date: Optional[datetime] = None,
) -> float:
    score = float(parsing_confidence or 0.0) * 100.0
    score += _method_bonus(parsing_method)
    score += 8.0 if _has_value(application_mapped) else 0.0
    score += 6.0 if _has_value(balance_after) else 0.0
    score += 6.0 if _has_value(receiver_name) else 0.0
    score += 6.0 if _has_value(receiver_card) else 0.0
    score += 4.0 if _has_value(operator_raw) else 0.0
    score += 3.0 if _has_value(card_last4) else 0.0
    if transaction_date is not None and int(getattr(transaction_date, "second", 0) or 0) != 0:
        score += 2.0
    if (parsing_method or "").upper().startswith("GPT"):
        score += 2.0
    return score


def _merge_duplicate_transaction(
    existing: Transaction,
    *,
    candidate_transaction_date: datetime,
    candidate_operator_raw: str,
    candidate_application_mapped: Optional[str],
    candidate_balance_after: Optional[Any],
    candidate_receiver_name: Optional[str],
    candidate_receiver_card: Optional[str],
    candidate_raw_message: str,
    candidate_is_p2p: Optional[bool],
    candidate_parsing_method: Optional[str],
    candidate_parsing_confidence: Optional[float],
    candidate_is_gpt: bool,
    candidate_source_type: Optional[str] = None,
) -> bool:
    existing_score = _tx_quality_score(
        parsing_confidence=getattr(existing, "parsing_confidence", None),
        application_mapped=getattr(existing, "application_mapped", None),
        balance_after=getattr(existing, "balance_after", None),
        receiver_name=getattr(existing, "receiver_name", None),
        receiver_card=getattr(existing, "receiver_card", None),
        operator_raw=getattr(existing, "operator_raw", None),
        card_last4=getattr(existing, "card_last_4", None),
        parsing_method=getattr(existing, "parsing_method", None),
        transaction_date=getattr(existing, "transaction_date", None),
    )
    candidate_score = _tx_quality_score(
        parsing_confidence=candidate_parsing_confidence,
        application_mapped=candidate_application_mapped,
        balance_after=candidate_balance_after,
        receiver_name=candidate_receiver_name,
        receiver_card=candidate_receiver_card,
        operator_raw=candidate_operator_raw,
        card_last4=getattr(existing, "card_last_4", None),
        parsing_method=candidate_parsing_method,
        transaction_date=candidate_transaction_date,
    )

    existing_conf = float(getattr(existing, "parsing_confidence", 0.0) or 0.0)
    candidate_conf = float(candidate_parsing_confidence or 0.0)
    candidate_is_better = candidate_score > (existing_score + 0.5)
    candidate_conf_is_better = candidate_conf >= existing_conf
    updated = False

    if _has_value(candidate_application_mapped) and (
        not _has_value(existing.application_mapped)
        or (_value_richness(candidate_application_mapped) > _value_richness(existing.application_mapped) and candidate_conf_is_better)
        or candidate_is_better
    ):
        existing.application_mapped = candidate_application_mapped
        updated = True
    if _has_value(candidate_balance_after) and (
        not _has_value(existing.balance_after)
        or (candidate_conf_is_better and candidate_is_better)
    ):
        existing.balance_after = candidate_balance_after
        updated = True
    if _has_value(candidate_receiver_name) and (
        not _has_value(existing.receiver_name)
        or (_value_richness(candidate_receiver_name) > _value_richness(existing.receiver_name) and candidate_conf_is_better)
        or candidate_is_better
    ):
        existing.receiver_name = candidate_receiver_name
        updated = True
    if _has_value(candidate_receiver_card) and (
        not _has_value(existing.receiver_card)
        or _value_richness(candidate_receiver_card) > _value_richness(existing.receiver_card)
        or candidate_is_better
    ):
        existing.receiver_card = candidate_receiver_card
        updated = True
    if _has_value(candidate_operator_raw) and (
        not _has_value(existing.operator_raw)
        or str(existing.operator_raw).upper() == "UNKNOWN"
        or (_value_richness(candidate_operator_raw) > _value_richness(existing.operator_raw) and candidate_conf_is_better)
        or candidate_is_better
    ):
        existing.operator_raw = candidate_operator_raw
        updated = True
    if candidate_is_p2p is not None and (existing.is_p2p is None or candidate_is_better):
        existing.is_p2p = candidate_is_p2p
        updated = True

    if candidate_transaction_date and not existing.transaction_date:
        existing.transaction_date = candidate_transaction_date
        updated = True
    elif candidate_transaction_date and existing.transaction_date:
        same_minute = existing.transaction_date.strftime("%Y-%m-%d %H:%M") == candidate_transaction_date.strftime("%Y-%m-%d %H:%M")
        better_second_precision = int(getattr(existing.transaction_date, "second", 0) or 0) == 0 and int(getattr(candidate_transaction_date, "second", 0) or 0) != 0
        if same_minute and (
            candidate_transaction_date.second != existing.transaction_date.second
            and (better_second_precision or candidate_is_better)
        ):
            existing.transaction_date = candidate_transaction_date
            updated = True

    if len(candidate_raw_message or "") > len(existing.raw_message or ""):
        existing.raw_message = candidate_raw_message
        updated = True

    if candidate_parsing_method and (not _has_value(existing.parsing_method) or candidate_is_better):
        existing.parsing_method = candidate_parsing_method
        updated = True

    if candidate_source_type:
        source_priority = {"MANUAL": 1, "SMS": 2, "AUTO": 3}
        current_source = str(getattr(existing, "source_type", "MANUAL") or "MANUAL").upper()
        candidate_source = str(candidate_source_type).upper()
        current_score = source_priority.get(current_source, 0)
        candidate_score = source_priority.get(candidate_source, 0)
        if candidate_score and (candidate_is_better or current_score == 0) and candidate_score >= current_score:
            existing.source_type = candidate_source
            updated = True

    existing.parsing_confidence = max(existing_conf, candidate_conf)
    existing.is_gpt_parsed = bool(existing.is_gpt_parsed or candidate_is_gpt)
    if updated:
        existing.updated_at = datetime.utcnow()
    return updated


def _parse_text_in_worker(
    text: str,
    fallback_datetime: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Run CPU/network-heavy parsing with a thread-local SQLAlchemy session."""
    with SessionLocal() as parser_db:
        return ParserOrchestrator(parser_db).process(text, fallback_datetime=fallback_datetime)


def _extract_and_parse_in_worker(
    path: str,
    *,
    caption: str,
    media_kind: str,
    fallback_datetime: Optional[datetime],
) -> tuple[Optional[Dict[str, Any]], str, Optional[str]]:
    notes: Optional[str] = None
    try:
        if media_kind == "pdf":
            extracted = extract_text_from_pdf(path, max_pages=2)
        else:
            extracted = extract_text_from_image_path(path)
    except Exception as exc:  # noqa: BLE001
        extracted = ""
        notes = f"{media_kind.upper()} extraction failed: {exc}"

    combined = "\n\n".join(part for part in (caption, extracted) if part).strip()
    if not combined:
        return None, caption or f"[{media_kind}]", notes
    return _parse_text_in_worker(combined, fallback_datetime), combined, notes


def _message_fallback_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc).astimezone(
                pytz.timezone("Asia/Tashkent")
            )
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return pytz.timezone("Asia/Tashkent").localize(parsed)
        return parsed.astimezone(pytz.timezone("Asia/Tashkent"))
    except (TypeError, ValueError, OSError):
        return None


def _validate_download(path: str, *, media_kind: str) -> None:
    configured = (
        os.getenv("RECEIPT_MAX_PDF_BYTES", str(25 * 1024 * 1024))
        if media_kind == "pdf"
        else os.getenv("RECEIPT_MAX_IMAGE_BYTES", str(15 * 1024 * 1024))
    )
    limit = max(1, int(configured))
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise HTTPException(status_code=422, detail=f"Unreadable {media_kind} file: {exc}") from exc
    if size > limit:
        raise HTTPException(
            status_code=413,
            detail=f"{media_kind.upper()} exceeds the configured {limit // (1024 * 1024)} MB limit",
        )


def _transaction_snapshot(txn: Transaction) -> Dict[str, Any]:
    fields = (
        "transaction_date", "amount", "currency", "card_last_4", "operator_raw",
        "application_mapped", "transaction_type", "balance_after", "receiver_name",
        "receiver_card", "parsing_method", "parsing_confidence", "fingerprint",
    )
    return {name: str(getattr(txn, name, None)) for name in fields}


def _mark_tg_message(
    db: Session,
    *,
    chat_id: int,
    message_id: int,
    transaction_id: int,
    duplicate: bool,
) -> None:
    row = (
        db.query(TgChatMessage)
        .filter(TgChatMessage.chat_id == int(chat_id), TgChatMessage.message_id == int(message_id))
        .first()
    )
    if row is None:
        return
    row.processing_status = "done"
    row.processing_error_code = None
    row.processing_error_text = None
    row.receipt_transaction_id = int(transaction_id)
    row.duplicate_status = "source_duplicate" if duplicate else None


async def process_tdlib_message(
    chat_id: int,
    message_id: int,
    force: bool,
    db: Session,
    manager: TelegramTDLibManager,
    authorize_result: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> "ProcessReceiptResponse":
    """Process a Telegram message into a Transaction, reusing existing logic."""
    # Late imports to break circular dependency
    from api.routes.transactions import (
        ProcessReceiptResponse,
        ParsingInfo,
        infer_transaction_type,
        build_transaction_response,
    )
    # Duplicate check - use integer types to match database schema (BigInteger)
    existing = (
        db.query(Transaction)
        .filter(
            Transaction.source_chat_id == int(chat_id),
            Transaction.source_message_id == int(message_id),
        )
        .first()
    )
    if existing is not None and authorize_result is not None:
        authorize_result(
            {
                "transaction_date": existing.transaction_date,
                "source_chat_id": existing.source_chat_id,
                "source_message_id": existing.source_message_id,
                "source_type": existing.source_type,
            }
        )
    if existing and not force:
        return ProcessReceiptResponse(
            created=False,
            duplicate=True,
            transaction=build_transaction_response(existing),
            parsing=ParsingInfo(
                method=getattr(existing, "parsing_method", None),
                confidence=None,
                notes="Already processed",
            ),
        )

    # Fetch message
    try:
        message = await manager.get_message(chat_id, message_id)
    except TDLibUnavailableError as exc:  # pragma: no cover - infra errors
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to fetch message: {exc}")

    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    text: str = (message.get("text") or "").strip()
    file_id: Optional[int] = None
    mime_type: Optional[str] = None
    file_name: Optional[str] = None
    image_file_id: Optional[int] = None
    image_mime_type: Optional[str] = None
    parsing_notes: Optional[str] = None
    caption = text
    fallback_datetime = _message_fallback_datetime(message.get("date"))

    document = message.get("document") or {}
    photo = message.get("photo") or {}
    if document:
        mime_type = document.get("mime_type")
        file_name = document.get("file_name")
        file_id = document.get("file_id")
        text = text or ""
        if mime_type and mime_type != "application/pdf":
            if str(mime_type).lower().startswith("image/"):
                image_file_id = file_id
                image_mime_type = mime_type
                file_id = None
                mime_type = None
                file_name = None
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported document type: {mime_type}")

    if photo and photo.get("file_id"):
        image_file_id = photo.get("file_id")
        image_mime_type = photo.get("mime_type") or "image/jpeg"

    raw_text_for_parser = text
    parsed: Optional[Dict[str, Any]] = None

    # Handle documents/images
    is_pdf = (mime_type or "").lower() == "application/pdf" or (file_name or "").lower().endswith(".pdf")
    is_image = bool(image_file_id) or str(image_mime_type or "").lower().startswith("image/")
    pdf_path: Optional[str] = None
    image_path: Optional[str] = None

    if is_pdf and file_id:
        try:
            pdf_path = await manager.download_file(file_id)
        except TDLibUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Timed out downloading PDF from TDLib")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Failed to download PDF: {exc}")

        if not pdf_path:
            raise HTTPException(status_code=404, detail="PDF file not found")

        try:
            _validate_download(pdf_path, media_kind="pdf")
            parsed, raw_text_for_parser, parsing_notes = await asyncio.to_thread(
                _extract_and_parse_in_worker,
                pdf_path,
                caption=caption,
                media_kind="pdf",
                fallback_datetime=fallback_datetime,
            )
        finally:
            try:
                if pdf_path and os.path.isfile(pdf_path):
                    os.unlink(pdf_path)
            except Exception:
                pass

    elif is_image and image_file_id:
        try:
            image_path = await manager.download_file(image_file_id)
        except TDLibUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Timed out downloading image from TDLib")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Failed to download image: {exc}")

        if not image_path:
            raise HTTPException(status_code=404, detail="Image file not found")

        try:
            _validate_download(image_path, media_kind="image")
            parsed, raw_text_for_parser, parsing_notes = await asyncio.to_thread(
                _extract_and_parse_in_worker,
                image_path,
                caption=caption,
                media_kind="image",
                fallback_datetime=fallback_datetime,
            )
        finally:
            try:
                if image_path and os.path.isfile(image_path):
                    os.unlink(image_path)
            except Exception:
                pass

    else:
        raw_text_for_parser = text
        if not raw_text_for_parser:
            raise HTTPException(status_code=422, detail="Empty message content")
        parsed = await asyncio.to_thread(
            _parse_text_in_worker,
            raw_text_for_parser,
            fallback_datetime,
        )

    if not parsed:
        raise HTTPException(status_code=422, detail="Cannot parse receipt after OCR/text extraction")

    transaction_date = parsed.get("transaction_date")
    if isinstance(transaction_date, str):
        try:
            transaction_date = datetime.fromisoformat(transaction_date)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail=f"Invalid transaction_date: {exc}")
    if not transaction_date:
        raise HTTPException(status_code=422, detail="Parsed data missing transaction_date")

    tz = pytz.timezone("Asia/Tashkent")
    if transaction_date.tzinfo:
        transaction_date = transaction_date.astimezone(tz)
    else:
        transaction_date = tz.localize(transaction_date)
    # Strip timezone info so naive local time goes to DB without UTC conversion
    transaction_date = transaction_date.replace(tzinfo=None)

    amount_val = parsed.get("amount")
    if amount_val is None:
        raise HTTPException(status_code=422, detail="Parsed data missing amount")
    amount = Decimal(str(amount_val))

    txn_type = infer_transaction_type(parsed.get("transaction_type"), raw_text_for_parser)
    store_amount = -abs(amount) if txn_type == "DEBIT" else abs(amount)

    operator_raw = parsed.get("operator_raw") or "Unknown"
    raw_card = parsed.get("card_last_4") or parsed.get("card_last4")
    card_digits = "".join(ch for ch in str(raw_card or "") if ch.isdigit())
    card_last4 = card_digits[-4:] if card_digits else None
    balance_after = parsed.get("balance_after")
    application_mapped = parsed.get("application_mapped")
    currency = parsed.get("currency") or "UZS"

    legacy_ai_parsed_flag = (parsed.get("parsing_method") or "").upper().startswith("GPT")
    parsed_is_p2p = parsed.get("is_p2p")

    # Fingerprints are fuzzy reconciliation candidates only.  Source identity is
    # the sole automatic idempotency key for online ingestion.
    fp_candidates = compute_fingerprint_candidates(
        amount=amount,
        transaction_date=transaction_date,
        card_last4=card_last4,
        operator_raw=operator_raw,
        transaction_type=txn_type,
    )
    fp = fp_candidates[0]

    values = dict(
        transaction_date=transaction_date,
        operator_raw=operator_raw,
        application_mapped=application_mapped,
        amount=store_amount,
        balance_after=balance_after,
        card_last_4=card_last4,
        is_p2p=parsed_is_p2p if parsed_is_p2p is not None else "P2P" in operator_raw.upper(),
        transaction_type=txn_type,
        currency=currency,
        receiver_name=parsed.get("receiver_name"),
        receiver_card=parsed.get("receiver_card"),
        source_type="AUTO",
        raw_message=raw_text_for_parser,
        parsing_method=parsed.get("parsing_method"),
        parsing_confidence=parsed.get("parsing_confidence"),
        is_gpt_parsed=legacy_ai_parsed_flag,
        source_chat_id=int(chat_id),
        source_message_id=int(message_id),
        fingerprint=fp,
    )

    # Authorization is deliberately after parsing/normalization but before any
    # transaction, TgChatMessage, or audit mutation. Route policy can therefore
    # decide on the final parsed date/source without cleanup compensation.
    if authorize_result is not None:
        authorize_result(dict(values))

    if existing and force:
        before = _transaction_snapshot(existing)
        for field, value in values.items():
            # Source identity is immutable during a force reparse.
            if field not in {"source_chat_id", "source_message_id", "source_type"}:
                setattr(existing, field, value)
        existing.updated_at = datetime.utcnow()
        after = _transaction_snapshot(existing)
        db.add(
            AccessAuditLog(
                action="receipt_force_reparse",
                success=True,
                details_json=json.dumps(
                    {
                        "transaction_id": int(existing.id),
                        "chat_id": int(chat_id),
                        "message_id": int(message_id),
                        "before": before,
                        "after": after,
                    },
                    ensure_ascii=False,
                ),
            )
        )
        _mark_tg_message(
            db,
            chat_id=chat_id,
            message_id=message_id,
            transaction_id=int(existing.id),
            duplicate=False,
        )
        db.commit()
        db.refresh(existing)
        return ProcessReceiptResponse(
            created=False,
            duplicate=False,
            transaction=build_transaction_response(existing),
            parsing=ParsingInfo(
                method=parsed.get("parsing_method"),
                confidence=parsed.get("parsing_confidence"),
                notes="Reprocessed existing transaction; previous values retained in audit log",
            ),
        )

    txn = Transaction(**values)

    try:
        db.add(txn)
        db.flush()
        _mark_tg_message(
            db,
            chat_id=chat_id,
            message_id=message_id,
            transaction_id=int(txn.id),
            duplicate=False,
        )
        db.commit()
        db.refresh(txn)
    except IntegrityError:
        db.rollback()
        raced = (
            db.query(Transaction)
            .filter(
                Transaction.source_chat_id == int(chat_id),
                Transaction.source_message_id == int(message_id),
            )
            .first()
        )
        if raced is None:
            raise HTTPException(status_code=409, detail="Transaction identity conflict")
        if authorize_result is not None:
            authorize_result(
                {
                    "transaction_date": raced.transaction_date,
                    "source_chat_id": raced.source_chat_id,
                    "source_message_id": raced.source_message_id,
                    "source_type": raced.source_type,
                }
            )
        _mark_tg_message(
            db,
            chat_id=chat_id,
            message_id=message_id,
            transaction_id=int(raced.id),
            duplicate=True,
        )
        db.commit()
        return ProcessReceiptResponse(
            created=False,
            duplicate=True,
            transaction=build_transaction_response(raced),
            parsing=ParsingInfo(
                method=getattr(raced, "parsing_method", None),
                confidence=getattr(raced, "parsing_confidence", None),
                notes="Already processed by another worker",
            ),
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save transaction: {exc}")

    parsing_info = ParsingInfo(
        method=parsed.get("parsing_method"),
        confidence=parsed.get("parsing_confidence"),
        notes=parsing_notes,
    )

    return ProcessReceiptResponse(
        created=True,
        duplicate=False,
        transaction=build_transaction_response(txn),
        parsing=parsing_info,
    )
