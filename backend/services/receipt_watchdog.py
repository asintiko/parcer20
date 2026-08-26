"""Durable recovery for stuck receipt processing and pending outbox work.

Usage (sync, safe to call from any context):
    from services.receipt_watchdog import sweep_stuck_receipt_tasks
    result = sweep_stuck_receipt_tasks()
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import and_, func, or_

from database.connection import get_db
from database.models import ReceiptProcessingTask, TgChatMessage

logger = logging.getLogger(__name__)


def sweep_stuck_receipt_tasks(timeout_seconds: int = 0) -> Dict[str, Any]:
    """Recover stale work with bounded retries, then dispatch due outbox rows."""
    timeout = int(timeout_seconds or os.getenv("RECEIPT_TASK_TIMEOUT_SECONDS", "600"))
    max_attempts = int(os.getenv("RECEIPT_MAX_PROCESSING_ATTEMPTS", "4"))
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=max(120, timeout))
    publish_lease_cutoff = now - timedelta(
        seconds=max(30, int(os.getenv("RECEIPT_OUTBOX_LEASE_SECONDS", "120")))
    )
    swept_ids: List[int] = []
    dead_rows: List[Dict[str, Any]] = []
    checked = 0
    with get_db() as db:
        rows = (
            db.query(ReceiptProcessingTask)
            .filter(
                or_(
                    and_(
                        ReceiptProcessingTask.status == "processing",
                        func.coalesce(
                            ReceiptProcessingTask.heartbeat_at,
                            ReceiptProcessingTask.updated_at,
                        ) < cutoff,
                    ),
                    and_(
                        ReceiptProcessingTask.status == "queued",
                        ReceiptProcessingTask.publish_state == "published",
                        func.coalesce(
                            ReceiptProcessingTask.published_at,
                            ReceiptProcessingTask.updated_at,
                        ) < cutoff,
                    ),
                    and_(
                        ReceiptProcessingTask.publish_state == "publishing",
                        func.coalesce(
                            ReceiptProcessingTask.heartbeat_at,
                            ReceiptProcessingTask.updated_at,
                        ) < publish_lease_cutoff,
                    ),
                )
            )
            .limit(100)
            .all()
        )
        checked = len(rows)
        for row in rows:
            try:
                attempts = int(row.processing_attempts or 0)
                reason = f"watchdog_timeout_{timeout}s"
                row.error = f"{row.error} | {reason}" if row.error else reason
                if attempts >= max_attempts:
                    row.status = "dead"
                    row.publish_state = "dead"
                    row.finished_at = now
                    row.next_retry_at = None
                    row.last_error_kind = "watchdog_exhausted"
                    dead_rows.append(
                        {
                            "task_id": str(row.task_id),
                            "payload_json": row.payload_json or "{}",
                            "error": row.error,
                            "attempts": attempts,
                        }
                    )
                else:
                    row.status = "retry"
                    row.publish_state = "retry"
                    row.next_retry_at = now
                    row.last_error_kind = "watchdog_timeout"
                message = (
                    db.query(TgChatMessage)
                    .filter(
                        TgChatMessage.chat_id == row.chat_id,
                        TgChatMessage.message_id == row.message_id,
                    )
                    .first()
                )
                if message:
                    message.processing_status = row.status
                    message.processing_error_code = row.last_error_kind
                    message.processing_error_text = row.error
                swept_ids.append(int(row.id))
            except Exception:  # noqa: BLE001
                logger.exception("Watchdog sweep failed for receipt task %s", row.id)
        db.commit()
    if dead_rows:
        from workers.celery_worker import _push_to_dlq

        for dead in dead_rows:
            _push_to_dlq(
                celery_task_id=dead["task_id"],
                task_data_json=dead["payload_json"],
                error=RuntimeError(dead["error"]),
                tb_text="",
                retries=dead["attempts"],
                reason="watchdog_exhausted",
            )

    from workers.celery_worker import dispatch_pending_receipt_tasks

    dispatch_result = dispatch_pending_receipt_tasks()
    if swept_ids:
        logger.warning(
            "Receipt watchdog swept %s stuck tasks: %s",
            len(swept_ids),
            swept_ids[:20],
        )
    return {
        "checked": checked,
        "swept": len(swept_ids),
        "retried": len(swept_ids) - len(dead_rows),
        "dead": len(dead_rows),
        "ids": swept_ids,
        "outbox": dispatch_result,
    }


def cleanup_old_receipt_tasks(retention_days: int = 0) -> Dict[str, Any]:
    """Delete done receipt tasks older than retention_days.

    Failed/stuck tasks kept indefinitely (so admin can investigate).
    """
    days = int(retention_days or os.getenv("RECEIPT_TASK_RETENTION_DAYS", "30"))
    cutoff = datetime.utcnow() - timedelta(days=max(1, days))
    deleted = 0
    with get_db() as db:
        deleted = (
            db.query(ReceiptProcessingTask)
            .filter(
                ReceiptProcessingTask.status == "done",
                ReceiptProcessingTask.updated_at < cutoff,
            )
            .delete(synchronize_session=False)
        )
        db.commit()
    if deleted:
        logger.info("Receipt task retention: deleted %s done rows older than %sd", deleted, days)
    return {"deleted": int(deleted), "retention_days": days}
