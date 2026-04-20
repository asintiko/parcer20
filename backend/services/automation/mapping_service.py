from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from database.models import AutomationTask, Transaction


async def start_mapping_analysis(
    db: Session,
    *,
    current_user: Dict[str, Any],
    scope: Optional[dict],
    limit: int = 100,
    only_unmapped: bool = True,
    currency_filter: Optional[str] = None,
) -> Dict[str, Any]:
    from api.routes.automation import (
        BATCH_APPLY_MAX_ITEMS,
        _apply_locked_periods_filter,
        _apply_scope_filter,
        _run_background_task,
        process_transactions_batch,
    )

    query = db.query(Transaction)
    query = _apply_scope_filter(query, scope)
    query = _apply_locked_periods_filter(query, db)
    if only_unmapped:
        query = query.filter((Transaction.application_mapped == None) | (Transaction.application_mapped == ""))  # noqa: E711
    if currency_filter:
        query = query.filter(Transaction.currency == currency_filter)
    safe_limit = min(max(1, int(limit or 100)), max(1, int(BATCH_APPLY_MAX_ITEMS)))
    txs = query.order_by(Transaction.transaction_date.desc()).limit(safe_limit).all()

    task_id = uuid4()
    if not txs:
        task = AutomationTask(
            id=task_id,
            task_type="mapping",
            status="completed",
            progress_json=json.dumps({"total": 0, "processed": 0, "percent": 100}),
            result_json=json.dumps({"suggestions_count": 0, "high_confidence": 0, "low_confidence": 0}),
        )
        db.add(task)
        db.commit()
        return {"task_id": str(task_id), "status": "empty", "count": 0}

    task = AutomationTask(
        id=task_id,
        task_type="mapping",
        status="pending",
        progress_json=json.dumps({"total": len(txs), "processed": 0, "percent": 0}),
    )
    db.add(task)
    db.commit()

    asyncio.create_task(
        _run_background_task(
            task_id,
            f"automation-analyze-{task_id}",
            process_transactions_batch(task_id, [int(t.id) for t in txs]),
        )
    )
    return {"task_id": str(task_id), "status": "started", "count": len(txs)}
