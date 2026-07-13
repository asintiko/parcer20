"""
Celery worker for async receipt processing (checks table)
"""
import os
import json
import logging
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

import pytz
import httpx
from celery import Celery
from dotenv import load_dotenv
from services.fingerprint import compute_fingerprint_candidates
from services.message_utils import is_metadata_only_chat, receipt_min_datetime
from services import receipt_logger
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
    # Tasks are ACKed after normal completion. If a child is hard-killed, the
    # durable DB watchdog below owns bounded recovery.
    task_acks_late=True,
    # A hard-killed child is acknowledged; the durable DB watchdog below owns
    # bounded recovery instead of Redis redelivering poison work forever.
    task_reject_on_worker_lost=False,
    # Disable noisy STARTED state writes — nobody reads them.
    task_track_started=False,
    task_time_limit=120,      # hard limit: 2 minutes
    task_soft_time_limit=90,  # soft limit: 1.5 minutes
    worker_prefetch_multiplier=1,
    # Recycle child every N tasks to release Tesseract / PIL / fitz handles.
    worker_max_tasks_per_child=int(os.getenv("CELERY_MAX_TASKS_PER_CHILD", "200")),
    # Visibility timeout > task_time_limit so Redis broker doesn't redeliver
    # mid-processing on slow tasks.
    broker_transport_options={
        "visibility_timeout": int(os.getenv("CELERY_VISIBILITY_TIMEOUT", "900")),
    },
    task_routes={
        "process_receipt": {"queue": "receipts.fast"},
        "receipt_outbox_dispatch": {"queue": "maintenance"},
        "receipt_task_watchdog_sweep": {"queue": "maintenance"},
        "receipt_task_retention_cleanup": {"queue": "maintenance"},
    },
)

BACKGROUND_AUDIT_MAX_CHUNKS_PER_TASK = int(os.getenv("AI_AGENT_AUDIT_MAX_CHUNKS_PER_TASK", "2"))
BACKGROUND_AUDIT_REQUEUE_DELAY_SECONDS = int(os.getenv("AI_AGENT_AUDIT_REQUEUE_DELAY_SECONDS", "1"))
BACKGROUND_AUDIT_MAX_CONTINUATIONS = int(os.getenv("AI_AGENT_AUDIT_MAX_CONTINUATIONS", "32"))
BACKGROUND_AUDIT_MAX_TOTAL_MESSAGES = int(os.getenv("AI_AGENT_AUDIT_MAX_TOTAL_MESSAGES", "100000"))
RECEIPT_MAX_PUBLISH_ATTEMPTS = int(os.getenv("RECEIPT_MAX_PUBLISH_ATTEMPTS", "12"))
RECEIPT_MAX_PROCESSING_ATTEMPTS = int(os.getenv("RECEIPT_MAX_PROCESSING_ATTEMPTS", "4"))
RECEIPT_OUTBOX_LEASE_SECONDS = int(os.getenv("RECEIPT_OUTBOX_LEASE_SECONDS", "120"))
RECEIPT_MAX_DOWNLOAD_BYTES = int(os.getenv("RECEIPT_MAX_DOWNLOAD_BYTES", str(25 * 1024 * 1024)))
RECEIPT_DOWNLOAD_TIMEOUT_SECONDS = float(os.getenv("RECEIPT_DOWNLOAD_TIMEOUT_SECONDS", "60"))


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


_HTTP_CLIENT: Optional[httpx.Client] = None


def _get_http_client() -> httpx.Client:
    """Module-level keep-alive httpx client to avoid TCP/TLS handshake per request."""
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        _HTTP_CLIENT = httpx.Client(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=8, max_connections=16),
        )
    return _HTTP_CLIENT


def download_file_bytes(file_id: int) -> bytes:
    url = f"{BACKEND_INTERNAL_URL.rstrip('/')}/api/tg/files/{file_id}"
    headers = {}
    internal_api_key = os.getenv("INTERNAL_API_KEY")
    if internal_api_key:
        headers["X-Internal-Api-Key"] = internal_api_key
    timeout = httpx.Timeout(RECEIPT_DOWNLOAD_TIMEOUT_SECONDS, connect=10.0)
    chunks = bytearray()
    with _get_http_client().stream("GET", url, headers=headers, timeout=timeout) as resp:
        resp.raise_for_status()
        content_length = resp.headers.get("Content-Length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = 0
            if declared_size > RECEIPT_MAX_DOWNLOAD_BYTES:
                raise ValueError(
                    f"receipt_file_too_large:{declared_size}>{RECEIPT_MAX_DOWNLOAD_BYTES}"
                )
        for chunk in resp.iter_bytes(chunk_size=64 * 1024):
            chunks.extend(chunk)
            if len(chunks) > RECEIPT_MAX_DOWNLOAD_BYTES:
                raise ValueError(
                    f"receipt_file_too_large:stream>{RECEIPT_MAX_DOWNLOAD_BYTES}"
                )
    return bytes(chunks)


def _task_fallback_datetime(task_data: dict) -> Optional[datetime]:
    value = (
        task_data.get("source_received_at")
        or task_data.get("message_date")
        or task_data.get("timestamp")
    )
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return to_tashkent_naive(value)
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        return datetime.fromtimestamp(float(value), tz=pytz.UTC).astimezone(TASHKENT_TZ).replace(tzinfo=None)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return to_tashkent_naive(parsed)
    return None


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


def _receipt_queue_name(task_data: dict) -> str:
    document = task_data.get("document") or {}
    image = task_data.get("image") or {}
    if document.get("file_id") or image.get("file_id"):
        return "receipts.ocr"
    return "receipts.fast"


def _retry_delay_seconds(attempt: int) -> int:
    return min(900, 10 * (3 ** max(0, attempt - 1)))


def _publish_receipt_outbox_task(task_id: str) -> bool:
    """Claim and publish one committed outbox row.

    Returning ``False`` is safe: the row remains durable and a later dispatcher
    pass retries it. A stable Celery id plus source identity makes an ambiguous
    publish acknowledgement harmless.
    """
    from database.connection import get_db
    from database.models import ReceiptProcessingTask

    now = datetime.utcnow()
    payload_json = None
    publish_attempt = 0
    queue_name = "receipts.fast"
    with get_db() as db:
        row = (
            db.query(ReceiptProcessingTask)
            .filter(ReceiptProcessingTask.task_id == str(task_id))
            .with_for_update(skip_locked=True)
            .first()
        )
        if not row or row.publish_state not in {"pending", "retry"}:
            return False
        if row.next_retry_at and row.next_retry_at > now:
            return False
        if int(row.publish_attempts or 0) >= RECEIPT_MAX_PUBLISH_ATTEMPTS:
            row.status = "dead"
            row.publish_state = "dead"
            row.finished_at = now
            row.last_error_kind = "publish_exhausted"
            row.error = row.error or "broker_publish_attempts_exhausted"
            db.commit()
            _push_to_dlq(
                celery_task_id=row.task_id,
                task_data_json=row.payload_json or "{}",
                error=RuntimeError(row.error),
                tb_text="",
                retries=int(row.publish_attempts or 0),
                reason="publish_exhausted",
            )
            return False
        row.publish_state = "publishing"
        row.publish_attempts = int(row.publish_attempts or 0) + 1
        row.heartbeat_at = now
        publish_attempt = int(row.publish_attempts)
        payload_json = row.payload_json or "{}"
        try:
            queue_name = _receipt_queue_name(json.loads(payload_json))
        except (TypeError, ValueError, json.JSONDecodeError):
            queue_name = "receipts.fast"
        db.commit()

    try:
        process_receipt_task.apply_async(
            args=[payload_json],
            task_id=str(task_id),
            queue=queue_name,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Receipt outbox publish failed for %s", task_id)
        with get_db() as db:
            row = (
                db.query(ReceiptProcessingTask)
                .filter(ReceiptProcessingTask.task_id == str(task_id))
                .first()
            )
            if row and row.publish_state == "publishing":
                row.status = "retry"
                row.publish_state = "retry"
                row.next_retry_at = datetime.utcnow() + timedelta(
                    seconds=_retry_delay_seconds(publish_attempt)
                )
                row.last_error_kind = "broker_publish"
                row.error = str(exc)[:2000]
                db.commit()
        return False

    with get_db() as db:
        row = (
            db.query(ReceiptProcessingTask)
            .filter(ReceiptProcessingTask.task_id == str(task_id))
            .first()
        )
        if row and row.publish_state == "publishing":
            row.status = "queued"
            row.publish_state = "published"
            row.published_at = datetime.utcnow()
            row.next_retry_at = None
            row.error = None
            row.last_error_kind = None
            db.commit()
    return True


def dispatch_pending_receipt_tasks(limit: int = 100) -> dict:
    """Publish due committed outbox rows; callable from scheduler or Celery beat."""
    from sqlalchemy import or_

    from database.connection import get_db
    from database.models import ReceiptProcessingTask

    now = datetime.utcnow()
    with get_db() as db:
        task_ids = [
            str(task_id)
            for (task_id,) in (
                db.query(ReceiptProcessingTask.task_id)
                .filter(
                    ReceiptProcessingTask.publish_state.in_(["pending", "retry"]),
                    or_(
                        ReceiptProcessingTask.next_retry_at.is_(None),
                        ReceiptProcessingTask.next_retry_at <= now,
                    ),
                )
                .order_by(ReceiptProcessingTask.created_at.asc())
                .limit(max(1, min(int(limit), 500)))
                .all()
            )
        ]
    published = sum(1 for task_id in task_ids if _publish_receipt_outbox_task(task_id))
    return {"checked": len(task_ids), "published": published}


def queue_receipt_task(task_data: dict, force: bool = False) -> str:
    """Persist a receipt task before best-effort broker publication.

    The returned stable task id identifies both the DB outbox row and every
    Celery delivery. Existing active work for the same source message is reused.
    """
    from database.connection import get_db
    from database.models import ReceiptProcessingTask, Transaction

    task_data = dict(task_data or {})
    if "request_id" not in task_data:
        try:
            from core.logging_config import get_request_id

            rid = get_request_id()
            if rid:
                task_data["request_id"] = rid
        except Exception:  # noqa: BLE001
            pass

    try:
        chat_id = int(task_data.get("source_chat_id"))
        msg_id = int(task_data.get("source_message_id"))
    except (TypeError, ValueError) as exc:
        raise ValueError("source_chat_id and source_message_id are required") from exc

    payload_json = json.dumps(task_data, ensure_ascii=False)
    task_id = str(uuid4())
    now = datetime.utcnow()
    with get_db() as db:
        existing_task = (
            db.query(ReceiptProcessingTask)
            .filter(
                ReceiptProcessingTask.chat_id == chat_id,
                ReceiptProcessingTask.message_id == msg_id,
            )
            .with_for_update()
            .first()
        )
        if existing_task and existing_task.status in {"queued", "processing", "retry"}:
            return str(existing_task.task_id)

        if not force:
            existing_txn = (
                db.query(Transaction)
                .filter(
                    Transaction.source_chat_id == chat_id,
                    Transaction.source_message_id == msg_id,
                )
                .first()
            )
            if existing_txn:
                if existing_task:
                    return str(existing_task.task_id)
                raise ValueError(f"Сообщение уже обработано (транзакция #{existing_txn.id})")

        if existing_task:
            existing_task.task_id = task_id
            existing_task.status = "queued"
            existing_task.transaction_id = None
            existing_task.error = None
            existing_task.raw_message = None
            existing_task.payload_json = payload_json
            existing_task.force_reprocess = bool(force)
            existing_task.publish_state = "pending"
            existing_task.publish_attempts = 0
            existing_task.processing_attempts = 0
            existing_task.next_retry_at = now
            existing_task.heartbeat_at = None
            existing_task.published_at = None
            existing_task.started_at = None
            existing_task.finished_at = None
            existing_task.last_error_kind = None
        else:
            db.add(
                ReceiptProcessingTask(
                    task_id=task_id,
                    chat_id=chat_id,
                    message_id=msg_id,
                    status="queued",
                    payload_json=payload_json,
                    force_reprocess=bool(force),
                    publish_state="pending",
                    next_retry_at=now,
                )
            )
        # This commit is the outbox invariant: no broker publish can happen first.
        try:
            db.commit()
        except Exception as exc:  # noqa: BLE001
            from sqlalchemy.exc import IntegrityError

            if not isinstance(exc, IntegrityError):
                raise
            db.rollback()
            winner = (
                db.query(ReceiptProcessingTask)
                .filter(
                    ReceiptProcessingTask.chat_id == chat_id,
                    ReceiptProcessingTask.message_id == msg_id,
                )
                .first()
            )
            if not winner:
                raise
            return str(winner.task_id)

    _publish_receipt_outbox_task(task_id)
    return task_id


def _update_tg_message_processing(
    db,
    *,
    chat_id: int | None,
    message_id: int | None,
    status: str,
    transaction_id: int | None = None,
    error_code: str | None = None,
    error_text: str | None = None,
    duplicate_status: str | None = None,
) -> None:
    if chat_id is None or message_id is None:
        return
    from database.models import TgChatMessage

    row = (
        db.query(TgChatMessage)
        .filter(
            TgChatMessage.chat_id == int(chat_id),
            TgChatMessage.message_id == int(message_id),
        )
        .first()
    )
    if not row:
        return
    row.processing_status = status
    row.receipt_transaction_id = transaction_id
    row.processing_error_code = error_code
    row.processing_error_text = (error_text or "")[:2000] or None
    if duplicate_status is not None:
        row.duplicate_status = duplicate_status


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
    from database.models import AgentRun, AgentThread
    from services.ai_agent.authorization import (
        AgentAuthorizationError,
        current_agent_authorization,
        require_same_source_set,
    )
    from services.ai_agent.session_service import create_message, create_run_event, update_run
    from services.ai_agent.tools.cache_tools import _build_monitored_chat_sync_audit_result, _parse_datetime
    from services.incident_service import upsert_receipt_incident
    from services.telegram_cache_service import TelegramCacheService

    task_payload = json.loads(task_payload_json or "{}")
    run_id = UUID(str(task_payload.get("run_id")))
    thread_id = UUID(str(task_payload.get("thread_id")))
    try:
        with get_db() as db:
            run = db.get(AgentRun, run_id)
            thread = db.get(AgentThread, thread_id)
            if run is None or thread is None:
                raise AgentAuthorizationError("background_run_or_thread_not_found")
            if run.thread_id != thread_id or int(run.created_by_user_id) != int(thread.created_by_user_id):
                raise AgentAuthorizationError("background_run_thread_actor_mismatch")
            if run.status in {"completed", "failed", "cancelled"}:
                return {"status": run.status, "idempotent": True}

            auth = current_agent_authorization(db, run.created_by_user_id)
            auth.require_dashboard()
            try:
                stored_progress = json.loads(run.progress_json or "{}")
            except Exception:
                stored_progress = {}
            resume_state = (
                stored_progress.get("background_state")
                if isinstance(stored_progress.get("background_state"), dict)
                else {}
            )
            plan = stored_progress.get("background_authorization")
            service = TelegramCacheService(db)
            if not isinstance(plan, dict):
                payload = task_payload.get("payload") or {}
                requested_chat_ids = payload.get("chat_ids")
                monitored_ids = set(service.list_monitored_chat_ids(only_enabled=True))
                if requested_chat_ids:
                    chat_ids = require_same_source_set(auth, requested_chat_ids)
                elif auth.allowed_sources is None:
                    chat_ids = tuple(sorted(monitored_ids))
                else:
                    chat_ids = tuple(sorted(monitored_ids.intersection(auth.allowed_sources)))
                if not chat_ids or not set(chat_ids).issubset(monitored_ids):
                    raise AgentAuthorizationError("background_source_scope_invalid")

                date_from = _parse_datetime(payload.get("date_from"))
                date_to = _parse_datetime(payload.get("date_to"))
                if not auth.is_admin or (date_from is not None and date_to is not None):
                    date_from, date_to = auth.authorize_range(db, date_from, date_to)
                grace_minutes = max(0, min(int(payload.get("grace_minutes") or 5), 1440))
                estimated_candidates = max(0, int(payload.get("estimated_candidates") or 0))
                chunk_size = max(50, min(int(payload.get("chunk_size") or 500), 1000))
                plan = {
                    "actor_user_id": auth.user_id,
                    "original_permissions_version": auth.permissions_version,
                    "chat_ids": list(chat_ids),
                    "date_from": date_from.isoformat() if date_from else None,
                    "date_to": date_to.isoformat() if date_to else None,
                    "grace_minutes": grace_minutes,
                    "estimated_candidates": estimated_candidates,
                    "chunk_size": chunk_size,
                    "continuations_used": 0,
                }
                run.progress_json = json.dumps(
                    {**stored_progress, "background_authorization": plan},
                    ensure_ascii=False,
                )
                db.add(run)
                db.commit()
            else:
                if int(plan.get("actor_user_id") or 0) != auth.user_id:
                    raise AgentAuthorizationError("background_actor_changed")
                chat_ids = require_same_source_set(auth, plan.get("chat_ids") or [])
                date_from = _parse_datetime(plan.get("date_from"))
                date_to = _parse_datetime(plan.get("date_to"))
                if not auth.is_admin or (date_from is not None and date_to is not None):
                    date_from, date_to = auth.authorize_range(db, date_from, date_to)
                grace_minutes = max(0, min(int(plan.get("grace_minutes") or 5), 1440))
                estimated_candidates = max(0, int(plan.get("estimated_candidates") or 0))
                chunk_size = max(50, min(int(plan.get("chunk_size") or 500), 1000))

            continuations_used = int(plan.get("continuations_used") or 0)
            if continuations_used > BACKGROUND_AUDIT_MAX_CONTINUATIONS:
                raise ValueError("background_audit_continuation_limit_exceeded")
            if not resume_state:
                create_run_event(
                    db,
                    run_id=run_id,
                    event_type='tool_started',
                    label='Сверяю чеки',
                    status='running',
                    payload={
                        'mode': 'background',
                        'date_from': plan.get('date_from'),
                        'date_to': plan.get('date_to'),
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

            summary = service.audit_monitored_chats_chunked(
                chat_ids=chat_ids,
                date_from=date_from,
                date_to=date_to,
                grace_minutes=grace_minutes,
                chunk_size=chunk_size,
                resume_state=resume_state,
                max_chunks=BACKGROUND_AUDIT_MAX_CHUNKS_PER_TASK,
                issue_callback=_issue_to_incident,
            )
            processed_messages = int(summary.get('processed_messages') or 0)
            if processed_messages > BACKGROUND_AUDIT_MAX_TOTAL_MESSAGES:
                db.rollback()
                raise ValueError("background_audit_message_limit_exceeded")

            # Authorization is reloaded after the chunk and immediately before
            # incident publication. Revocation rolls the pending incidents back.
            current_auth = current_agent_authorization(db, auth.user_id)
            current_sources = require_same_source_set(current_auth, plan.get("chat_ids") or [])
            if tuple(chat_ids) != current_sources:
                db.rollback()
                raise AgentAuthorizationError("background_source_scope_changed")
            if date_from is not None and date_to is not None:
                current_auth.authorize_range(db, date_from, date_to)
            db.commit()

            progress_payload = {
                'mode': 'background',
                'phase': summary.get('phase') or ('completed' if summary.get('complete') else 'scan_chunk'),
                'current_chat_id': summary.get('current_chat_id'),
                'processed_messages': processed_messages,
                'total_estimated_messages': int(summary.get('total_estimated_messages') or estimated_candidates),
                'issues_found': int(summary.get('total_issues') or 0),
                'completed_chat_ids': summary.get('completed_chat_ids') or [],
                'cursor': summary.get('cursor'),
                'started_from_latest': True,
                'categories': summary.get('categories') or {},
                'percent': int(summary.get('percent') or 0),
                'background_authorization': plan,
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
                continuations_used += 1
                if continuations_used > BACKGROUND_AUDIT_MAX_CONTINUATIONS:
                    raise ValueError("background_audit_continuation_limit_exceeded")
                plan = {**plan, "continuations_used": continuations_used}
                next_state = {
                    'monitored_ids': list(chat_ids),
                    'completed_chat_ids': [
                        int(item)
                        for item in (summary.get('completed_chat_ids') or [])
                        if int(item) in set(chat_ids)
                    ],
                    'seen_chat_ids': [
                        int(item)
                        for item in (summary.get('seen_chat_ids') or [])
                        if int(item) in set(chat_ids)
                    ],
                    'cursor': summary.get('cursor'),
                    'processed_messages': processed_messages,
                    'total_estimated_messages': int(summary.get('total_estimated_messages') or estimated_candidates),
                    'total_issues': int(summary.get('total_issues') or 0),
                    'categories': summary.get('categories') or {},
                    'by_chat': [
                        item
                        for item in (summary.get('by_chat') or [])
                        if int(item.get('chat_id') or 0) in set(chat_ids)
                    ],
                    'issues_preview': summary.get('issues_preview') or [],
                    'top_actionable_cases': summary.get('top_actionable_cases') or [],
                }
                cursor = next_state.get('cursor')
                if isinstance(cursor, dict) and int(cursor.get('chat_id') or 0) not in set(chat_ids):
                    next_state['cursor'] = None
                progress_payload["background_authorization"] = plan
                progress_payload["background_state"] = next_state
                update_run(
                    db,
                    run_id=run_id,
                    status='processing',
                    progress=progress_payload,
                    requires_confirmation=False,
                )
                next_payload = {
                    'run_id': str(run_id),
                    'thread_id': str(thread_id),
                }
                run_agent_monitored_chat_sync_audit_task.apply_async(
                    args=[json.dumps(next_payload, ensure_ascii=False)],
                    countdown=max(0, BACKGROUND_AUDIT_REQUEUE_DELAY_SECONDS),
                )
                return progress_payload

            final_auth = current_agent_authorization(db, auth.user_id)
            final_sources = require_same_source_set(final_auth, plan.get("chat_ids") or [])
            if tuple(chat_ids) != final_sources:
                raise AgentAuthorizationError("background_source_scope_changed")
            if date_from is not None and date_to is not None:
                final_auth.authorize_range(db, date_from, date_to)
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


def _authorize_deferred_receipt_task(
    db,
    task_data: dict,
    *,
    transaction=None,
    parsed_date=None,
):
    """Revalidate actor-bound reparse jobs immediately before mutation."""
    action = str(task_data.get("requested_action") or "").strip()
    if not action:
        return None
    if action != "agent_receipt_reparse":
        raise ValueError("deferred_receipt_action_invalid")

    from services.ai_agent.authorization import current_agent_authorization

    try:
        actor_user_id = int(task_data.get("requested_by_user_id"))
        source_chat_id = int(task_data.get("source_chat_id"))
        source_message_id = int(task_data.get("source_message_id"))
        original_chat_id = int(task_data.get("original_source_chat_id"))
        original_message_id = int(task_data.get("original_source_message_id"))
    except (TypeError, ValueError) as exc:
        raise ValueError("deferred_receipt_authorization_invalid") from exc
    if (source_chat_id, source_message_id) != (original_chat_id, original_message_id):
        raise ValueError("deferred_receipt_source_changed")

    auth = current_agent_authorization(db, actor_user_id)
    auth.require_dashboard()
    auth.authorize_chat(original_chat_id)
    if transaction is not None:
        auth.authorize_transaction(db, transaction, proposed_date=parsed_date)
    elif parsed_date is not None:
        auth.authorize_date(db, parsed_date)
    return auth


@app.task(name='process_receipt', bind=True, max_retries=3)
def process_receipt_task(self, task_data_json: str):
    """
    Process a single receipt from the queue
    
    Args:
        task_data_json: JSON string containing receipt data
    """
    from database.connection import get_db
    from database.models import (
        AccessAuditLog,
        DuplicateSuggestion,
        MonitoredBotChat,
        OperatorReference,
        ParsingLog,
        ReceiptProcessingTask,
        TgChatMessage,
        Transaction,
    )
    from parsers.parser_orchestrator import ParserOrchestrator
    
    try:
        celery_task_id = self.request.id
        # Parse task data
        task_data = json.loads(task_data_json)
        # Restore request_id (set by HTTP middleware on the API side) so log
        # lines emitted from the worker carry the same correlation id.
        try:
            from core.logging_config import set_request_id

            rid = task_data.get("request_id")
            if rid:
                set_request_id(str(rid))
        except Exception:  # noqa: BLE001
            pass
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
            deferred_auth = _authorize_deferred_receipt_task(db, task_data)
            if deferred_auth is not None and source_chat_id and source_message_id:
                cached_date = (
                    db.query(TgChatMessage.message_date)
                    .filter(
                        TgChatMessage.chat_id == int(source_chat_id),
                        TgChatMessage.message_id == int(source_message_id),
                    )
                    .scalar()
                )
                if cached_date is not None:
                    deferred_auth.authorize_date(db, cached_date)
            # Update tracking -> processing
            tracking = None
            force_reprocess = False
            existing_source_transaction = None
            force_before_snapshot = None
            if source_chat_id and source_message_id:
                tracking = (
                    db.query(ReceiptProcessingTask)
                    .filter(ReceiptProcessingTask.task_id == celery_task_id)
                    .first()
                )
                if tracking:
                    if tracking.status == "dead":
                        return {"success": False, "error": "task_is_dead"}
                    force_reprocess = bool(tracking.force_reprocess)
                    tracking.status = 'processing'
                    tracking.error = None
                    tracking.processing_attempts = int(tracking.processing_attempts or 0) + 1
                    tracking.started_at = tracking.started_at or datetime.utcnow()
                    tracking.heartbeat_at = datetime.utcnow()
                    tracking.last_error_kind = None
                    _update_tg_message_processing(
                        db,
                        chat_id=tracking.chat_id,
                        message_id=tracking.message_id,
                        status="processing",
                    )
                    db.commit()

                    is_auto_source = str(source_type or "").upper() in {
                        "AUTO",
                        "USERBOT",
                    }
                    skip_reason = None
                    if is_auto_source:
                        monitored = db.get(MonitoredBotChat, int(tracking.chat_id))
                        if monitored is None or not monitored.enabled:
                            skip_reason = "unmonitored_source"
                        source_datetime = _task_fallback_datetime(task_data)
                        if source_datetime is None:
                            source_datetime = (
                                db.query(TgChatMessage.message_date)
                                .filter(
                                    TgChatMessage.chat_id == int(tracking.chat_id),
                                    TgChatMessage.message_id == int(tracking.message_id),
                                )
                                .scalar()
                            )
                        if source_datetime is None:
                            skip_reason = skip_reason or "missing_source_date"
                        elif source_datetime < receipt_min_datetime():
                            skip_reason = skip_reason or "source_before_date_cutoff"

                    if skip_reason:
                        tracking.status = "done"
                        tracking.publish_state = "done"
                        tracking.error = f"skipped:{skip_reason}"
                        tracking.finished_at = datetime.utcnow()
                        tracking.heartbeat_at = datetime.utcnow()
                        tracking.last_error_kind = skip_reason
                        _update_tg_message_processing(
                            db,
                            chat_id=tracking.chat_id,
                            message_id=tracking.message_id,
                            status="done",
                            error_code=skip_reason,
                            error_text=tracking.error,
                        )
                        db.commit()
                        return {
                            "success": True,
                            "skipped": True,
                            "reason": skip_reason,
                        }
                    try:
                        receipt_logger.log_received(
                            task_id=int(tracking.id),
                            chat_id=tracking.chat_id,
                            chat_title=str(tracking.chat_id) if tracking.chat_id else None,
                            message_id=tracking.message_id,
                        )
                    except Exception:  # noqa: BLE001
                        logger.debug("receipt_logger.log_received failed", exc_info=True)

            if is_metadata_only_chat(source_chat_id):
                if tracking:
                    tracking.status = "done"
                    tracking.transaction_id = None
                    tracking.error = "metadata_only_chat_skipped"
                    tracking.finished_at = datetime.utcnow()
                    tracking.heartbeat_at = datetime.utcnow()
                    tracking.last_error_kind = "metadata_only"
                    _update_tg_message_processing(
                        db,
                        chat_id=tracking.chat_id,
                        message_id=tracking.message_id,
                        status="done",
                        error_code="metadata_only",
                        error_text="metadata_only_chat_skipped",
                    )
                    db.commit()
                return {"success": True, "skipped": True, "reason": "metadata_only_chat"}

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
                        if force_reprocess:
                            existing_source_transaction = existing
                            force_before_snapshot = {
                                key: str(getattr(existing, key, None))
                                for key in (
                                    "transaction_date", "amount", "currency", "card_last_4",
                                    "operator_raw", "application_mapped", "transaction_type",
                                    "balance_after", "receiver_name", "receiver_card",
                                    "parsing_method", "parsing_confidence", "fingerprint",
                                )
                            }
                        else:
                            processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
                            if tracking:
                                tracking.status = 'done'
                                tracking.transaction_id = existing.id
                                tracking.finished_at = datetime.utcnow()
                                tracking.heartbeat_at = datetime.utcnow()
                                _update_tg_message_processing(
                                    db,
                                    chat_id=tracking.chat_id,
                                    message_id=tracking.message_id,
                                    status="done",
                                    transaction_id=int(existing.id),
                                    duplicate_status="source_duplicate",
                                )
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
                    if tracking:
                        tracking.heartbeat_at = datetime.utcnow()
                        db.commit()
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
                    if tracking:
                        tracking.heartbeat_at = datetime.utcnow()
                        db.commit()
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
                parsed_data = orchestrator.process(
                    raw_text,
                    fallback_datetime=_task_fallback_datetime(task_data),
                )
            if tracking:
                tracking.heartbeat_at = datetime.utcnow()
                db.commit()

            processing_time = int((datetime.now() - start_time).total_seconds() * 1000)
            
            if not parsed_data:
                reason = getattr(orchestrator, "last_rejection_reason", None) or "unknown"
                error_message = f"Parsing returned None: {reason}"
                transient_rejection = "ai_transient" in str(reason).lower()
                log = ParsingLog(
                    raw_message=raw_text,
                    success=False,
                    error_message=error_message,
                    processing_time_ms=processing_time
                )
                db.add(log)
                if tracking:
                    tracking.error = error_message
                    tracking.raw_message = (raw_text or "")[:4000] if raw_text else None
                    tracking.heartbeat_at = datetime.utcnow()
                    attempts = int(tracking.processing_attempts or 0)
                    if transient_rejection and attempts < RECEIPT_MAX_PROCESSING_ATTEMPTS:
                        rejection_state = "retry"
                        tracking.status = "retry"
                        tracking.publish_state = "retry"
                        tracking.next_retry_at = datetime.utcnow() + timedelta(
                            seconds=_retry_delay_seconds(attempts)
                        )
                        tracking.last_error_kind = "ai_transient"
                    else:
                        rejection_state = "dead"
                        tracking.status = "dead"
                        tracking.publish_state = "dead"
                        tracking.finished_at = datetime.utcnow()
                        tracking.next_retry_at = None
                        tracking.last_error_kind = "parser_rejected"
                    _update_tg_message_processing(
                        db,
                        chat_id=tracking.chat_id,
                        message_id=tracking.message_id,
                        status=rejection_state,
                        error_code=str(tracking.last_error_kind),
                        error_text=error_message,
                    )
                db.commit()
                try:
                    receipt_logger.log_failed(
                        task_id=int(tracking.id) if tracking else None,
                        chat_id=tracking.chat_id if tracking else None,
                        chat_title=str(tracking.chat_id) if tracking and tracking.chat_id else None,
                        message_id=tracking.message_id if tracking else None,
                        rejection_reason=reason,
                        error_summary=error_message,
                        ocr_preview=raw_text,
                        duration_seconds=processing_time / 1000.0,
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("receipt_logger.log_failed failed", exc_info=True)
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
                    db.commit()
                    if rejection_state == "dead":
                        _push_to_dlq(
                            celery_task_id=celery_task_id,
                            task_data_json=task_data_json,
                            error=ValueError(error_message),
                            tb_text="",
                            retries=int(tracking.processing_attempts or 0),
                            reason="parser_rejected",
                        )
                logger.warning("Parsing failed for receipt: %s", reason)
                if transient_rejection and not tracking:
                    raise RuntimeError(error_message)
                return {
                    'success': False,
                    'error': error_message,
                    'state': rejection_state if tracking else 'dead',
                }

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
            if tx_datetime < receipt_min_datetime():
                if tracking:
                    tracking.status = "done"
                    tracking.publish_state = "done"
                    tracking.error = "skipped:transaction_before_date_cutoff"
                    tracking.finished_at = datetime.utcnow()
                    tracking.heartbeat_at = datetime.utcnow()
                    tracking.last_error_kind = "transaction_before_date_cutoff"
                    _update_tg_message_processing(
                        db,
                        chat_id=tracking.chat_id,
                        message_id=tracking.message_id,
                        status="done",
                        error_code="transaction_before_date_cutoff",
                        error_text=tracking.error,
                    )
                    db.commit()
                return {
                    "success": True,
                    "skipped": True,
                    "reason": "transaction_before_date_cutoff",
                }
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
                transaction_type=transaction_type,
            )
            fp = fp_candidates[0]

            # A fingerprint is intentionally fuzzy. Keep the nearest match only
            # to create a reconciliation suggestion after inserting this source.
            fingerprint_candidate = (
                db.query(Transaction)
                .filter(Transaction.fingerprint.in_(fp_candidates))
                .filter(
                    Transaction.id != existing_source_transaction.id
                    if existing_source_transaction is not None
                    else True
                )
                .order_by(Transaction.id.asc())
                .first()
            )

            transaction_values = {
                "raw_message": raw_text,
                "source_type": tx_source_type,
                "source_chat_id": chat_id_int,
                "source_message_id": msg_id_int,
                "transaction_date": tx_datetime,
                "amount": store_amount,
                "currency": currency,
                "card_last_4": str(card_last4)[-4:] if card_last4 else None,
                "operator_raw": operator,
                "application_mapped": app_name,
                "receiver_name": parsed_data.get("receiver_name"),
                "receiver_card": parsed_data.get("receiver_card"),
                "transaction_type": transaction_type,
                "balance_after": balance,
                "is_p2p": is_p2p,
                "is_gpt_parsed": is_gpt_parsed_flag,
                "parsing_confidence": confidence_value,
                "parsing_method": method_value,
                "fingerprint": fp,
            }
            _authorize_deferred_receipt_task(
                db,
                task_data,
                transaction=existing_source_transaction,
                parsed_date=tx_datetime,
            )
            if existing_source_transaction is not None:
                transaction = existing_source_transaction
                for key, value in transaction_values.items():
                    setattr(transaction, key, value)
                force_after_snapshot = {
                    key: str(getattr(transaction, key, None))
                    for key in (force_before_snapshot or {}).keys()
                }
                db.add(
                    AccessAuditLog(
                        action="receipt_force_reparse",
                        success=True,
                        details_json=json.dumps(
                            {
                                "transaction_id": int(transaction.id),
                                "chat_id": chat_id_int,
                                "message_id": msg_id_int,
                                "before": force_before_snapshot or {},
                                "after": force_after_snapshot,
                                "worker_task_id": str(celery_task_id),
                            },
                            ensure_ascii=False,
                        ),
                    )
                )
                db.commit()
                db.refresh(transaction)
            else:
                transaction = Transaction(**transaction_values)
                db.add(transaction)
                try:
                    db.commit()
                except Exception as exc:  # noqa: BLE001
                    from sqlalchemy.exc import IntegrityError as _IntegrityError
                    if isinstance(exc, _IntegrityError):
                        db.rollback()
                        logger.info(
                            "Race-condition duplicate detected on commit; resolving by source identity",
                        )
                        existing = None
                        if chat_id_int is not None and msg_id_int is not None:
                            existing = (
                                db.query(Transaction)
                                .filter(
                                    Transaction.source_chat_id == chat_id_int,
                                    Transaction.source_message_id == msg_id_int,
                                )
                                .first()
                            )
                        if existing is not None:
                            if tracking:
                                tracking.status = 'done'
                                tracking.transaction_id = existing.id
                                tracking.error = None
                                tracking.finished_at = datetime.utcnow()
                                tracking.heartbeat_at = datetime.utcnow()
                                _update_tg_message_processing(
                                    db,
                                    chat_id=tracking.chat_id,
                                    message_id=tracking.message_id,
                                    status="done",
                                    transaction_id=int(existing.id),
                                    duplicate_status="source_race_duplicate",
                                )
                                db.commit()
                            return {
                                'success': True,
                                'duplicate': True,
                                'transaction_id': str(existing.uuid),
                                'id': existing.id,
                            }
                    raise

            if fingerprint_candidate and fingerprint_candidate.id != transaction.id:
                try:
                    suggestion_task_id = UUID(str(celery_task_id)) if celery_task_id else None
                except (TypeError, ValueError):
                    suggestion_task_id = None
                db.add(
                    DuplicateSuggestion(
                        task_id=suggestion_task_id,
                        primary_transaction_id=int(fingerprint_candidate.id),
                        duplicate_transaction_id=int(transaction.id),
                        confidence=0.6,
                        reasoning="fuzzy_fingerprint_match_requires_review",
                        payload_json=json.dumps(
                            {"fingerprint": fp, "candidates": fp_candidates},
                            ensure_ascii=False,
                        ),
                    )
                )
                try:
                    db.commit()
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to persist duplicate suggestion")
                    db.rollback()
                _update_tg_message_processing(
                    db,
                    chat_id=chat_id_int,
                    message_id=msg_id_int,
                    status="processing",
                    duplicate_status="candidate",
                )

            if tracking:
                tracking.status = 'done'
                tracking.transaction_id = transaction.id
                tracking.error = None
                tracking.finished_at = datetime.utcnow()
                tracking.heartbeat_at = datetime.utcnow()
                _update_tg_message_processing(
                    db,
                    chat_id=tracking.chat_id,
                    message_id=tracking.message_id,
                    status="done",
                    transaction_id=int(transaction.id),
                )
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
            try:
                from services import metrics as _metrics

                _metrics.inc(
                    "receipts_processed_total",
                    labels={
                        "status": "ok",
                        "method": transaction.parsing_method or "UNKNOWN",
                    },
                )
                _metrics.observe(
                    "receipt_processing_duration_ms",
                    processing_time,
                    labels={"status": "ok"},
                )
            except Exception:  # noqa: BLE001
                pass
            try:
                receipt_logger.log_processed(
                    task_id=int(tracking.id) if tracking else None,
                    transaction_id=transaction.id,
                    chat_id=transaction.source_chat_id,
                    chat_title=str(transaction.source_chat_id) if transaction.source_chat_id else None,
                    message_id=transaction.source_message_id,
                    amount=transaction.amount,
                    currency=transaction.currency,
                    transaction_date=transaction.transaction_date,
                    operator=transaction.operator_raw,
                    receiver_name=transaction.receiver_name,
                    sender_card=transaction.card_last_4,
                    receiver_card=transaction.receiver_card,
                    parsing_method=transaction.parsing_method,
                    parsing_confidence=float(transaction.parsing_confidence) if transaction.parsing_confidence is not None else None,
                    is_p2p=bool(transaction.is_p2p),
                    duration_seconds=processing_time / 1000.0,
                    ocr_preview=raw_text,
                )
            except Exception:  # noqa: BLE001
                logger.debug("receipt_logger.log_processed failed", exc_info=True)

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

        import traceback as _traceback
        tb_text = _traceback.format_exc()

        durable_state = None
        durable_attempts = 0
        terminal_error = _is_terminal_worker_error(e)
        try:
            with get_db() as db:
                tracking = (
                    db.query(ReceiptProcessingTask)
                    .filter(ReceiptProcessingTask.task_id == getattr(self.request, "id", None))
                    .first()
                )
                if tracking:
                    tracking.error = str(e)
                    _rt = raw_text if 'raw_text' in locals() else ''
                    tracking.raw_message = (_rt or "")[:4000] if _rt else None
                    tracking.heartbeat_at = datetime.utcnow()
                    durable_attempts = int(tracking.processing_attempts or 0)
                    if terminal_error or durable_attempts >= RECEIPT_MAX_PROCESSING_ATTEMPTS:
                        durable_state = "dead"
                        tracking.status = "dead"
                        tracking.publish_state = "dead"
                        tracking.finished_at = datetime.utcnow()
                        tracking.next_retry_at = None
                        tracking.last_error_kind = (
                            "terminal" if terminal_error else "processing_exhausted"
                        )
                    else:
                        durable_state = "retry"
                        tracking.status = "retry"
                        tracking.publish_state = "retry"
                        tracking.next_retry_at = datetime.utcnow() + timedelta(
                            seconds=_retry_delay_seconds(durable_attempts)
                        )
                        tracking.last_error_kind = "transient_worker"
                    _update_tg_message_processing(
                        db,
                        chat_id=tracking.chat_id,
                        message_id=tracking.message_id,
                        status=str(durable_state),
                        error_code=str(tracking.last_error_kind),
                        error_text=str(e),
                    )
                    register_receipt_incident(
                        db,
                        chat_id=tracking.chat_id,
                        message_id=tracking.message_id,
                        task_id=int(tracking.id),
                        incident_type='failed_parse',
                        reason_code='worker_exception',
                        reason_text=str(e),
                        payload={
                            'raw_text': (_rt or '')[:1000],
                            'traceback': tb_text[:6000],
                        },
                    )
                log = ParsingLog(
                    raw_message=raw_text if 'raw_text' in locals() else '',
                    success=False,
                    error_message=str(e)
                )
                db.add(log)
                db.commit()
                # Push to Telegram log channel
                try:
                    receipt_logger.log_failed(
                        task_id=int(tracking.id) if tracking else None,
                        chat_id=tracking.chat_id if tracking else None,
                        chat_title=str(tracking.chat_id) if tracking and tracking.chat_id else None,
                        message_id=tracking.message_id if tracking else None,
                        rejection_reason='worker_exception',
                        error_summary=str(e)[:300],
                        ocr_preview=(raw_text if 'raw_text' in locals() else None),
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("receipt_logger.log_failed (worker exc) failed", exc_info=True)
        except Exception:
            logger.exception("Failed to record worker failure")

        if durable_state == "dead":
            _push_to_dlq(
                celery_task_id=getattr(self.request, "id", None),
                task_data_json=task_data_json,
                error=e,
                tb_text=tb_text if 'tb_text' in locals() else "",
                retries=durable_attempts,
                reason="terminal" if terminal_error else "processing_exhausted",
            )
            return {"success": False, "error": str(e)[:300], "state": "dead"}
        if durable_state == "retry":
            return {"success": False, "error": str(e)[:300], "state": "retry"}

        # Legacy direct .delay() callers have no durable row. Preserve bounded
        # Celery retry behavior for them until all callers use queue_receipt_task.
        retry_count = self.request.retries or 0
        countdown = _retry_delay_seconds(retry_count + 1)
        if terminal_error:
            _push_to_dlq(
                celery_task_id=getattr(self.request, "id", None),
                task_data_json=task_data_json,
                error=e,
                tb_text=tb_text if 'tb_text' in locals() else "",
                retries=retry_count,
                reason="terminal_untracked",
            )
            return {"success": False, "error": str(e)[:300], "state": "dead"}
        try:
            raise self.retry(exc=e, countdown=countdown)
        except Exception as retry_exc:  # noqa: BLE001
            # MaxRetriesExceededError or other failure to enqueue retry — push DLQ.
            from celery.exceptions import MaxRetriesExceededError as _MaxRetries

            if isinstance(retry_exc, _MaxRetries):
                _push_to_dlq(
                    celery_task_id=getattr(self.request, "id", None),
                    task_data_json=task_data_json,
                    error=e,
                    tb_text=tb_text if 'tb_text' in locals() else "",
                    retries=retry_count,
                    reason="max_retries",
                )
                return {"success": False, "error": "max_retries_exceeded"}
            raise


def _push_to_dlq(
    *,
    celery_task_id: Optional[str],
    task_data_json: str,
    error: BaseException,
    tb_text: str,
    retries: int,
    reason: str,
) -> None:
    """Persist one terminal receipt failure through the ORM-backed DLQ."""
    try:
        from database.connection import get_db
        from database.models import ReceiptProcessingTask, ReceiptTaskDLQ

        chat_id = None
        message_id = None
        try:
            d = json.loads(task_data_json or "{}") or {}
            chat_id = d.get("source_chat_id")
            message_id = d.get("source_message_id")
            chat_id = int(chat_id) if chat_id is not None else None
            message_id = int(message_id) if message_id is not None else None
        except Exception:  # noqa: BLE001
            pass
        with get_db() as db:
            stable_task_id = str(celery_task_id or "")[:255] or "unknown"
            existing = (
                db.query(ReceiptTaskDLQ)
                .filter(ReceiptTaskDLQ.task_id == stable_task_id)
                .order_by(ReceiptTaskDLQ.id.desc())
                .first()
            )
            tracking = (
                db.query(ReceiptProcessingTask)
                .filter(ReceiptProcessingTask.task_id == stable_task_id)
                .first()
            )
            values = {
                "tracking_task_id": int(tracking.id) if tracking else None,
                "chat_id": chat_id,
                "message_id": message_id,
                "payload_json": (task_data_json or "{}")[:50000],
                "error_text": str(error)[:2000],
                "traceback": (tb_text or "")[:6000],
                "retries": int(retries),
                "reason": str(reason)[:40],
            }
            if existing:
                for key, value in values.items():
                    setattr(existing, key, value)
            else:
                db.add(ReceiptTaskDLQ(task_id=stable_task_id, **values))
            db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to push to receipt_task_dlq")


def _is_terminal_worker_error(exc: BaseException) -> bool:
    """Decide whether retry is pointless for this exception class."""
    name = type(exc).__name__
    # Pydantic validation errors won't change on retry
    if name in {"ValidationError", "ValueError"}:
        return True
    # HTTP 4xx auth/permission/not-found from internal API
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    if isinstance(status, int) and status in (400, 401, 403, 404):
        return True
    return False


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


@app.task(name='agent_run_watchdog_sweep')
def agent_run_watchdog_sweep_task():
    """Mark agent runs that exceeded their soft deadline as failed."""
    from services.ai_agent.run_watchdog import sweep_stuck_runs

    result = sweep_stuck_runs()
    if result.get("swept"):
        logger.warning("Agent run watchdog swept %s runs: %s", result["swept"], result["ids"])
    return result


@app.task(name='receipt_task_watchdog_sweep')
def receipt_task_watchdog_sweep_task():
    """Recover stuck receipt tasks and publish due outbox work."""
    from services.receipt_watchdog import sweep_stuck_receipt_tasks

    return sweep_stuck_receipt_tasks()


@app.task(name='receipt_outbox_dispatch')
def receipt_outbox_dispatch_task():
    """Publish committed receipt outbox rows that are ready for delivery."""
    return dispatch_pending_receipt_tasks()


@app.task(name='receipt_task_retention_cleanup')
def receipt_task_retention_cleanup_task():
    """Delete done receipt tasks older than retention window (default 30d)."""
    from services.receipt_watchdog import cleanup_old_receipt_tasks

    return cleanup_old_receipt_tasks()


@app.task(name='monitored_chat_sync_tick')
def monitored_chat_sync_tick_task():
    """Sync new messages from active monitored chats into tg_chat_messages.

    The TDLib fetch is injected via a thin wrapper that prefers the in-process
    `TelegramTDLibManager`; if unavailable, the task no-ops gracefully.
    """
    import asyncio

    async def _fetch(chat_id: int, from_message_id: int, limit: int):
        try:
            from services.telegram_tdlib_manager import get_tdlib_manager
        except Exception:  # noqa: BLE001
            logger.warning("TDLib manager unavailable, skipping chat %s", chat_id)
            return []
        try:
            mgr = get_tdlib_manager()
            # Use get_messages — it returns {"items": [...raw tdlib dicts...], "total": N}.
            # Pass limit + from_message_id (0 means latest). For monitored sync we always
            # walk back from the latest, so callers should pass from_message_id=0.
            resp = await mgr.get_messages(
                chat_id=chat_id,
                from_message_id=from_message_id or 0,
                limit=min(int(limit or 100), 100),
            )
            return resp.get("items") or []
        except Exception:  # noqa: BLE001
            logger.exception("monitored_chat fetch failed for chat %s", chat_id)
            return []

    try:
        from services.monitored_chat_sync import sync_all_active_chats
    except Exception as exc:  # noqa: BLE001
        logger.warning("monitored_chat_sync module not loaded: %s", exc)
        return {"skipped": True, "reason": "module_missing"}

    try:
        result = asyncio.run(sync_all_active_chats(fetch_callable=_fetch))
    except RuntimeError:
        # Already inside an event loop — fall back to creating a new one
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(sync_all_active_chats(fetch_callable=_fetch))
        finally:
            loop.close()
    return {"chats": result}


@app.task(name='agent_weekly_publish')
def agent_weekly_publish_task():
    """Publish the weekly health-check digest into the configured Telegram channel."""
    import asyncio

    try:
        from services.ai_agent.weekly_publisher import publish_weekly_report
    except Exception as exc:  # noqa: BLE001
        logger.warning("weekly_publisher not loaded: %s", exc)
        return {"published": False, "reason": "module_missing"}

    try:
        result = asyncio.run(publish_weekly_report())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(publish_weekly_report())
        finally:
            loop.close()
    logger.info("Weekly publish result: %s", result)
    return result
