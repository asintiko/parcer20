"""Watchdog for stuck receipt processing tasks.

Sweeps `receipt_processing_tasks` rows that are still `qued` or `processing`
past their soft deadline and marks them `failed`. Designed for symmetry with
`services/ai_agent/run_watchdog.py`.

Usage (sync, safe to call from any context):
    from services.receipt_watchdog import sweep_stuck_receipt_tasks
    result = sweep_stuck_receipt_tasks()
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List

from database.connection import get_db
from database.models import ReceiptProcessingTask

logger = logging.getLogger(__name__)


def sweep_stuck_receipt_tasks(timeout_seconds: int = 0) -> Dict[str, Any]:
    """Mark stuck receipt tasks as failed. Returns {checked, swept, ids}.

    A task is considered stuck if its `updated_at` is older than
    `now - timeout_seconds` and its status is queued/processing.
    """
    timeout = int(timeout_seconds or os.getenv("RECEIPT_TASK_TIMEOUT_SECONDS", "600"))
    cutoff = datetime.utcnow() - timedelta(seconds=max(120, timeout))
    swept_ids: List[int] = []
    checked = 0
    with get_db() as db:
        rows = (
            db.query(ReceiptProcessingTask)
            .filter(
                ReceiptProcessingTask.status.in_(["queued", "processing"]),
                ReceiptProcessingTask.updated_at < cutoff,
            )
            .limit(100)
            .all()
        )
        checked = len(rows)
        for row in rows:
            try:
                row.status = "failed"
                row.error = (row.error or "") + (
                    f" | watchdog_timeout_{timeout}s"
                    if row.error and "watchdog_timeout" not in row.error
                    else f"watchdog_timeout_{timeout}s"
                )
                swept_ids.append(int(row.id))
            except Exception:  # noqa: BLE001
                logger.exception("Watchdog sweep failed for receipt task %s", row.id)
        db.commit()
    if swept_ids:
        logger.warning(
            "Receipt watchdog swept %s stuck tasks: %s",
            len(swept_ids),
            swept_ids[:20],
        )
    return {"checked": checked, "swept": len(swept_ids), "ids": swept_ids}


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
