"""
Reconciliation Agent — compares synced chat history against parsed transactions.

Reads from PostgreSQL ``tg_chat_messages`` (not TDLib), classifies every
receipt-candidate message into one of four categories:

- **MATCHED** — a transaction already exists for this message
- **MISSING_IN_DB** — looks like a receipt but no transaction found → can auto-parse
- **FAILED_PARSE** — was processed but resulted in an error
- **ORPHANED_IN_DB** — transaction exists but the source message is missing from history
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from database.connection import get_db_session, SessionLocal
from database.models import (
    AutomationTask,
    ReceiptProcessingTask,
    TgChatMessage,
    TgHistoryCursor,
    Transaction,
)
from api.dependencies import require_tab_access
from services.message_utils import (
    looks_like_receipt,
    format_tdlib_message,
    build_task_data_from_message,
)
from workers.celery_worker import queue_receipt_task

router = APIRouter(
    prefix="/api/automation/reconciliation",
    tags=["automation"],
    dependencies=[Depends(require_tab_access("automation"))],
)
logger = logging.getLogger(__name__)


# ── Pydantic models ──────────────────────────────────────────────────────────

class ReconcileRequest(BaseModel):
    period_start: str = Field(..., description="ISO date, e.g. 2026-02-01")
    period_end: str = Field(..., description="ISO date, e.g. 2026-02-18")
    bot_chat_ids: List[int] = Field(..., min_length=1)
    auto_parse: bool = False
    source: Literal["local", "tdlib"] = "local"
    sync_if_needed: bool = True


class ReconcileResponse(BaseModel):
    task_id: UUID
    status: str  # started | empty | sync_required
    message: str
    sync_warnings: Optional[List[Dict[str, Any]]] = None


class ReconciliationItem(BaseModel):
    message_id: int
    chat_id: int
    message_date: Optional[str] = None
    text_preview: Optional[str] = None
    category: str  # MATCHED | MISSING_IN_DB | FAILED_PARSE | ORPHANED_IN_DB
    transaction_id: Optional[int] = None
    can_auto_parse: bool = False


class ReconciliationSummary(BaseModel):
    total_receipt_candidates: int = 0
    matched: int = 0
    missing_in_db: int = 0
    failed_parse: int = 0
    orphaned_in_db: int = 0


class ReconcileStatusResponse(BaseModel):
    task_id: UUID
    status: str
    progress: Optional[Dict[str, Any]] = None


class ReconcileResultsResponse(BaseModel):
    task_id: UUID
    status: str
    summary: Optional[ReconciliationSummary] = None
    items: List[ReconciliationItem] = []
    total_items: int = 0
    sync_warnings: Optional[List[Dict[str, Any]]] = None


class ChatSyncStatusItem(BaseModel):
    chat_id: int
    status: str  # completed | loading | idle | error | not_started
    loaded_count: int = 0
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class AutoParseResponse(BaseModel):
    queued: int = 0
    skipped: int = 0
    errors: int = 0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _update_task_atomic(
    session: Session,
    task_id: UUID,
    *,
    expected_status: Optional[str] = None,
    **values: Any,
) -> bool:
    """Optimistic-lock update of an ``AutomationTask``."""
    update_payload = dict(values)
    update_payload["version"] = AutomationTask.version + 1
    query = session.query(AutomationTask).filter(AutomationTask.id == task_id)
    if expected_status:
        query = query.filter(AutomationTask.status == expected_status)
    updated = query.update(update_payload, synchronize_session=False)
    session.commit()
    return bool(updated)


async def _run_background_task(task_id: UUID, task_name: str, coro) -> None:
    logger.debug("Starting background task '%s'", task_name)
    try:
        await coro
        logger.debug("Background task '%s' finished successfully", task_name)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background task '%s' crashed", task_name)
        try:
            with SessionLocal() as db:
                _update_task_atomic(
                    db,
                    task_id,
                    expected_status="processing",
                    status="failed",
                    result_json=json.dumps({"error": str(exc)[:500]}),
                )
        except Exception:
            pass


def _parse_date(s: str) -> datetime:
    """Parse ISO date string into datetime."""
    return datetime.fromisoformat(s)


def _text_preview(text: Optional[str], max_len: int = 120) -> Optional[str]:
    if not text:
        return None
    return text[:max_len] + ("..." if len(text) > max_len else "")


# ── Background reconciliation logic ──────────────────────────────────────────

async def _process_reconciliation(
    task_id: UUID,
    chat_ids: List[int],
    period_start: datetime,
    period_end: datetime,
    auto_parse: bool,
    sync_warnings: List[Dict[str, Any]],
) -> None:
    """Core reconciliation algorithm (runs in background)."""

    with SessionLocal() as db:
        # Step 1: Progress update
        _update_task_atomic(
            db, task_id,
            expected_status="processing",
            progress_json=json.dumps({
                "step": "loading_messages",
                "percent": 10,
            }),
        )

        # Step 2: Fetch history messages in the period
        messages = (
            db.query(TgChatMessage)
            .filter(
                TgChatMessage.chat_id.in_(chat_ids),
                TgChatMessage.message_date >= period_start,
                TgChatMessage.message_date <= period_end + timedelta(days=1),
            )
            .order_by(TgChatMessage.message_date.desc())
            .all()
        )

        # Step 3: Filter receipt candidates
        receipt_candidates: List[TgChatMessage] = []
        for msg in messages:
            text = msg.text or ""
            raw = msg.raw_json or ""
            if looks_like_receipt(text, raw):
                receipt_candidates.append(msg)

        _update_task_atomic(
            db, task_id,
            expected_status="processing",
            progress_json=json.dumps({
                "step": "matching",
                "percent": 40,
                "total_messages": len(messages),
                "receipt_candidates": len(receipt_candidates),
            }),
        )

        # Step 4: Build lookup of existing transactions by (chat_id, message_id)
        tx_lookup: Dict[tuple, int] = {}
        if receipt_candidates:
            # Collect all unique (chat_id, message_id) pairs
            candidate_pairs = [
                (int(m.chat_id), int(m.message_id))
                for m in receipt_candidates
            ]
            # Query existing transactions for these sources
            for cid, mid in candidate_pairs:
                tx = (
                    db.query(Transaction.id)
                    .filter(
                        Transaction.source_chat_id == cid,
                        Transaction.source_message_id == mid,
                    )
                    .first()
                )
                if tx:
                    tx_lookup[(cid, mid)] = tx[0]

        # Step 5: Also check receipt_transaction_id linkage
        linked_lookup: Dict[tuple, int] = {}
        for m in receipt_candidates:
            if m.receipt_transaction_id:
                linked_lookup[(int(m.chat_id), int(m.message_id))] = int(m.receipt_transaction_id)

        # Step 6: Check for failed processing tasks (single bulk query, no N+1).
        failed_lookup: Dict[tuple, str] = {}
        if receipt_candidates and candidate_pairs:
            from sqlalchemy import tuple_

            int_pairs = []
            for cid, mid in candidate_pairs:
                try:
                    int_pairs.append((int(cid), int(mid)))
                except (TypeError, ValueError):
                    continue
            if int_pairs:
                rows = (
                    db.query(
                        ReceiptProcessingTask.chat_id,
                        ReceiptProcessingTask.message_id,
                        ReceiptProcessingTask.error,
                    )
                    .filter(
                        tuple_(
                            ReceiptProcessingTask.chat_id,
                            ReceiptProcessingTask.message_id,
                        ).in_(int_pairs),
                        ReceiptProcessingTask.status == "failed",
                    )
                    .all()
                )
                for cid, mid, err in rows:
                    failed_lookup[(cid, mid)] = err or "unknown error"

        _update_task_atomic(
            db, task_id,
            expected_status="processing",
            progress_json=json.dumps({
                "step": "classifying",
                "percent": 60,
            }),
        )

        # Step 7: Classify each candidate
        items: List[Dict[str, Any]] = []
        summary = {
            "total_receipt_candidates": len(receipt_candidates),
            "matched": 0,
            "missing_in_db": 0,
            "failed_parse": 0,
            "orphaned_in_db": 0,
        }
        matched_msg_keys: set = set()

        for m in receipt_candidates:
            key = (int(m.chat_id), int(m.message_id))
            msg_date = m.message_date.isoformat() if m.message_date else None
            preview = _text_preview(m.text)

            # Check if matched via direct transaction or linkage
            tx_id = tx_lookup.get(key) or linked_lookup.get(key)
            if tx_id:
                items.append({
                    "message_id": int(m.message_id),
                    "chat_id": int(m.chat_id),
                    "message_date": msg_date,
                    "text_preview": preview,
                    "category": "MATCHED",
                    "transaction_id": tx_id,
                    "can_auto_parse": False,
                })
                summary["matched"] += 1
                matched_msg_keys.add(key)
            elif key in failed_lookup:
                items.append({
                    "message_id": int(m.message_id),
                    "chat_id": int(m.chat_id),
                    "message_date": msg_date,
                    "text_preview": preview,
                    "category": "FAILED_PARSE",
                    "transaction_id": None,
                    "can_auto_parse": True,
                })
                summary["failed_parse"] += 1
            else:
                items.append({
                    "message_id": int(m.message_id),
                    "chat_id": int(m.chat_id),
                    "message_date": msg_date,
                    "text_preview": preview,
                    "category": "MISSING_IN_DB",
                    "transaction_id": None,
                    "can_auto_parse": True,
                })
                summary["missing_in_db"] += 1

        _update_task_atomic(
            db, task_id,
            expected_status="processing",
            progress_json=json.dumps({
                "step": "orphan_check",
                "percent": 80,
            }),
        )

        # Step 8: Orphaned transactions — exist in DB but source message not in history
        orphaned_txs = (
            db.query(Transaction.id, Transaction.source_chat_id, Transaction.source_message_id, Transaction.transaction_date)
            .filter(
                Transaction.source_chat_id.in_(chat_ids),
                Transaction.transaction_date >= period_start,
                Transaction.transaction_date <= period_end + timedelta(days=1),
                Transaction.source_message_id.isnot(None),
            )
            .all()
        )

        for tx in orphaned_txs:
            key = (int(tx.source_chat_id), int(tx.source_message_id))
            if key not in matched_msg_keys:
                # Check if the message exists in history at all
                msg_exists = (
                    db.query(TgChatMessage.id)
                    .filter(
                        TgChatMessage.chat_id == tx.source_chat_id,
                        TgChatMessage.message_id == tx.source_message_id,
                    )
                    .first()
                )
                if not msg_exists:
                    items.append({
                        "message_id": int(tx.source_message_id),
                        "chat_id": int(tx.source_chat_id),
                        "message_date": tx.transaction_date.isoformat() if tx.transaction_date else None,
                        "text_preview": None,
                        "category": "ORPHANED_IN_DB",
                        "transaction_id": tx.id,
                        "can_auto_parse": False,
                    })
                    summary["orphaned_in_db"] += 1

        # Step 9: Auto-parse MISSING_IN_DB if requested
        auto_parse_stats = {"queued": 0, "skipped": 0, "errors": 0}
        if auto_parse:
            _update_task_atomic(
                db, task_id,
                expected_status="processing",
                progress_json=json.dumps({
                    "step": "auto_parsing",
                    "percent": 90,
                }),
            )
            for item in items:
                if item["category"] in ("MISSING_IN_DB", "FAILED_PARSE") and item["can_auto_parse"]:
                    try:
                        q = _queue_message_for_parsing(
                            db,
                            chat_id=item["chat_id"],
                            message_id=item["message_id"],
                        )
                        if q:
                            auto_parse_stats["queued"] += 1
                        else:
                            auto_parse_stats["skipped"] += 1
                    except Exception:
                        auto_parse_stats["errors"] += 1

        # Step 10: Save results
        result = {
            "summary": summary,
            "items": items,
            "auto_parse": auto_parse_stats if auto_parse else None,
            "sync_warnings": sync_warnings,
        }
        _update_task_atomic(
            db, task_id,
            expected_status="processing",
            status="completed",
            progress_json=json.dumps({"step": "done", "percent": 100}),
            result_json=json.dumps(result, default=str),
        )


def _queue_message_for_parsing(
    db: Session,
    chat_id: int,
    message_id: int,
) -> bool:
    """Load raw message from history and queue it for receipt parsing.

    Returns ``True`` if queued, ``False`` if skipped (already exists).
    """
    msg = (
        db.query(TgChatMessage)
        .filter(
            TgChatMessage.chat_id == chat_id,
            TgChatMessage.message_id == message_id,
        )
        .first()
    )
    if not msg or not msg.raw_json:
        return False

    # Format the raw TDLib JSON into a flat message dict
    try:
        raw = json.loads(msg.raw_json)
    except Exception:
        return False

    formatted = format_tdlib_message(raw)
    if not formatted:
        return False

    task_data = build_task_data_from_message(chat_id, message_id, formatted)
    try:
        queue_receipt_task(task_data, force=False)
    except ValueError:
        # Message could be parsed between reconciliation snapshot and queue attempt.
        return False
    return True


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/start", response_model=ReconcileResponse)
async def reconciliation_start(
    payload: ReconcileRequest,
    db: Session = Depends(get_db_session),
) -> ReconcileResponse:
    """Start a reconciliation run as a background task."""
    # Validate dates
    try:
        period_start = _parse_date(payload.period_start)
        period_end = _parse_date(payload.period_end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

    if period_end < period_start:
        raise HTTPException(status_code=400, detail="period_end must be >= period_start")

    # Check sync status for each chat
    sync_warnings: List[Dict[str, Any]] = []
    for cid in payload.bot_chat_ids:
        cursor = db.get(TgHistoryCursor, cid)
        if not cursor:
            sync_warnings.append({
                "chat_id": cid,
                "warning": "not_synced",
                "message": f"Chat {cid} has not been synced yet",
            })
        elif cursor.status not in ("completed", "loading"):
            sync_warnings.append({
                "chat_id": cid,
                "warning": "sync_incomplete",
                "message": f"Chat {cid} sync status: {cursor.status}",
            })

    if payload.source == "tdlib":
        # Keep explicit source contract for forward compatibility.
        # Current implementation still reads from local tg_chat_messages store.
        sync_warnings.append(
            {
                "chat_id": 0,
                "warning": "source_fallback",
                "message": "source=tdlib requested; using local synced history for this run",
            }
        )

    # Create task
    task = AutomationTask(
        id=uuid4(),
        task_type="reconciliation",
        status="processing",
    )
    db.add(task)
    db.commit()

    # Launch background
    asyncio.ensure_future(
        _run_background_task(
            task.id,
            "reconciliation",
            _process_reconciliation(
                task_id=task.id,
                chat_ids=payload.bot_chat_ids,
                period_start=period_start,
                period_end=period_end,
                auto_parse=payload.auto_parse,
                sync_warnings=sync_warnings,
            ),
        )
    )

    return ReconcileResponse(
        task_id=task.id,
        status="started",
        message=(
            f"Reconciliation started for {len(payload.bot_chat_ids)} chat(s), "
            f"period {payload.period_start} — {payload.period_end}, source={payload.source}"
        ),
        sync_warnings=sync_warnings if sync_warnings else None,
    )


@router.get("/status/{task_id}", response_model=ReconcileStatusResponse)
async def reconciliation_status(
    task_id: UUID,
    db: Session = Depends(get_db_session),
) -> ReconcileStatusResponse:
    """Poll reconciliation task progress."""
    task = db.get(AutomationTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    progress = None
    if task.progress_json:
        try:
            progress = json.loads(task.progress_json)
        except Exception:
            pass

    return ReconcileStatusResponse(
        task_id=task.id,
        status=task.status,
        progress=progress,
    )


@router.get("/results/{task_id}", response_model=ReconcileResultsResponse)
async def reconciliation_results(
    task_id: UUID,
    category: Optional[str] = Query(default=None, description="Filter: MATCHED|MISSING_IN_DB|FAILED_PARSE|ORPHANED_IN_DB"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db_session),
) -> ReconcileResultsResponse:
    """Get reconciliation results with optional category filter and pagination."""
    task = db.get(AutomationTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != "completed" or not task.result_json:
        return ReconcileResultsResponse(
            task_id=task.id,
            status=task.status,
        )

    try:
        result = json.loads(task.result_json)
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupt task results")

    raw_items = result.get("items", [])
    summary_data = result.get("summary", {})
    sync_warnings = result.get("sync_warnings")

    # Filter by category
    if category:
        category_upper = category.upper()
        raw_items = [it for it in raw_items if it.get("category") == category_upper]

    total_items = len(raw_items)
    paginated = raw_items[offset: offset + limit]

    return ReconcileResultsResponse(
        task_id=task.id,
        status=task.status,
        summary=ReconciliationSummary(**summary_data) if summary_data else None,
        items=[ReconciliationItem(**it) for it in paginated],
        total_items=total_items,
        sync_warnings=sync_warnings,
    )


@router.get("/chat-sync-status", response_model=List[ChatSyncStatusItem])
async def chat_sync_status(
    chat_ids: str = Query(..., description="Comma-separated chat IDs"),
    db: Session = Depends(get_db_session),
) -> List[ChatSyncStatusItem]:
    """Get sync status for specified chats."""
    ids = [int(x.strip()) for x in chat_ids.split(",") if x.strip()]
    if not ids:
        return []

    result: List[ChatSyncStatusItem] = []
    for cid in ids:
        cursor = db.get(TgHistoryCursor, cid)
        if cursor:
            result.append(ChatSyncStatusItem(
                chat_id=cid,
                status=cursor.status or "idle",
                loaded_count=int(cursor.loaded_count or 0),
                error=cursor.error,
                started_at=cursor.started_at.isoformat() if cursor.started_at else None,
                finished_at=cursor.finished_at.isoformat() if cursor.finished_at else None,
            ))
        else:
            result.append(ChatSyncStatusItem(
                chat_id=cid,
                status="not_started",
            ))
    return result


@router.post("/{task_id}/auto-parse", response_model=AutoParseResponse)
async def auto_parse_missing(
    task_id: UUID,
    category: Optional[str] = Query(default=None, description="Filter category (MISSING_IN_DB, FAILED_PARSE, or omit for both)"),
    db: Session = Depends(get_db_session),
) -> AutoParseResponse:
    """Queue auto-parse for MISSING_IN_DB / FAILED_PARSE items from a completed reconciliation task."""
    task = db.get(AutomationTask, task_id)
    if not task or task.status != "completed" or not task.result_json:
        raise HTTPException(status_code=404, detail="Completed reconciliation task not found")

    try:
        result = json.loads(task.result_json)
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupt task results")

    items = result.get("items", [])
    parseable_categories = {"MISSING_IN_DB", "FAILED_PARSE"}
    if category:
        cat_upper = category.upper()
        if cat_upper not in parseable_categories:
            raise HTTPException(status_code=400, detail=f"Category must be one of {parseable_categories}")
        parseable_categories = {cat_upper}

    stats = {"queued": 0, "skipped": 0, "errors": 0}
    for item in items:
        if item.get("category") not in parseable_categories:
            continue
        if not item.get("can_auto_parse"):
            continue
        try:
            queued = _queue_message_for_parsing(
                db,
                chat_id=item["chat_id"],
                message_id=item["message_id"],
            )
            if queued:
                stats["queued"] += 1
            else:
                stats["skipped"] += 1
        except Exception:
            logger.exception("Auto-parse error for chat=%s msg=%s", item.get("chat_id"), item.get("message_id"))
            stats["errors"] += 1

    return AutoParseResponse(**stats)
