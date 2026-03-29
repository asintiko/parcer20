"""
Celery worker for async receipt processing (checks table)
"""
import os
import json
import logging
import re
import base64
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import pytz
import httpx
from celery import Celery
from dotenv import load_dotenv
from services.fingerprint import compute_fingerprint_candidates
from core.logging_config import setup_logging

load_dotenv()
setup_logging()

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
    task_time_limit=120,      # hard limit: 2 minutes
    task_soft_time_limit=90,  # soft limit: 1.5 minutes
    worker_prefetch_multiplier=1,
)

BACKGROUND_AUDIT_MAX_CHUNKS_PER_TASK = int(os.getenv("AI_AGENT_AUDIT_MAX_CHUNKS_PER_TASK", "2"))
BACKGROUND_AUDIT_REQUEUE_DELAY_SECONDS = int(os.getenv("AI_AGENT_AUDIT_REQUEUE_DELAY_SECONDS", "1"))


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
    return dt.strftime("%d.%m.%Y")


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
    if isinstance(value, str):
        cleaned = value.replace(" ", "").replace(",", ".")
        return abs(Decimal(cleaned))
    return abs(Decimal(str(value)))


def download_file_bytes(file_id: int) -> bytes:
    url = f"{BACKEND_INTERNAL_URL.rstrip('/')}/api/tg/files/{file_id}"
    headers = {}
    internal_api_key = os.getenv("INTERNAL_API_KEY")
    if internal_api_key:
        headers["X-Internal-Api-Key"] = internal_api_key
    with httpx.Client(timeout=60) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.content


def download_pdf_text(file_id: int, return_bytes: bool = False):
    """
    Download PDF via internal backend endpoint and extract text with OCR fallback.
    Uses cascade: PyMuPDF → pdfplumber → OCR (Tesseract).
    Returns extracted text (may be empty if all methods fail).
    """
    pdf_bytes = download_file_bytes(file_id)

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


def download_image_text(file_id: int, return_bytes: bool = False):
    """
    Download image via internal backend endpoint and OCR text.
    """
    image_bytes = download_file_bytes(file_id)
    from parsers.pdf_extractor import extract_text_from_image_bytes

    text = extract_text_from_image_bytes(image_bytes)
    if not text or len(text.strip()) < 20:
        logger.warning(f"Image {file_id} has insufficient text after OCR: {len(text)} chars")
    text = text[:20000] if len(text) > 20000 else text

    if return_bytes:
        return text, image_bytes
    return text


def queue_receipt_task(task_data: dict, force: bool = False) -> str:
    """
    Enqueue Celery task with persistent tracking.
    Returns task_id (existing for in-flight tasks).
    If force=False (default), checks for existing transaction and skips if found.
    """
    from database.connection import get_db
    from database.models import ReceiptProcessingTask, Transaction

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
        existing_task = None
        if chat_id is not None and msg_id is not None:
            # Check if already in processing queue
            existing_task = (
                db.query(ReceiptProcessingTask)
                .filter(
                    ReceiptProcessingTask.chat_id == chat_id,
                    ReceiptProcessingTask.message_id == msg_id
                )
                .first()
            )
            if existing_task and existing_task.status in ('queued', 'processing'):
                return existing_task.task_id

            # STRICT DUPLICATE CHECK: Check if transaction already exists
            if not force:
                existing_txn = (
                    db.query(Transaction)
                    .filter(
                        Transaction.source_chat_id == chat_id,
                        Transaction.source_message_id == msg_id
                    )
                    .first()
                )
                if existing_txn:
                    # Return existing task_id or create a dummy response
                    if existing_task:
                        return existing_task.task_id
                    # Message already processed, return a marker
                    raise ValueError(f"Сообщение уже обработано (транзакция #{existing_txn.id})")

        # Dispatch new Celery task
        result = process_receipt_task.delay(json.dumps(task_data))

        if chat_id is None or msg_id is None:
            return result.id

        if existing_task:
            existing_task.task_id = result.id
            existing_task.status = 'queued'
            existing_task.error = None
            existing_task.transaction_id = None
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


def register_receipt_incident(
    db,
    *,
    chat_id: int | None,
    message_id: int | None,
    incident_type: str,
    severity: str = 'high',
    task_id: int | None = None,
    transaction_id: int | None = None,
    reason_code: str | None = None,
    reason_text: str | None = None,
    payload: dict | None = None,
) -> None:
    if chat_id is None:
        return
    try:
        from services.incident_service import upsert_receipt_incident

        upsert_receipt_incident(
            db,
            chat_id=int(chat_id),
            message_id=int(message_id) if message_id is not None else None,
            incident_type=incident_type,
            severity=severity,
            task_id=task_id,
            transaction_id=transaction_id,
            reason_code=reason_code,
            reason_text=reason_text,
            payload=payload,
            notify=True,
        )
    except Exception:
        logger.debug("Failed to register receipt incident", exc_info=True)


@app.task(
    name='agent_monitored_chat_sync_audit',
    bind=True,
    max_retries=1,
    soft_time_limit=300,
    time_limit=360,
)
def run_agent_monitored_chat_sync_audit_task(self, task_payload_json: str):
    from database.connection import SessionLocal, get_db
    from services.ai_agent.session_service import create_message, create_run_event, update_run
    from services.ai_agent.tools.cache_tools import _build_monitored_chat_sync_audit_result, _parse_datetime
    from services.incident_service import upsert_receipt_incident
    from services.telegram_cache_service import TelegramCacheService

    task_payload = json.loads(task_payload_json or "{}")
    run_id = UUID(str(task_payload.get("run_id")))
    thread_id = UUID(str(task_payload.get("thread_id")))
    payload = task_payload.get("payload") or {}
    chat_ids = payload.get("chat_ids") or None
    grace_minutes = int(payload.get("grace_minutes") or 5)
    date_from = _parse_datetime(payload.get("date_from"))
    date_to = _parse_datetime(payload.get("date_to"))
    estimated_candidates = int(payload.get("estimated_candidates") or 0)
    chunk_size = int(payload.get("chunk_size") or 500)
    resume_state = task_payload.get("state") or {}

    try:
        with get_db() as db:
            if not resume_state:
                create_run_event(
                    db,
                    run_id=run_id,
                    event_type='tool_started',
                    label='Сверяю чеки',
                    status='running',
                    payload={
                        'mode': 'background',
                        'date_from': payload.get('date_from'),
                        'date_to': payload.get('date_to'),
                        'estimated_candidates': estimated_candidates,
                    },
                )

            def _issue_to_incident(issue: dict) -> None:
                category = str(issue.get('category') or '').upper()
                if category in {'SYNCED', 'PENDING_PROCESSING'}:
                    return
                incident_type = {
                    'FAILED_PARSE': 'failed_parse',
                    'MISSING_IN_DB': 'missing_in_db',
                    'DUPLICATE': 'duplicate_without_row',
                    'CURSOR_STALE': 'cursor_stale',
                    'CACHE_GAP': 'cache_gap',
                    'ORPHANED_IN_DB': 'manual_review',
                }.get(category, 'manual_review')
                upsert_receipt_incident(
                    db,
                    chat_id=int(issue.get('chat_id') or 0),
                    message_id=int(issue.get('message_id')) if issue.get('message_id') is not None else None,
                    transaction_id=int(issue.get('transaction_id')) if issue.get('transaction_id') is not None else None,
                    task_id=int(issue.get('task_id')) if issue.get('task_id') is not None else None,
                    incident_type=incident_type,
                    severity='high' if category in {'FAILED_PARSE', 'MISSING_IN_DB', 'CURSOR_STALE', 'CACHE_GAP'} else 'medium',
                    reason_code=category.lower(),
                    reason_text=str(issue.get('summary') or ''),
                    payload=issue,
                    notify=False,
                    auto_commit=False,
                )

            summary = TelegramCacheService(db).audit_monitored_chats_chunked(
                chat_ids=chat_ids,
                date_from=date_from,
                date_to=date_to,
                grace_minutes=grace_minutes,
                chunk_size=chunk_size,
                resume_state=resume_state,
                max_chunks=BACKGROUND_AUDIT_MAX_CHUNKS_PER_TASK,
                issue_callback=_issue_to_incident,
            )
            db.commit()

            progress_payload = {
                'mode': 'background',
                'phase': summary.get('phase') or ('completed' if summary.get('complete') else 'scan_chunk'),
                'current_chat_id': summary.get('current_chat_id'),
                'processed_messages': int(summary.get('processed_messages') or 0),
                'total_estimated_messages': int(summary.get('total_estimated_messages') or estimated_candidates),
                'issues_found': int(summary.get('total_issues') or 0),
                'completed_chat_ids': summary.get('completed_chat_ids') or [],
                'cursor': summary.get('cursor'),
                'started_from_latest': True,
                'categories': summary.get('categories') or {},
                'percent': int(summary.get('percent') or 0),
            }

            update_run(
                db,
                run_id=run_id,
                status='processing' if not summary.get('complete') else 'completed',
                progress=progress_payload,
                requires_confirmation=False,
            )
            create_run_event(
                db,
                run_id=run_id,
                event_type='tool_progress',
                label='Сверяю чеки',
                status='running' if not summary.get('complete') else 'completed',
                payload=progress_payload,
            )

            if not summary.get('complete'):
                next_payload = {
                    **task_payload,
                    'state': {
                        'monitored_ids': summary.get('monitored_ids') or (resume_state.get('monitored_ids') if isinstance(resume_state, dict) else None),
                        'completed_chat_ids': summary.get('completed_chat_ids') or [],
                        'seen_chat_ids': summary.get('seen_chat_ids') or [],
                        'cursor': summary.get('cursor'),
                        'processed_messages': int(summary.get('processed_messages') or 0),
                        'total_estimated_messages': int(summary.get('total_estimated_messages') or estimated_candidates),
                        'total_issues': int(summary.get('total_issues') or 0),
                        'categories': summary.get('categories') or {},
                        'by_chat': summary.get('by_chat') or [],
                        'issues_preview': summary.get('issues_preview') or [],
                        'top_actionable_cases': summary.get('top_actionable_cases') or [],
                    },
                }
                run_agent_monitored_chat_sync_audit_task.apply_async(
                    args=[json.dumps(next_payload, ensure_ascii=False)],
                    countdown=max(0, BACKGROUND_AUDIT_REQUEUE_DELAY_SECONDS),
                )
                return progress_payload

            assistant_payload = _build_monitored_chat_sync_audit_result(
                summary=summary,
                date_from=date_from,
                date_to=date_to,
                background=False,
                estimated_candidates=estimated_candidates,
            )
            create_message(
                db,
                thread_id=thread_id,
                run_id=run_id,
                role='assistant',
                message_type='text',
                content=assistant_payload,
            )
            create_run_event(
                db,
                run_id=run_id,
                event_type='tool_finished',
                label='Сверка завершена',
                status='completed',
                payload={
                    'issues_found': int(summary.get('total_issues') or 0),
                    'categories': summary.get('categories') or {},
                },
            )
            create_run_event(
                db,
                run_id=run_id,
                event_type='completed',
                label='Готово',
                status='completed',
                payload={'mode': 'background', 'issues_found': int(summary.get('total_issues') or 0)},
            )
            update_run(
                db,
                run_id=run_id,
                status='completed',
                progress={**progress_payload, 'phase': 'completed', 'cursor': None, 'percent': 100},
                result=assistant_payload,
                requires_confirmation=False,
                error_text='',
            )
            return assistant_payload
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background monitored chat audit failed")
        with SessionLocal() as db:
            update_run(
                db,
                run_id=run_id,
                status='failed',
                progress={'mode': 'background', 'phase': 'failed', 'percent': 100},
                error_text=str(exc),
                requires_confirmation=False,
            )
            create_run_event(
                db,
                run_id=run_id,
                event_type='failed',
                label='Сверка завершилась ошибкой',
                status='failed',
                payload={'error': str(exc)},
            )
            if thread_id:
                create_message(
                    db,
                    thread_id=thread_id,
                    run_id=run_id,
                    role='system',
                    message_type='warning',
                    content={'message': f'Фоновая сверка завершилась ошибкой: {exc}'},
                )
        raise


@app.task(name='process_receipt', bind=True, max_retries=3)
def process_receipt_task(self, task_data_json: str):
    """
    Process a single receipt from the queue
    
    Args:
        task_data_json: JSON string containing receipt data
    """
    from database.connection import get_db
    from database.models import Transaction, ParsingLog, ReceiptProcessingTask, OperatorReference, DuplicateMergeLog
    from parsers.parser_orchestrator import ParserOrchestrator
    from services.receipt_processor import _merge_duplicate_transaction
    
    try:
        celery_task_id = self.request.id
        # Parse task data
        task_data = json.loads(task_data_json)
        raw_text_original = task_data.get('raw_text') or ""
        source_type = task_data.get('source_type', 'MANUAL')
        _raw_chat_id = task_data.get('source_chat_id')
        _raw_message_id = task_data.get('source_message_id')
        source_chat_id = (
            str(_raw_chat_id)
            if _raw_chat_id not in (None, "", "None", "null")
            else None
        )
        source_message_id = (
            str(_raw_message_id)
            if _raw_message_id not in (None, "", "None", "null")
            else None
        )
        document = task_data.get('document') or {}
        image = task_data.get('image') or {}
        
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
            raw_text = raw_text_original or ""
            parsed_data = None
            pdf_bytes = b""
            image_bytes = b""

            # Handle PDF documents
            is_pdf = document and document.get('mime_type') == 'application/pdf' and document.get('file_id')
            is_image = image and image.get("file_id") and str(image.get("mime_type") or "").lower().startswith("image/")
            if is_pdf:
                try:
                    pdf_text, pdf_bytes = download_pdf_text(int(document['file_id']), return_bytes=True)
                except Exception as e:
                    if tracking:
                        tracking.status = 'failed'
                        tracking.error = f"PDF download/extract failed: {e}"
                        db.commit()
                        register_receipt_incident(
                            db,
                            chat_id=tracking.chat_id,
                            message_id=tracking.message_id,
                            task_id=int(tracking.id),
                            incident_type='failed_parse',
                            reason_code='pdf_extract_failed',
                            reason_text=str(e),
                            payload={'stage': 'pdf_extract'},
                        )
                    raise

                raw_text_parts = [part for part in [raw_text_original, pdf_text] if part]
                raw_text = "\n\n".join(raw_text_parts).strip()
            elif is_image:
                try:
                    image_text, image_bytes = download_image_text(int(image["file_id"]), return_bytes=True)
                except Exception as e:
                    if tracking:
                        tracking.status = "failed"
                        tracking.error = f"Image download/extract failed: {e}"
                        db.commit()
                        register_receipt_incident(
                            db,
                            chat_id=tracking.chat_id,
                            message_id=tracking.message_id,
                            task_id=int(tracking.id),
                            incident_type='failed_parse',
                            reason_code='image_extract_failed',
                            reason_text=str(e),
                            payload={'stage': 'image_extract'},
                        )
                    raise
                raw_text_parts = [part for part in [raw_text_original, image_text] if part]
                raw_text = "\n\n".join(raw_text_parts).strip()

            # Text-first parsing
            if raw_text:
                parsed_data = orchestrator.process(raw_text)

            processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
            
            if not parsed_data:
                reason = getattr(orchestrator, "last_rejection_reason", None) or "unknown"
                error_message = f"Parsing returned None: {reason}"
                log = ParsingLog(
                    raw_message=raw_text,
                    success=False,
                    error_message=error_message,
                    processing_time_ms=processing_time
                )
                db.add(log)
                if tracking:
                    tracking.status = 'failed'
                    tracking.error = error_message
                    tracking.raw_message = (raw_text or "")[:4000] if raw_text else None
                db.commit()
                if tracking:
                    register_receipt_incident(
                        db,
                        chat_id=tracking.chat_id,
                        message_id=tracking.message_id,
                        task_id=int(tracking.id),
                        incident_type='failed_parse',
                        reason_code='parser_returned_none',
                        reason_text=error_message,
                        payload={'raw_text': (raw_text or '')[:1000]},
                    )
                logger.warning("Parsing failed for receipt: %s", reason)
                return {'success': False, 'error': error_message}

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
            store_amount = -abs(amount) if transaction_type == 'DEBIT' else abs(amount)
            currency = parsed_data.get('currency', 'UZS')
            is_p2p = parsed_data.get('is_p2p', False)

            # Determine source_type for Transaction model.
            source_type_upper = (source_type or "").upper()
            if source_type_upper in ("AUTO", "USERBOT"):
                tx_source_type = "AUTO"
            elif source_type_upper == "SMS":
                tx_source_type = "SMS"
            else:
                tx_source_type = "MANUAL"

            # Convert source IDs to integers for Transaction model
            try:
                chat_id_int = int(source_chat_id) if source_chat_id else None
            except (ValueError, TypeError):
                chat_id_int = None

            try:
                msg_id_int = int(source_message_id) if source_message_id else None
            except (ValueError, TypeError):
                msg_id_int = None

            # Extract parsing metadata from parsed_data
            is_gpt_parsed_flag = parsed_data.get('is_gpt_parsed', False)
            confidence_value = parsed_data.get('parsing_confidence')
            method_value = parsed_data.get('parsing_method')

            # Compute fingerprint candidates for duplicate detection.
            fp_candidates = compute_fingerprint_candidates(
                amount=amount,
                transaction_date=tx_datetime,
                card_last4=card_last4,
                operator_raw=operator,
            )
            fp = fp_candidates[0]

            # Check duplicates by all candidates to keep backward compatibility during transition.
            existing_by_fp = db.query(Transaction).filter(Transaction.fingerprint.in_(fp_candidates)).first()
            if existing_by_fp:
                original_method = getattr(existing_by_fp, "parsing_method", None)
                original_conf = float(getattr(existing_by_fp, "parsing_confidence", 0.0) or 0.0)
                merged = _merge_duplicate_transaction(
                    existing_by_fp,
                    candidate_transaction_date=tx_datetime,
                    candidate_operator_raw=operator,
                    candidate_application_mapped=app_name,
                    candidate_balance_after=balance,
                    candidate_receiver_name=parsed_data.get("receiver_name"),
                    candidate_receiver_card=parsed_data.get("receiver_card"),
                    candidate_raw_message=raw_text,
                    candidate_is_p2p=is_p2p,
                    candidate_parsing_method=method_value,
                    candidate_parsing_confidence=confidence_value,
                    candidate_is_gpt=is_gpt_parsed_flag,
                    candidate_source_type=tx_source_type,
                )
                db.add(
                    DuplicateMergeLog(
                        fingerprint=fp,
                        existing_transaction_id=int(existing_by_fp.id),
                        source_chat_id=chat_id_int,
                        source_message_id=msg_id_int,
                        merged=bool(merged),
                        candidate_method=method_value,
                        candidate_confidence=float(confidence_value) if confidence_value is not None else None,
                        existing_method=original_method,
                        existing_confidence=original_conf,
                        details_json=json.dumps(
                            {
                                "original_method": original_method,
                                "original_confidence": original_conf,
                                "candidate_method": method_value,
                                "candidate_confidence": confidence_value,
                                "candidate_has_receiver": bool(parsed_data.get("receiver_name") or parsed_data.get("receiver_card")),
                                "candidate_has_balance": parsed_data.get("balance_after") is not None,
                            },
                            ensure_ascii=False,
                        ),
                    )
                )
                db.commit()
                db.refresh(existing_by_fp)
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
                logger.info(
                    "Duplicate receipt detected by fingerprint, skipping%s",
                    " (merged richer fields)" if merged else "",
                )
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
                amount=store_amount,
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

            logger.info(
                "Transaction saved: id=%s amount=%s currency=%s",
                transaction.id,
                transaction.amount,
                transaction.currency,
            )

            return {
                'success': True,
                'transaction_id': str(transaction.uuid),
                'id': transaction.id,
                'amount': str(store_amount),
                'currency': currency,
                'application': app_name
            }

    except Exception as e:
        logger.exception("Worker error: %s", e)
        
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
                    _rt = raw_text if 'raw_text' in locals() else ''
                    tracking.raw_message = (_rt or "")[:4000] if _rt else None
                    register_receipt_incident(
                        db,
                        chat_id=tracking.chat_id,
                        message_id=tracking.message_id,
                        task_id=int(tracking.id),
                        incident_type='failed_parse',
                        reason_code='worker_exception',
                        reason_text=str(e),
                        payload={'raw_text': (_rt or '')[:1000]},
                    )
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


@app.task(name='generate_weekly_agent_report')
def generate_weekly_agent_report_task():
    """
    Generate the system-wide weekly AI agent report.
    """
    from database.connection import SessionLocal
    from services.ai_agent.report_service import build_previous_week_window, generate_report

    period_start, period_end = build_previous_week_window()
    with SessionLocal() as db:
        report = generate_report(
            db,
            created_by_user_id=0,
            thread_id=None,
            scope='team',
            period_start=period_start,
            period_end=period_end,
            publish_team_notification=True,
        )
    logger.info(
        "Weekly AI agent report generated: period_start=%s period_end=%s report_id=%s",
        period_start.isoformat(),
        period_end.isoformat(),
        report.get('id'),
    )
    return report


@app.task(name='cleanup_ai_agent_threads')
def cleanup_ai_agent_threads_task():
    from database.connection import SessionLocal
    from services.ai_agent.session_service import purge_expired_threads

    with SessionLocal() as db:
        removed = purge_expired_threads(db, limit=500)
    logger.info("AI agent thread cleanup completed: removed=%s", removed)
    return {"removed": removed}
