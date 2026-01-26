"""
Celery worker for async receipt processing (checks table)
"""
import os
import json
import logging
import re
import hashlib
from datetime import datetime
from decimal import Decimal

import pytz
import httpx
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Celery configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
BACKEND_INTERNAL_URL = os.getenv("BACKEND_INTERNAL_URL", "http://backend:8000")
app = Celery('uzbek_parser_worker', broker=REDIS_URL, backend=REDIS_URL)

# Celery settings
app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Tashkent',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30,  # 30 seconds max per task
    worker_prefetch_multiplier=1,
)


TASHKENT_TZ = pytz.timezone("Asia/Tashkent")
EMOJI_PATTERN = re.compile(r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF]")


def to_tashkent_naive(dt: datetime) -> datetime:
    """Return naive datetime in Asia/Tashkent."""
    if dt is None:
        return None
    if dt.tzinfo:
        return dt.astimezone(TASHKENT_TZ).replace(tzinfo=None)
    return dt


def compute_weekday_label(dt: datetime) -> str:
    weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    return weekdays[dt.weekday()]


def compute_date_display(dt: datetime) -> str:
    months = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
    return f"{dt.day} {months[dt.month - 1]}"


def compute_time_display(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def extract_card_last4(raw_text: str, fallback: str = "0000") -> str:
    """Try to extract last4 after asterisks."""
    if not raw_text:
        return fallback
    match = re.search(r"\*+(\d{4})", raw_text)
    return match.group(1) if match else fallback


def detect_source(raw_text: str, source_type: str) -> str:
    """
    Determine source string for checks: 'Telegram' or 'SMS'.
    Prefer explicit source_type; default to Telegram.
    """
    if source_type and source_type.upper() == "SMS":
        return "SMS"
    if source_type and source_type.upper() in ("AUTO", "MANUAL"):
        return "Telegram"
    if raw_text and EMOJI_PATTERN.search(raw_text):
        return "Telegram"
    return "SMS"


def normalize_amount_positive(value) -> Decimal:
    """Return Decimal with absolute value."""
    if value is None:
        return None
    return abs(Decimal(value))


def compute_fingerprint(amount: Decimal, transaction_date: datetime, card_last4: str) -> str:
    """Compute SHA256 fingerprint for duplicate detection."""
    # Normalize: use absolute amount, date to minute precision, last 4 of card
    amount_str = str(abs(amount)) if amount else "0"
    date_str = transaction_date.strftime("%Y-%m-%d %H:%M") if transaction_date else ""
    card_str = str(card_last4)[-4:] if card_last4 else "0000"
    data = f"{amount_str}|{date_str}|{card_str}"
    return hashlib.sha256(data.encode()).hexdigest()


def download_pdf_text(file_id: int, return_bytes: bool = False):
    """
    Download PDF via internal backend endpoint and extract text with OCR fallback.
    Uses cascade: PyMuPDF → pdfplumber → OCR (Tesseract).
    Returns extracted text (may be empty if all methods fail).
    """
    url = f"{BACKEND_INTERNAL_URL.rstrip('/')}/api/tg/files/{file_id}"
    with httpx.Client(timeout=60) as client:
        resp = client.get(url)
        resp.raise_for_status()
        pdf_bytes = resp.content

    # Use new cascade extraction with OCR fallback
    from parsers.pdf_extractor import extract_text_from_pdf_bytes
    text = extract_text_from_pdf_bytes(pdf_bytes, max_pages=2, use_ocr=True)

    if not text or len(text.strip()) < 20:
        logger.warning(f"PDF {file_id} has insufficient text after extraction: {len(text)} chars")
        # Return what we have - don't fail, Vision API can handle images later if needed

    # Limit to 20k chars for API efficiency
    text = text[:20000] if len(text) > 20000 else text

    if return_bytes:
        return text, pdf_bytes
    return text


def queue_receipt_task(task_data: dict) -> str:
    """
    Enqueue Celery task with persistent tracking.
    Returns task_id (existing for in-flight tasks).
    """
    from database.connection import get_db
    from database.models import ReceiptProcessingTask

    chat_id = task_data.get('source_chat_id')
    msg_id = task_data.get('source_message_id')
    try:
        chat_id = int(chat_id) if chat_id is not None else None
    except (TypeError, ValueError):
        chat_id = None
    try:
        msg_id = int(msg_id) if msg_id is not None else None
    except (TypeError, ValueError):
        msg_id = None

    with get_db() as db:
        existing = None
        if chat_id is not None and msg_id is not None:
            existing = (
                db.query(ReceiptProcessingTask)
                .filter(
                    ReceiptProcessingTask.chat_id == chat_id,
                    ReceiptProcessingTask.message_id == msg_id
                )
                .first()
            )
            if existing and existing.status in ('queued', 'processing'):
                return existing.task_id

        # Dispatch new Celery task
        result = process_receipt_task.delay(json.dumps(task_data))

        if chat_id is None or msg_id is None:
            return result.id

        if existing:
            existing.task_id = result.id
            existing.status = 'queued'
            existing.error = None
            existing.transaction_id = None
        else:
            tracking = ReceiptProcessingTask(
                task_id=result.id,
                chat_id=chat_id,
                message_id=msg_id,
                status='queued'
            )
            db.add(tracking)
        db.commit()
        return result.id


@app.task(name='process_receipt', bind=True, max_retries=3)
def process_receipt_task(self, task_data_json: str):
    """
    Process a single receipt from the queue
    
    Args:
        task_data_json: JSON string containing receipt data
    """
    from database.connection import get_db
    from database.models import Transaction, ParsingLog, ReceiptProcessingTask, OperatorReference
    from parsers.parser_orchestrator import ParserOrchestrator
    
    try:
        celery_task_id = self.request.id
        # Parse task data
        task_data = json.loads(task_data_json)
        raw_text_original = task_data.get('raw_text') or ""
        source_type = task_data.get('source_type', 'MANUAL')
        source_chat_id = str(task_data.get('source_chat_id')) if task_data.get('source_chat_id') is not None else None
        source_message_id = str(task_data.get('source_message_id')) if task_data.get('source_message_id') is not None else None
        document = task_data.get('document') or {}
        
        start_time = datetime.now()
        
        # Process with parser orchestrator
        with get_db() as db:
            # Update tracking -> processing
            tracking = None
            if source_chat_id and source_message_id:
                tracking = (
                    db.query(ReceiptProcessingTask)
                    .filter(ReceiptProcessingTask.task_id == celery_task_id)
                    .first()
                )
                if tracking:
                    tracking.status = 'processing'
                    tracking.error = None
                    db.commit()

            # Idempotency: skip duplicates by source ids (transactions table)
            if source_chat_id and source_message_id:
                try:
                    chat_id_int = int(source_chat_id)
                    msg_id_int = int(source_message_id)
                except (ValueError, TypeError):
                    chat_id_int = None
                    msg_id_int = None

                if chat_id_int is not None and msg_id_int is not None:
                    existing = (
                        db.query(Transaction)
                        .filter(
                            Transaction.source_chat_id == chat_id_int,
                            Transaction.source_message_id == msg_id_int
                        )
                        .first()
                    )
                    if existing:
                        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
                        if tracking:
                            tracking.status = 'done'
                            tracking.transaction_id = existing.id
                            db.commit()
                        log = ParsingLog(
                            raw_message=raw_text_original,
                            parsing_method=None,
                            success=True,
                            processing_time_ms=processing_time
                        )
                        db.add(log)
                        db.commit()
                        return {
                            'success': True,
                            'duplicate': True,
                            'transaction_id': str(existing.uuid),
                            'id': existing.id
                        }

            orchestrator = ParserOrchestrator(db)
            gpt_parser = orchestrator.gpt_parser
            raw_text = raw_text_original or ""
            parsed_data = None
            pdf_bytes = b""

            # Handle PDF documents
            is_pdf = document and document.get('mime_type') == 'application/pdf' and document.get('file_id')
            if is_pdf:
                try:
                    pdf_text, pdf_bytes = download_pdf_text(int(document['file_id']), return_bytes=True)
                except Exception as e:
                    if tracking:
                        tracking.status = 'failed'
                        tracking.error = f"PDF download/extract failed: {e}"
                        db.commit()
                    raise

                raw_text_parts = [part for part in [raw_text_original, pdf_text] if part]
                raw_text = "\n\n".join(raw_text_parts).strip()

            # Text-first parsing
            if raw_text:
                parsed_data = orchestrator.process(raw_text)

            # Vision fallback for PDFs when text parsing failed or text is too weak
            if is_pdf and (not parsed_data or len(raw_text.strip()) < 40):
                if gpt_parser and getattr(gpt_parser, "enabled", False) and pdf_bytes:
                    try:
                        from parsers.pdf_extractor import render_pdf_bytes_to_png_base64

                        images_b64 = render_pdf_bytes_to_png_base64(pdf_bytes, max_pages=2, dpi=170)
                        caption_text = (document.get("caption") or raw_text_original or "").strip()
                        parsed_data = gpt_parser.parse_from_images(images_b64, caption_text)
                        if parsed_data:
                            parsed_data.setdefault("parsing_method", "GPT_VISION")
                            parsed_data["is_gpt_parsed"] = True
                            if not raw_text:
                                raw_text = caption_text or "[vision parsed PDF]"
                    except Exception as vision_err:
                        logger.warning("Vision fallback failed for PDF %s: %s", document.get("file_id"), vision_err)
                else:
                    logger.info("Vision fallback skipped: GPT parser unavailable or pdf bytes missing")

            processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
            
            if not parsed_data:
                log = ParsingLog(
                    raw_message=raw_text,
                    success=False,
                    error_message="Parsing returned None",
                    processing_time_ms=processing_time
                )
                db.add(log)
                if tracking:
                    tracking.status = 'failed'
                    tracking.error = "Parsing returned None"
                db.commit()
                print(f"❌ Parsing failed for receipt")
                return {'success': False, 'error': 'Parsing failed'}

            # Suggest adding new reference entry if AI proposed one and it's not in DB yet
            suggestion = parsed_data.get("operator_reference_suggestion")
            if suggestion and suggestion.get("application_name"):
                suggested_operator = suggestion.get("operator_name") or parsed_data.get("operator_raw") or ""
                # Normalize operator name using mapper normalization when available
                if orchestrator and orchestrator.operator_mapper:
                    normalized_operator = orchestrator.operator_mapper.normalize_operator(suggested_operator)
                else:
                    normalized_operator = suggested_operator.strip()

                if normalized_operator:
                    existing_ref = (
                        db.query(OperatorReference)
                        .filter(
                            OperatorReference.operator_name == normalized_operator,
                            OperatorReference.application_name == suggestion["application_name"],
                        )
                        .first()
                    )
                    if not existing_ref:
                        new_ref = OperatorReference(
                            operator_name=normalized_operator,
                            application_name=suggestion["application_name"],
                            is_p2p=bool(suggestion.get("is_p2p", False)),
                            is_active=False,
                        )
                        db.add(new_ref)
                        db.commit()

            # Normalize fields
            tx_datetime = to_tashkent_naive(parsed_data['transaction_date'])
            operator = parsed_data.get('operator_raw') or 'Unknown'
            app_name = parsed_data.get('application_mapped')
            amount = normalize_amount_positive(parsed_data['amount'])
            balance_after = parsed_data.get('balance_after')
            balance = normalize_amount_positive(balance_after) if balance_after is not None else None
            card_last4 = (
                parsed_data.get('card_last_4')
                or parsed_data.get('card_last4')
                or extract_card_last4(raw_text)
            )
            if not card_last4:
                card_last4 = "0000"
            transaction_type = parsed_data.get('transaction_type') or 'DEBIT'
            currency = parsed_data.get('currency', 'UZS')
            is_p2p = parsed_data.get('is_p2p', False)

            # Determine source_type for Transaction model (MANUAL or AUTO)
            if source_type and source_type.upper() in ('AUTO', 'USERBOT'):
                tx_source_type = 'AUTO'
            else:
                tx_source_type = 'MANUAL'

            # Convert source IDs to integers for Transaction model
            try:
                chat_id_int = int(source_chat_id) if source_chat_id else 0
            except (ValueError, TypeError):
                chat_id_int = 0

            try:
                msg_id_int = int(source_message_id) if source_message_id else None
            except (ValueError, TypeError):
                msg_id_int = None

            # Extract parsing metadata from parsed_data
            is_gpt_parsed_flag = parsed_data.get('is_gpt_parsed', False)
            confidence_value = parsed_data.get('parsing_confidence')
            method_value = parsed_data.get('parsing_method')

            # Compute fingerprint for duplicate detection
            fp = compute_fingerprint(amount, tx_datetime, card_last4)
            
            # Check if fingerprint already exists (duplicate content)
            existing_by_fp = (
                db.query(Transaction)
                .filter(Transaction.fingerprint == fp)
                .first()
            )
            if existing_by_fp:
                processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
                if tracking:
                    tracking.status = 'done'
                    tracking.transaction_id = existing_by_fp.id
                    db.commit()
                log = ParsingLog(
                    raw_message=raw_text,
                    parsing_method=method_value,
                    success=True,
                    processing_time_ms=processing_time
                )
                db.add(log)
                db.commit()
                print(f"⚠️ Duplicate receipt detected by fingerprint, skipping")
                return {
                    'success': True,
                    'duplicate': True,
                    'transaction_id': str(existing_by_fp.uuid),
                    'id': existing_by_fp.id
                }

            transaction = Transaction(
                raw_message=raw_text,
                source_type=tx_source_type,
                source_chat_id=chat_id_int,
                source_message_id=msg_id_int,
                transaction_date=tx_datetime,
                amount=amount,
                currency=currency,
                card_last_4=str(card_last4)[-4:] if card_last4 else None,
                operator_raw=operator,
                application_mapped=app_name,
                receiver_name=parsed_data.get('receiver_name'),
                receiver_card=parsed_data.get('receiver_card'),
                transaction_type=transaction_type,
                balance_after=balance,
                is_p2p=is_p2p,
                is_gpt_parsed=is_gpt_parsed_flag,
                parsing_confidence=confidence_value,
                parsing_method=method_value,
                fingerprint=fp,
            )

            db.add(transaction)
            db.commit()

            if tracking:
                tracking.status = 'done'
                tracking.transaction_id = transaction.id
                tracking.error = None
                db.commit()

            log = ParsingLog(
                raw_message=raw_text,
                parsing_method=method_value,
                success=True,
                processing_time_ms=processing_time
            )
            db.add(log)
            db.commit()

            print(f"✅ Transaction saved: {transaction.id} ({transaction.amount} {transaction.currency})")

            return {
                'success': True,
                'transaction_id': str(transaction.uuid),
                'id': transaction.id,
                'amount': str(amount),
                'currency': currency,
                'application': app_name
            }

    except Exception as e:
        print(f"❌ Worker error: {e}")
        
        # Log exception
        try:
            with get_db() as db:
                tracking = (
                    db.query(ReceiptProcessingTask)
                    .filter(ReceiptProcessingTask.task_id == getattr(self.request, "id", None))
                    .first()
                )
                if tracking:
                    tracking.status = 'failed'
                    tracking.error = str(e)
                log = ParsingLog(
                    raw_message=raw_text if 'raw_text' in locals() else '',
                    success=False,
                    error_message=str(e)
                )
                db.add(log)
                db.commit()
        except Exception:
            pass
        
        # Retry task
        raise self.retry(exc=e, countdown=5)
