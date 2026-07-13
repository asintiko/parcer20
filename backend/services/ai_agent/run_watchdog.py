"""Watchdog for stuck agent runs.

Sweeps `agent_runs` rows that are still `queued` or `processing` past their
soft deadline and marks them `failed`. Runs as a Celery beat-driven task,
configurable via env:

    AGENT_RUN_TIMEOUT_SECONDS   default 600 (10 min)

Usage:
    from services.ai_agent.run_watchdog import sweep_stuck_runs
    result = sweep_stuck_runs()  # synchronous, safe to call from any context
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List

from database.connection import get_db
from database.models import AgentRun
from services.ai_agent.session_service import create_run_event, update_run

logger = logging.getLogger(__name__)


def sweep_stuck_runs(timeout_seconds: int = 0) -> Dict[str, Any]:
    """Mark stuck runs as failed. Returns {checked, swept, ids}.

    A run is considered stuck if its `updated_at` is older than
    `now - timeout_seconds` and its status is queued/processing.
    """
    timeout = int(timeout_seconds or os.getenv("AGENT_RUN_TIMEOUT_SECONDS", "600"))
    cutoff = datetime.utcnow() - timedelta(seconds=max(60, timeout))
    swept_ids: List[str] = []
    checked = 0
    with get_db() as db:
        rows = (
            db.query(AgentRun)
            .filter(
                AgentRun.status.in_(["queued", "processing"]),
                AgentRun.updated_at < cutoff,
            )
            .limit(50)
            .all()
        )
        checked = len(rows)
        for row in rows:
            try:
                payload = {
                    "message": "Запрос превысил таймаут и был отменён.",
                    "cards": [
                        {
                            "type": "warning",
                            "title": "Run timeout",
                            "body": f"updated_at={row.updated_at}",
                        }
                    ],
                    "tool_results": [],
                    "navigation_targets": [],
                    "requires_confirmation": False,
                    "confirmation_payload": None,
                    "ui_action": None,
                }
                update_run(
                    db,
                    run_id=row.id,
                    status="failed",
                    progress={"step": "timeout", "percent": 100},
                    result=payload,
                    error_text=f"watchdog_timeout_{timeout}s",
                    requires_confirmation=False,
                )
                create_run_event(
                    db,
                    run_id=row.id,
                    event_type="failed",
                    label="Watchdog: timeout",
                    status="failed",
                    payload={"timeout_seconds": timeout},
                )
                swept_ids.append(str(row.id))
            except Exception:  # noqa: BLE001
                logger.exception("Watchdog sweep failed for run %s", row.id)
    return {"checked": checked, "swept": len(swept_ids), "ids": swept_ids}
