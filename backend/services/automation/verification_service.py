from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from database.models import AutomationTask, Transaction


async def start_verification_analysis(
    db: Session,
    *,
    current_user: Dict[str, Any],
    scope: Optional[dict],
    limit: int = 50,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Dict[str, Any]:
    from api.routes.automation import (
        BATCH_APPLY_MAX_ITEMS,
        _apply_locked_periods_filter,
        _apply_scope_filter,
        _run_background_task,
        process_verification_batch,
    )

    query = db.query(Transaction).filter(Transaction.raw_message != None, Transaction.raw_message != "")  # noqa: E711
    query = _apply_scope_filter(query, scope)
    query = _apply_locked_periods_filter(query, db)
    if date_from:
        query = query.filter(Transaction.transaction_date >= date_from)
    if date_to:
        query = query.filter(Transaction.transaction_date <= date_to)
    safe_limit = min(max(1, int(limit or 50)), max(1, int(BATCH_APPLY_MAX_ITEMS)))
    txs = query.order_by(Transaction.transaction_date.desc()).limit(safe_limit).all()

    task_id = uuid4()
    if not txs:
        task = AutomationTask(
            id=task_id,
            task_type="verification",
            status="completed",
            progress_json=json.dumps({"total": 0, "processed": 0, "percent": 100}),
            result_json=json.dumps({"total_verified": 0, "transactions_with_errors": 0, "total_corrections": 0}),
        )
        db.add(task)
        db.commit()
        return {"task_id": str(task_id), "status": "empty", "count": 0}

    task = AutomationTask(
        id=task_id,
        task_type="verification",
        status="pending",
        progress_json=json.dumps({"total": len(txs), "processed": 0, "percent": 0}),
    )
    db.add(task)
    db.commit()

    asyncio.create_task(
        _run_background_task(
            task_id,
            f"automation-verify-{task_id}",
            process_verification_batch(task_id, [int(t.id) for t in txs]),
        )
    )
    return {"task_id": str(task_id), "status": "started", "count": len(txs)}
